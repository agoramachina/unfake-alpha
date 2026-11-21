"""unfake_core: the unfake_alpha steps in plain Python, no numpy (Krita's own Python doesn't ship it).
The same steps as unfake_alpha.py; the walkthrough is in the README (https://github.com/agoramachina/unfake-alpha).

unfake(r, g, b, a, W, H, bg=None, floor=0.03, tick=None) -> ((r, g, b, a), report) or (None, report)
    r, g, b, a: one value per pixel (0..255), rows top to bottom. bg: None for "find the checker", or an (r, g, b)
    flat background. tick(fraction) is called now and then (for a progress bar); if it returns True, stop.
"""
import math


class Cancelled(Exception):
    pass


def _levels(v, neutral):
    h = [0.0] * 256
    for x, n in zip(v, neutral):
        if n:
            h[min(255, max(0, int(round(x))))] += 1
    s = [sum(h[max(0, i - 2):i + 3]) / 5 for i in range(256)]  # smoothed, so one peak counts once
    a = max(range(256), key=s.__getitem__)
    s2 = [0 if abs(i - a) <= 15 else x for i, x in enumerate(s)]  # the second level must differ by more than 15
    b = max(range(256), key=s2.__getitem__)
    return [a] if s2[b] < 0.15 * s[a] else sorted([a, b])


def _grid_lines(e, n):
    """Grid lines from e[i] = how often light meets dark between position i and i+1. The rough spacing comes from the
    rhythm (a discrete Fourier transform), with an octave check; then each line snaps to the nearest strong edge."""
    emax = max(e)
    if not emax:
        return None
    N = len(e)
    mean = sum(e) / N
    d = [x - mean for x in e]
    spec = []
    for k in range(N // 2 + 1):
        re = im = 0.0
        w = 2 * math.pi * k / N
        for i, x in enumerate(d):
            re += x * math.cos(w * i)
            im -= x * math.sin(w * i)
        spec.append(math.hypot(re, im))
    ks = [i for i in range(len(spec)) if n / 200 <= i <= n / 3]
    if not ks:
        return None
    k = max(ks, key=spec.__getitem__)
    for div in (2, 3):  # octave check: an echo of the rhythm can come out loudest
        while True:
            lo = round(k / div)
            if lo < n / 200:
                break
            j = max(range(max(1, lo - 1), min(len(spec), lo + 2)), key=spec.__getitem__)
            if spec[j] >= 0.5 * spec[k]:
                k = j
            else:
                break
    kf = float(k)
    if 0 < k < len(spec) - 1:
        y0, y1, y2 = spec[k - 1], spec[k], spec[k + 1]
        den = y0 - 2 * y1 + y2
        if den:
            kf = k + 0.5 * (y0 - y2) / den
    p = n / kf
    strong = emax * 0.15
    start = e.index(emax)
    lines = {start + 1}
    for step in (1, -1):
        x = start + 1
        while True:
            want = x + step * p
            lo, hi = int(round(want - p / 4)), int(round(want + p / 4))
            if hi < 1 or lo > n - 1:
                break
            rng = range(max(0, lo - 1), min(len(e), hi))
            best = max(rng, key=e.__getitem__) if len(rng) else -1
            x = best + 1 if best >= 0 and e[best] >= strong else want
            lines.add(int(round(x)))
    return sorted(l for l in lines if 0 < l < n), p


def _index(lines, n):
    out, i = [0] * n, 0
    for x in range(n):
        while i < len(lines) and lines[i] <= x:
            i += 1
        out[x] = i
    return out


def unfake(r, g, b, a, W, H, bg=None, floor=0.03, tick=None):
    N = W * H

    def step(f):
        if tick and tick(f):
            raise Cancelled()

    v = [(x + y + z) / 3 for x, y, z in zip(r, g, b)]
    n_op = sum(1 for al in a if al > 250)
    if n_op < N / 2:
        return None, f'already has real transparency ({1 - n_op / N:.0%} see-through); nothing to do'
    neutral = [al > 250 and max(x, y, z) - min(x, y, z) <= 10 for al, x, y, z in zip(a, r, g, b)]
    step(0.1)

    # 1. the background behind every pixel (a grey per pixel, or one flat colour)
    flat = None
    grey = None
    if bg is not None:
        flat = tuple(bg)
        lo = hi = sum(flat) / 3
        report = 'flat background #%02x%02x%02x' % flat
    else:
        levels = _levels(v, neutral)
        if len(levels) == 1:
            flat = (levels[0],) * 3
            lo = hi = levels[0]
            report = f'flat grey background, level {levels[0]}'
        else:
            dark, light = levels
            tol = min(12, (light - dark) / 3)
            cls = bytearray(N)  # 0 unknown, 1 dark, 2 light
            for j in range(N):
                if neutral[j]:
                    if abs(v[j] - light) <= tol:
                        cls[j] = 2
                    elif abs(v[j] - dark) <= tol:
                        cls[j] = 1
            step(0.25)
            ex, ey = [0] * (W - 1), [0] * (H - 1)
            for y in range(H):
                row = cls[y * W:(y + 1) * W]
                for x, (p, q) in enumerate(zip(row, row[1:])):
                    if p and q and p != q:
                        ex[x] += 1
                if y < H - 1:
                    nxt = cls[(y + 1) * W:(y + 2) * W]
                    ey[y] += sum(1 for p, q in zip(row, nxt) if p and q and p != q)
            step(0.45)
            gx, gy = _grid_lines(ex, W), _grid_lines(ey, H)
            if not gx or not gy:
                raise ValueError(f'found two greys ({dark}, {light}) but no checker grid; try a flat background colour')
            ix, iy = _index(gx[0], W), _index(gy[0], H)
            l0 = k0 = 0
            for y in range(H):
                for x in range(W):
                    c = cls[y * W + x]
                    if c and (ix[x] + iy[y]) % 2 == 0:
                        k0 += 1
                        l0 += c == 2
            light_par = 0 if k0 and l0 / k0 > 0.5 else 1
            grey = [0] * N
            fit_n = fit_k = 0
            for y in range(H):
                for x in range(W):
                    j = y * W + x
                    gv = light if (ix[x] + iy[y]) % 2 == light_par else dark
                    grey[j] = gv
                    c = cls[j]
                    if c:
                        fit_k += 1
                        fit_n += (gv == light) == (c == 2)
            lo, hi = dark, light
            fit = fit_n / max(1, fit_k)
            report = (f'checker of {dark} and {light}, squares about {(gx[1] + gy[1]) / 2:.1f}px; '
                      f'the grid explains {fit:.1%} of the grey pixels')
            if fit < 0.9:
                report += " (irregular checker: the art's edges may keep a faint grid)"
    step(0.6)

    # 2-4. grey pixels between the levels are background; colour to alpha on the rest; the floor
    outr, outg, outb, outa = bytearray(N), bytearray(N), bytearray(N), bytearray(N)
    kept = 0
    for j in range(N):
        if not j % 65536:
            step(0.6 + 0.4 * j / N)
        if neutral[j] and lo - 12 <= v[j] <= hi + 12:
            continue
        if flat:
            br, bgv, bb = flat
        else:
            br = bgv = bb = grey[j]
        al = 0.0
        for s, bk in ((r[j], br), (g[j], bgv), (b[j], bb)):
            d = s - bk
            t = d / max(255 - bk, 1) if d > 0 else (-d / max(bk, 1) if d < 0 else 0.0)
            if t > al:
                al = t
        a2 = min(1.0, max(0.0, (al - floor) / (1 - floor))) * (a[j] / 255)
        if a2 <= 0:
            continue
        kept += 1
        inv = 1 / max(al, 1e-6)
        outr[j] = min(255, max(0, round(br + (r[j] - br) * inv)))
        outg[j] = min(255, max(0, round(bgv + (g[j] - bgv) * inv)))
        outb[j] = min(255, max(0, round(bb + (b[j] - bb) * inv)))
        outa[j] = round(a2 * 255)
    report += f'; {kept / N:.1%} of pixels kept'
    return (outr, outg, outb, outa), report
