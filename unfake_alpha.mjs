// unfake_alpha.mjs: the node twin of unfake_alpha.py (same steps, same results).
// Gives a generated image with a painted-on "transparency" checkerboard (or a flat painted background) real
// transparency. Nothing to install: it reads and writes PNGs itself with node's built-in zlib (PNG only; the Python
// one also opens JPG and WebP).
//   node unfake_alpha.mjs <image.png or folder> [--out DIR] [--bg checker|#rrggbb] [--floor 0.03] [--preview]
// The walkthrough of how and why is in the README; the comments here follow the same numbered steps.
import { readFileSync, writeFileSync, readdirSync, statSync, mkdirSync } from 'node:fs';
import { inflateSync, deflateSync } from 'node:zlib';
import path from 'node:path';

// ---- a small PNG reader and writer (8-bit; grey, grey+alpha, RGB, RGBA and palette; not interlaced)
function readPng(file) {
  const buf = readFileSync(file);
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error(`${file}: not a PNG`);
  let p = 8, W, H, depth, type, interlace, pal = null, trns = null;
  const idat = [];
  while (p < buf.length) {
    const len = buf.readUInt32BE(p), kind = buf.toString('latin1', p + 4, p + 8), d = buf.subarray(p + 8, p + 8 + len);
    if (kind === 'IHDR') [W, H, depth, type, interlace] = [d.readUInt32BE(0), d.readUInt32BE(4), d[8], d[9], d[12]];
    else if (kind === 'PLTE') pal = d;
    else if (kind === 'tRNS') trns = d;
    else if (kind === 'IDAT') idat.push(d);
    else if (kind === 'IEND') break;
    p += 12 + len;
  }
  if (interlace) throw new Error(`${file}: interlaced PNGs aren't supported (re-save it, or use the .py)`);
  if (depth !== 8 && depth !== 16) throw new Error(`${file}: ${depth}-bit PNGs aren't supported (use the .py)`);
  const ch = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[type], bpp = ch * (depth / 8), stride = W * bpp;
  const raw = inflateSync(Buffer.concat(idat)), px = Buffer.alloc(H * stride);
  for (let y = 0; y < H; y++) {  // undo each row's filter (the trick PNG uses to compress better)
    const f = raw[y * (stride + 1)], src = y * (stride + 1) + 1, row = y * stride, up = row - stride;
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? px[row + i - bpp] : 0, b = y ? px[up + i] : 0, c = y && i >= bpp ? px[up + i - bpp] : 0;
      let pr;
      if (f === 0) pr = 0; else if (f === 1) pr = a; else if (f === 2) pr = b; else if (f === 3) pr = (a + b) >> 1;
      else { const q = a + b - c, pa = Math.abs(q - a), pb = Math.abs(q - b), pc = Math.abs(q - c); pr = pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      px[row + i] = (raw[src + i] + pr) & 255;
    }
  }
  const rgba = new Uint8Array(W * H * 4), step = depth / 8;
  for (let j = 0; j < W * H; j++) {
    const s = j * bpp, g = k => px[s + k * step];
    let r, gg, b, a = 255;
    if (type === 0) r = gg = b = g(0);
    else if (type === 4) { r = gg = b = g(0); a = g(1); }
    else if (type === 2) [r, gg, b] = [g(0), g(1), g(2)];
    else if (type === 6) [r, gg, b, a] = [g(0), g(1), g(2), g(3)];
    else { const i = px[s]; [r, gg, b] = [pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]]; a = trns && i < trns.length ? trns[i] : 255; }
    rgba.set([r, gg, b, a], j * 4);
  }
  return { W, H, rgba };
}
const CRC = new Int32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c; });
const crc32 = b => { let c = -1; for (const x of b) c = CRC[(c ^ x) & 255] ^ (c >>> 8); return (c ^ -1) >>> 0; };
function chunk(kind, data) {
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0); out.write(kind, 4, 'latin1'); data.copy(out, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
  return out;
}
function writePng(file, W, H, rgba) {
  const raw = Buffer.alloc(H * (W * 4 + 1));
  for (let y = 0; y < H; y++) Buffer.from(rgba.buffer, rgba.byteOffset + y * W * 4, W * 4).copy(raw, y * (W * 4 + 1) + 1);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(H, 4); ihdr[8] = 8; ihdr[9] = 6;
  writeFileSync(file, Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))]));
}

// ---- 1. finding the background
// the two grey levels: the biggest peaks in the histogram of near-grey pixels (smoothed, so one peak counts once)
function findLevels(v, neutral) {
  const h = new Float64Array(256);
  for (let j = 0; j < v.length; j++) if (neutral[j]) h[Math.min(255, Math.max(0, Math.round(v[j])))]++;
  const s = h.map((_, i) => { let t = 0; for (let k = -2; k <= 2; k++) t += h[i + k] || 0; return t / 5; });
  const a = s.indexOf(Math.max(...s));
  const s2 = s.map((x, i) => (Math.abs(i - a) <= 15 ? 0 : x));
  const b = s2.indexOf(Math.max(...s2));
  return s2[b] < 0.15 * s[a] ? [a] : [Math.min(a, b), Math.max(a, b)];
}
// where the checker's lines are along one axis: the rough spacing from the rhythm of the edges (a Fourier
// transform, with an octave check), then each line snapped to the strongest edge near where it should be
function gridLines(cls, W, H, alongX) {
  const n = alongX ? W : H, m = alongX ? H : W, e = new Float64Array(n - 1);
  for (let i = 0; i < n - 1; i++) for (let j = 0; j < m; j++) {
    const a = alongX ? cls[j * W + i] : cls[i * W + j], b = alongX ? cls[j * W + i + 1] : cls[(i + 1) * W + j];
    if (a >= 0 && b >= 0 && a !== b) e[i]++;
  }
  const emax = Math.max(...e);
  if (!emax) return null;
  const mean = e.reduce((x, y) => x + y) / e.length, N = e.length, spec = [];
  for (let k = 0; k <= N / 2; k++) {  // a plain discrete Fourier transform: fine for a thousand numbers
    let re = 0, im = 0;
    for (let i = 0; i < N; i++) { const t = (2 * Math.PI * k * i) / N; re += (e[i] - mean) * Math.cos(t); im -= (e[i] - mean) * Math.sin(t); }
    spec.push(Math.hypot(re, im));
  }
  let k = -1;
  for (let i = 0; i < spec.length; i++) if (i >= n / 200 && i <= n / 3 && (k < 0 || spec[i] > spec[k])) k = i;
  if (k < 0) return null;
  for (const div of [2, 3]) for (;;) {  // octave check: an echo of the rhythm can come out loudest
    const lo = Math.round(k / div);
    if (lo < n / 200) break;
    let j = Math.max(1, lo - 1);
    for (let i = j; i <= lo + 1 && i < spec.length; i++) if (spec[i] > spec[j]) j = i;
    if (spec[j] >= 0.5 * spec[k]) k = j; else break;
  }
  let kf = k;
  if (k > 0 && k < spec.length - 1) { const [y0, y1, y2] = [spec[k - 1], spec[k], spec[k + 1]], den = y0 - 2 * y1 + y2; if (den) kf = k + (0.5 * (y0 - y2)) / den; }
  const p = n / kf, strong = emax * 0.15, start = e.indexOf(emax), lines = new Set([start + 1]);
  for (const step of [1, -1]) {
    let x = start + 1;
    for (;;) {
      const want = x + step * p, lo = Math.round(want - p / 4), hi = Math.round(want + p / 4);
      if (hi < 1 || lo > n - 1) break;
      let best = -1;
      for (let i = Math.max(0, lo - 1); i < Math.min(e.length, hi); i++) if (best < 0 || e[i] > e[best]) best = i;
      x = best >= 0 && e[best] >= strong ? best + 1 : want;
      lines.add(Math.round(x));
    }
  }
  return { lines: [...lines].filter(l => l > 0 && l < n).sort((a, b) => a - b), p };
}
const squareIndex = (lines, n) => {  // for each position, how many lines come before it
  const out = new Int32Array(n);
  let i = 0;
  for (let x = 0; x < n; x++) { while (i < lines.length && lines[i] <= x) i++; out[x] = i; }
  return out;
};

function unfake(file, { out, bg = 'checker', floor = 0.03, preview = false } = {}) {
  const { W, H, rgba } = readPng(file), N = W * H, name = path.basename(file);
  const v = new Float32Array(N), neutral = new Uint8Array(N);
  let opaque = 0;
  for (let j = 0; j < N; j++) {
    const [r, g, b, a] = rgba.subarray(j * 4, j * 4 + 4);
    v[j] = (r + g + b) / 3;
    if (a > 250) { opaque++; neutral[j] = Math.max(r, g, b) - Math.min(r, g, b) <= 10 ? 1 : 0; }
  }
  if (opaque / N < 0.5) { console.log(`${name}: already has real transparency (${Math.round(100 - (100 * opaque) / N)}% see-through); skipped`); return null; }

  // 1. the background behind every pixel (grey, so one number each; or a flat colour)
  const B = new Float32Array(N * 3);
  let lo, hi;
  if (bg !== 'checker') {
    const rgb = [0, 2, 4].map(i => parseInt(bg.replace('#', '').slice(i, i + 2), 16));
    for (let j = 0; j < N; j++) B.set(rgb, j * 3);
    lo = hi = (rgb[0] + rgb[1] + rgb[2]) / 3;
    console.log(`${name}: flat background ${bg}`);
  } else {
    const levels = findLevels(v, neutral);
    if (levels.length === 1) {
      B.fill(levels[0]); lo = hi = levels[0];
      console.log(`${name}: flat grey background, level ${levels[0]}`);
    } else {
      const [dark, light] = levels, tol = Math.min(12, (light - dark) / 3), cls = new Int8Array(N).fill(-1);
      for (let j = 0; j < N; j++) if (neutral[j]) { if (Math.abs(v[j] - light) <= tol) cls[j] = 1; else if (Math.abs(v[j] - dark) <= tol) cls[j] = 0; }
      const gx = gridLines(cls, W, H, true), gy = gridLines(cls, W, H, false);
      if (!gx || !gy) throw new Error(`${file}: found two greys (${dark}, ${light}) but no checker grid; try --bg #rrggbb`);
      const ix = squareIndex(gx.lines, W), iy = squareIndex(gy.lines, H);
      let l0 = 0, k0 = 0;
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const j = y * W + x; if (cls[j] >= 0 && (ix[x] + iy[y]) % 2 === 0) { k0++; if (cls[j] === 1) l0++; } }
      const lightPar = l0 / k0 > 0.5 ? 0 : 1;
      let fitN = 0, fitK = 0;
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const j = y * W + x, g = (ix[x] + iy[y]) % 2 === lightPar ? light : dark;
        B[j * 3] = B[j * 3 + 1] = B[j * 3 + 2] = g;
        if (cls[j] >= 0) { fitK++; if ((g === light) === (cls[j] === 1)) fitN++; }
      }
      lo = dark; hi = light;
      const fit = fitN / fitK;
      console.log(`${name}: checker of ${dark} and ${light}, squares about ${((gx.p + gy.p) / 2).toFixed(1)}px ` +
        `(${gx.lines.length} x ${gy.lines.length} lines); the grid explains ${(100 * fit).toFixed(1)}% of the grey pixels`);
      if (fit < 0.9) console.log("  (under 90%: the painted checker is irregular; edges of the art may keep a faint grid)");
    }
  }

  const res = new Uint8Array(N * 4);
  let kept = 0;
  for (let j = 0; j < N; j++) {
    // 2. grey pixels between the background levels are background, watermark nudges and all
    if (neutral[j] && v[j] >= lo - 12 && v[j] <= hi + 12) continue;
    // 3. colour to alpha: the least opacity that explains the pixel with a real colour
    let a = 0;
    for (let c = 0; c < 3; c++) {
      const s = rgba[j * 4 + c], b = B[j * 3 + c], d = s - b;
      a = Math.max(a, d > 0 ? d / Math.max(255 - b, 1) : d < 0 ? -d / Math.max(b, 1) : 0);
    }
    // 4. leftover specks below the floor
    const a2 = Math.min(1, Math.max(0, (a - floor) / (1 - floor))) * (rgba[j * 4 + 3] / 255);
    if (a2 <= 0) continue;
    kept++;
    for (let c = 0; c < 3; c++) {  // the art's own colour: take the background's share back out
      const s = rgba[j * 4 + c], b = B[j * 3 + c];
      res[j * 4 + c] = Math.round(Math.min(255, Math.max(0, b + (s - b) / Math.max(a, 1e-6))));
    }
    res[j * 4 + 3] = Math.round(a2 * 255);
  }
  const stem = path.basename(file).replace(/\.[^.]+$/, '');
  const dest = path.join(out || path.dirname(file), stem + '_alpha.png');
  writePng(dest, W, H, res);
  console.log(`  -> ${dest}  (${((100 * kept) / N).toFixed(1)}% of pixels kept)`);
  if (preview) {  // the result on near-black, next to it on magenta
    const pv = new Uint8Array(W * 2 * H * 4);
    [[7, 12, 10], [255, 0, 255]].forEach((col, side) => {
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const j = (y * W + x) * 4, o = (y * W * 2 + side * W + x) * 4, a = res[j + 3] / 255;
        for (let c = 0; c < 3; c++) pv[o + c] = Math.round(res[j + c] * a + col[c] * (1 - a));
        pv[o + 3] = 255;
      }
    });
    writePng(dest.replace(/\.png$/, '_preview.png'), W * 2, H, pv);
  }
  return dest;
}

const args = process.argv.slice(2), opt = {};
const src = args.find((a, i) => !a.startsWith('--') && !['--out', '--bg', '--floor'].includes(args[i - 1]));
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--out') opt.out = args[++i];
  else if (args[i] === '--bg') opt.bg = args[++i];
  else if (args[i] === '--floor') opt.floor = parseFloat(args[++i]);
  else if (args[i] === '--preview') opt.preview = true;
}
if (!src) { console.log('usage: node unfake_alpha.mjs <image.png or folder> [--out DIR] [--bg checker|#rrggbb] [--floor 0.03] [--preview]'); process.exit(1); }
if (opt.out) mkdirSync(opt.out, { recursive: true });
const files = statSync(src).isDirectory()
  ? readdirSync(src).filter(f => f.toLowerCase().endsWith('.png') && !f.includes('_alpha')).sort().map(f => path.join(src, f))
  : [src];
for (const f of files) unfake(f, opt);
