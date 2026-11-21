"""unfake_alpha: give a generated image with a painted-on "transparency" checkerboard (or a flat painted background)
real transparency. Needs Pillow and numpy (pip install pillow numpy); no numpy? unfake_alpha.mjs does the
same with plain node.

    python unfake_alpha.py <image or folder> [--out DIR] [--bg checker|#rrggbb] [--floor 0.03] [--preview]

Writes <name>_alpha.png beside each input (or into --out). --preview also writes <name>_alpha_preview.png: the result
on near-black (#070c0a) next to it on magenta, so leftover background shows up at a glance.

How it works (the longer walkthrough is in the README):
  Every pixel of the picture is   seen = alpha * art + (1 - alpha) * background.
  We know `seen`. If we also know the background behind each pixel, we can solve for alpha and the art's own colour.
  1. Find the background. A fake checker is two flat greys in a grid. Grey means red = green = blue, which glowing
     coloured art almost never is, so: collect the near-grey pixels, find the two grey levels, then find the square
     size and where the grid starts from where light and dark meet. That rebuilds the background behind every pixel,
     including under the art. (A flat painted background, e.g. --bg #000000, skips all that.)
  2. Pixels that are grey and between the two levels ARE background: alpha 0. This is the step that beats the
     watermark. Its nudges are a few units, too small to make a grey pixel stop being grey, so they vanish with it.
     (A magic wand with tolerance compares colours to one picked colour, so the same nudges make it stop and start.)
  3. Everything else gets "colour to alpha" against its own background: the smallest alpha that explains the pixel
     with an art colour that's still a real colour (0..255 in every channel). Then the art colour is worked out by
     taking the background back out. Glows keep their soft fall-off as real partial transparency.
  4. Alphas under --floor (a few percent: leftover noise) go to 0.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def find_levels(v, neutral):
    """The background's grey levels: the biggest peaks in the histogram of near-grey pixels."""
    h = np.bincount(np.clip(v[neutral].round().astype(int), 0, 255), minlength=256).astype(float)
    h = np.convolve(h, np.ones(5) / 5, mode='same')  # smooth, so one peak doesn't count twice
    a = int(h.argmax())
    h2 = h.copy()
    h2[max(0, a - 15):a + 16] = 0  # the second level must differ by more than 15
    b = int(h2.argmax())
    if h2[b] < 0.15 * h[a]:
        return [a]  # one level: a flat background
    return sorted([a, b])


def grid_lines(cls, axis):
    """Where the checker's lines are along one axis (columns for axis=1, rows for axis=0), from where light (1)
    meets dark (0); cls is -1 where unsure. Generated checkers drift (squares of 16, 17, 15... px), so each line is
    found on its own: the rough spacing comes from the rhythm of the edges (a Fourier transform), then every line
    is snapped to the strongest edge near where it should be, or left where it should be if art hides it."""
    a = np.moveaxis(cls, axis, 1)
    known = (a[:, 1:] >= 0) & (a[:, :-1] >= 0)
    e = (known & (a[:, 1:] != a[:, :-1])).sum(0).astype(float)  # light/dark changes between column i and i+1
    n = len(e) + 1
    if e.max() == 0:
        return None
    spec = np.abs(np.fft.rfft(e - e.mean()))
    ks = np.arange(len(spec))
    ok = (ks >= n / 200) & (ks <= n / 3)  # squares between 3 and 200 px
    if not ok.any():
        return None
    k = int(ks[ok][spec[ok].argmax()])
    # octave check (as in pitch detection): sharp edges echo at 2x, 3x the true rhythm, and an echo can come out
    # loudest. If the rhythm at half (or a third of) the frequency is nearly as strong, that's the real one.
    for div in (2, 3):
        while True:
            lo_k = int(round(k / div))
            if lo_k < n / 200:
                break
            j = lo_k + int(np.argmax(spec[max(1, lo_k - 1):lo_k + 2])) - (1 if lo_k > 1 else 0)
            if spec[j] >= 0.5 * spec[k]:
                k = j
            else:
                break
    if 0 < k < len(spec) - 1:  # refine between bins
        y0, y1, y2 = spec[k - 1], spec[k], spec[k + 1]
        den = y0 - 2 * y1 + y2
        k = k + (0.5 * (y0 - y2) / den if den else 0)
    p = n / k  # the spacing of the lines
    strong = e.max() * 0.15
    start = int(e.argmax())
    lines = {start + 1}
    for step in (1, -1):  # walk out from the clearest line in both directions
        x = start + 1
        while True:
            want = x + step * p
            lo, hi = int(round(want - p / 4)), int(round(want + p / 4))
            if hi < 1 or lo > n - 1:
                break
            win = e[max(0, lo - 1):min(len(e), hi)]
            if win.size and win.max() >= strong:
                x = max(0, lo - 1) + int(win.argmax()) + 1
            else:
                x = want
            lines.add(int(round(x)))
    return np.array(sorted(l for l in lines if 0 < l < n)), p


def unfake(path, out_dir=None, bg='checker', floor=0.03, preview=False, quiet=False):
    im = Image.open(path).convert('RGBA')
    px = np.asarray(im).astype(np.float32)
    C, A0 = px[..., :3], px[..., 3] / 255
    H, W = C.shape[:2]
    v = C.mean(-1)
    spread = C.max(-1) - C.min(-1)
    say = (lambda *a: None) if quiet else print
    opaque = A0 > 0.98
    if opaque.mean() < 0.5:  # mostly see-through already: nothing painted to take out
        say(f'{os.path.basename(path)}: already has real transparency ({1 - opaque.mean():.0%} see-through); skipped')
        return None
    neutral = (spread <= 10) & opaque  # grey: red, green and blue within 10 of each other

    # 1. the background behind every pixel
    if bg != 'checker':
        rgb = np.array([int(bg.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
        B = np.broadcast_to(rgb, C.shape).astype(np.float32)
        lo = hi = float(rgb.mean())
        say(f'{os.path.basename(path)}: flat background {bg}')
    else:
        levels = find_levels(v, neutral)
        if len(levels) == 1:
            B = np.full(C.shape, levels[0], np.float32)
            lo = hi = levels[0]
            say(f'{os.path.basename(path)}: flat grey background, level {levels[0]}')
        else:
            dark, light = levels
            tol = min(12, (light - dark) / 3)
            cls = np.full((H, W), -1, np.int8)
            cls[neutral & (abs(v - light) <= tol)] = 1
            cls[neutral & (abs(v - dark) <= tol)] = 0
            gx, gy = grid_lines(cls, 1), grid_lines(cls, 0)
            if gx is None or gy is None:
                sys.exit(f'{path}: found two greys ({dark}, {light}) but no checker grid; try --bg #rrggbb')
            (lx, sx), (ly, sy) = gx, gy
            # each pixel's square, counted from the lines; light and dark alternate between neighbours
            ix = np.searchsorted(lx, np.arange(W), side='right')
            iy = np.searchsorted(ly, np.arange(H), side='right')
            par = (iy[:, None] + ix[None, :]) % 2
            s = (sx + sy) / 2
            known = cls >= 0
            light_par = 0 if (cls[known & (par == 0)] == 1).mean() > 0.5 else 1
            grey = np.where(par == light_par, light, dark).astype(np.float32)
            fit = ((grey[known] == light) == (cls[known] == 1)).mean()
            B = np.repeat(grey[..., None], 3, -1)
            lo, hi = dark, light
            say(f'{os.path.basename(path)}: checker of {dark} and {light}, squares about {s:.1f}px '
                f'({len(lx)} x {len(ly)} lines); the grid explains {fit:.1%} of the grey pixels')
            if fit < 0.9:
                say('  (under 90%: the painted checker is irregular; edges of the art may keep a faint grid)')

    # 2. grey pixels between the background levels are background, watermark nudges and all
    is_bg = neutral & (v >= lo - 12) & (v <= hi + 12)

    # 3. colour to alpha: the LEAST opacity that explains each pixel with a real colour. (One look at one pixel can't
    # say more than that; the README says why the checker can't reliably tell us the rest.)
    d = C - B
    up = np.where(d > 0, d / np.maximum(255 - B, 1), 0)  # brighter than the background: how far towards white
    down = np.where(d < 0, -d / np.maximum(B, 1), 0)  # darker: how far towards black
    a = np.maximum(up, down).max(-1)

    a[is_bg] = 0
    # the art's own colour: take the background's share back out (seen = a*art + (1-a)*background)
    art = np.clip((C - (1 - a)[..., None] * B) / np.maximum(a, 1e-6)[..., None], 0, 255)

    # 4. leftover specks below the floor
    a = np.clip((a - floor) / (1 - floor), 0, 1) * A0
    out = np.dstack([art, a * 255]).round().astype(np.uint8)
    out[a == 0, :3] = 0

    stem = os.path.splitext(os.path.basename(path))[0]
    dest = os.path.join(out_dir or os.path.dirname(path) or '.', stem + '_alpha.png')
    Image.fromarray(out, 'RGBA').save(dest, optimize=True)
    say(f'  -> {dest}  ({(a > 0).mean():.1%} of pixels kept)')
    if preview:
        res = Image.fromarray(out, 'RGBA')
        pv = Image.new('RGB', (W * 2, H))
        for i, colour in enumerate(((7, 12, 10), (255, 0, 255))):
            tile = Image.new('RGB', (W, H), colour)
            tile.paste(res, (0, 0), res)
            pv.paste(tile, (i * W, 0))
        pv.save(dest[:-4] + '_preview.png', optimize=True)
    return dest


def main():
    ap = argparse.ArgumentParser(description='Real transparency for images with a painted-on background.')
    ap.add_argument('src', help='an image, or a folder of them')
    ap.add_argument('--out', help='folder for the results (default: beside each input)')
    ap.add_argument('--bg', default='checker', help="'checker' (default) or a flat colour like #000000")
    ap.add_argument('--floor', type=float, default=0.03, help='alphas below this become 0 (default 0.03)')
    ap.add_argument('--preview', action='store_true', help='also write a check image (on dark and on magenta)')
    o = ap.parse_args()
    if o.out:
        os.makedirs(o.out, exist_ok=True)
    files = [o.src] if os.path.isfile(o.src) else sorted(
        os.path.join(o.src, f) for f in os.listdir(o.src)
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')) and '_alpha' not in f)
    for f in files:
        unfake(f, o.out, o.bg, o.floor, o.preview)


if __name__ == '__main__':
    main()
