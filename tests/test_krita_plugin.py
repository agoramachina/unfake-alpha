"""test_krita_plugin: runs the Unfake Alpha Krita plugin outside Krita.
Borrows Krita's own PyQt6 (read only; same Python version) and stands in for Krita's API with a
tiny fake document holding a real image as its layer. Checks the plugin's whole path: menu action, dialog, progress,
reading the layer, the new layer, hiding the original, and that the pixels match unfake_alpha.py's.
    python tests/test_krita_plugin.py [image.png reference_alpha.png]   (default: the example in examples/)
Needs Krita 6 installed (set KRITA_DIR if it isn't in the default place) and Pillow. Windows only as written:
it borrows Krita's Python bindings, which must match this Python's version.
"""
import os
import sys
import types

KRITA = os.environ.get('KRITA_DIR', 'C:/Program Files/Krita (x64)')
if not os.path.isdir(KRITA):
    sys.exit(f'Krita not found at {KRITA}: set KRITA_DIR to its install folder')
os.environ['QT_PLUGIN_PATH'] = KRITA + '/bin'  # Krita ships only the Windows platform plugin (no offscreen):
os.environ['QT_QPA_PLATFORM'] = 'windows'       # the progress box flashes up for a moment
os.add_dll_directory(KRITA + '/bin')
sys.path.insert(0, KRITA + '/lib/site-packages')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'krita'))

from PIL import Image  # noqa: E402  (the system Python's, for reading the test image)
from PyQt6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication([])
passed = failed = 0


def ok(cond, what):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(('ok   ' if cond else 'FAIL ') + what)


# ---- a stand-in for the parts of Krita's API the plugin uses
class Node:
    def __init__(self, name, W, H, bgra=None):
        self._name, self.W, self.H, self.visible, self.children, self.parent = name, W, H, True, [], None
        self.data = bytearray(bgra if bgra is not None else bytes(W * H * 4))

    def name(self): return self._name
    def type(self): return 'paintlayer'
    def colorModel(self): return 'RGBA'
    def colorDepth(self): return 'U8'
    def pixelData(self, x, y, w, h):
        from PyQt6.QtCore import QByteArray
        return QByteArray(bytes(self.data))
    def setPixelData(self, qba, x, y, w, h): self.data = bytearray(qba.data())
    def parentNode(self): return self.parent
    def addChildNode(self, child, above):
        child.parent = self
        self.children.insert(self.children.index(above) + 1 if above in self.children else len(self.children), child)
    def setVisible(self, v): self.visible = v


class Doc:
    def __init__(self, node):
        self.root = Node('root', node.W, node.H)
        self.root.addChildNode(node, None)
        self.active = node
        self.refreshed = False

    def width(self): return self.active.W
    def height(self): return self.active.H
    def activeNode(self): return self.active
    def setActiveNode(self, n): self.active = n
    def createNode(self, name, kind): return Node(name, self.active.W, self.active.H)
    def refreshProjection(self): self.refreshed = True


class Window:
    def __init__(self): self.actions = {}
    def qwindow(self): return None
    def createAction(self, id_, text, menu):
        from PyQt6.QtGui import QAction
        a = QAction(text)
        self.actions[id_] = (a, menu)
        return a


class KritaApp:
    _i = None
    def __init__(self): self.settings, self.exts, self.doc, self.win = {}, [], None, Window()
    @classmethod
    def instance(cls):
        cls._i = cls._i or KritaApp()
        return cls._i
    def readSetting(self, g, k, d): return self.settings.get((g, k), d)
    def writeSetting(self, g, k, v): self.settings[(g, k)] = v
    def addExtension(self, e): self.exts.append(e)
    def activeDocument(self): return self.doc
    def activeWindow(self): return self.win


class Extension:
    def __init__(self, parent): self.parent = parent


sys.modules['krita'] = types.SimpleNamespace(Krita=KritaApp, Extension=Extension)

# ---- load the plugin as Krita would, and run it on the image
import unfake_alpha as plugin_pkg  # noqa: E402  (the package: its __init__ registers the extension)
mod = sys.modules['unfake_alpha.unfake_alpha']
app = KritaApp.instance()
ok(len(app.exts) == 1, 'the plugin registers one extension')
ext = app.exts[0]
ext.setup()
ext.createActions(app.win)
ok('unfake_alpha' in app.win.actions and app.win.actions['unfake_alpha'][1] == 'tools/scripts',
   'it adds its menu item under Tools > Scripts')

messages = []
mod.QMessageBox = types.SimpleNamespace(information=lambda parent, title, text: messages.append(text))
mod.run_dialog = lambda d: True  # press OK in the dialog without a person

src, ref = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else (
    os.path.join(ROOT, 'examples', 'traces2.png'), os.path.join(ROOT, 'examples', 'traces2_alpha.png'))
im = Image.open(src).convert('RGBA')
W, H = im.size
rgba = im.tobytes()
bgra = bytearray(len(rgba))
bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = rgba[2::4], rgba[1::4], rgba[0::4], rgba[3::4]
layer = Node('traces2', W, H, bgra)
app.doc = Doc(layer)
app.win.actions['unfake_alpha'][0].trigger()

kids = app.doc.root.children
ok(len(kids) == 2 and kids[1].name() == 'traces2 (unfaked)', 'a new layer "traces2 (unfaked)" above the original')
ok(not layer.visible, 'the original is hidden')
ok(app.doc.active is kids[-1] and app.doc.refreshed, 'the new layer is selected and the canvas refreshed')
ok(messages and messages[-1].startswith('Done: checker of 82 and 138'), 'reports: ' + (messages[-1] if messages else '(nothing)'))
out = kids[-1].data
got = bytearray(len(out))
got[0::4], got[1::4], got[2::4], got[3::4] = out[2::4], out[1::4], out[0::4], out[3::4]
want = Image.open(ref).convert('RGBA').tobytes()
worst = max(abs(x - y) for x, y in zip(got, want))
ok(worst <= 1, f'pixels match unfake_alpha.py (largest difference {worst})')
ok(app.settings.get(('unfake_alpha', 'mode')) == 'checker', 'remembers the options for next time')

# a layer that's already transparent is left alone
clear = Node('clear', 8, 8)
app.doc = Doc(clear)
messages.clear()
app.win.actions['unfake_alpha'][0].trigger()
ok(len(app.doc.root.children) == 1 and messages and 'already has real transparency' in messages[-1].lower(),
   'an already-transparent layer: says so, adds nothing')

# the install zip, through Krita's own importer (its real code, into a scratch folder, not Krita's)
import builtins  # noqa: E402
import tempfile  # noqa: E402
builtins.i18n = lambda s: s  # Krita puts i18n into builtins
sys.path.insert(0, KRITA + '/share/krita/pykrita/plugin_importer')
import plugin_importer  # noqa: E402
with tempfile.TemporaryDirectory() as res:
    os.makedirs(os.path.join(res, 'pykrita'))
    zp = os.path.join(ROOT, 'krita', 'unfake_alpha_krita_plugin.zip')
    try:
        got = [p['ui_name'] for p in plugin_importer.PluginImporter(zp, res, lambda p: True).import_all()]
    except Exception as e:
        got = [f'error: {e}']
    ok(got == ['Unfake Alpha'], f"Krita's importer takes the zip: {got}")
    ok(all(os.path.exists(os.path.join(res, 'pykrita', p)) for p in
           ['unfake_alpha.desktop', 'unfake_alpha/__init__.py', 'unfake_alpha/unfake_core.py']),
       'and puts the plugin where Krita loads plugins from')
print(f'{passed}/{passed + failed} passed')
sys.exit(1 if failed else 0)
