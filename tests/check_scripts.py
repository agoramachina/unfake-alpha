"""check_scripts: runs all three versions of unfake-alpha on the example and checks they agree with each other and
with the result kept in examples/ (to within 1 per channel: rounding).
    python tests/check_scripts.py
Needs Pillow and numpy, and node for the .mjs (skipped with a note if node isn't there).
"""
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'examples', 'traces2.png')
REF = np.asarray(Image.open(os.path.join(ROOT, 'examples', 'traces2_alpha.png')).convert('RGBA')).astype(int)
fails = 0


def check(name, arr):
    global fails
    worst = int(np.abs(arr.astype(int) - REF).max())
    good = worst <= 1
    fails += not good
    print(f"{'ok  ' if good else 'FAIL'} {name}: largest difference from examples/traces2_alpha.png is {worst}")


with tempfile.TemporaryDirectory() as tmp:
    subprocess.run([sys.executable, os.path.join(ROOT, 'unfake_alpha.py'), SRC, '--out', tmp], check=True)
    check('unfake_alpha.py', np.asarray(Image.open(os.path.join(tmp, 'traces2_alpha.png'))))
    if shutil.which('node'):
        os.makedirs(os.path.join(tmp, 'js'))
        subprocess.run(['node', os.path.join(ROOT, 'unfake_alpha.mjs'), SRC, '--out', os.path.join(tmp, 'js')], check=True)
        check('unfake_alpha.mjs', np.asarray(Image.open(os.path.join(tmp, 'js', 'traces2_alpha.png'))))
    else:
        print('skip unfake_alpha.mjs: node not found')

sys.path.insert(0, os.path.join(ROOT, 'krita', 'unfake_alpha'))
import unfake_core  # noqa: E402  (the Krita plugin's plain-Python maths)
im = Image.open(SRC).convert('RGBA')
W, H = im.size
d = im.tobytes()
(r, g, b, a), report = unfake_core.unfake(d[0::4], d[1::4], d[2::4], d[3::4], W, H)
print('     unfake_core: ' + report)
check('krita/unfake_alpha/unfake_core.py', np.dstack([np.frombuffer(bytes(x), np.uint8).reshape(H, W) for x in (r, g, b, a)]))
sys.exit(1 if fails else 0)
