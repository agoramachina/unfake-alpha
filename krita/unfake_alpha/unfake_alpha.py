"""Unfake Alpha for Krita: turns a painted-on "transparency" checkerboard (or a flat painted background) on the active
layer into real transparency, on a new layer above it.

Tools > Scripts > Unfake Alpha... The maths is unfake_core.py (plain Python: Krita's Python has no numpy); the how and
why is in the README (https://github.com/agoramachina/unfake-alpha). Nothing is overwritten: the result goes on a new layer, and the original
is only hidden, so deleting the new layer undoes it.
"""
from krita import Extension, Krita

try:  # Krita 6 (Qt6); Krita 5 had PyQt5
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                                 QFormLayout, QLabel, QLineEdit, QMessageBox, QProgressDialog)
except ImportError:
    from PyQt5.QtCore import QByteArray, Qt
    from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                                 QFormLayout, QLabel, QLineEdit, QMessageBox, QProgressDialog)

from . import unfake_core

SB = getattr(QDialogButtonBox, 'StandardButton', QDialogButtonBox)  # Qt6 scoped enums, Qt5 flat ones
WM = getattr(Qt, 'WindowModality', Qt)
GROUP = 'unfake_alpha'
TITLE = 'Unfake Alpha'


def run_dialog(d):
    return (d.exec() if hasattr(d, 'exec') else d.exec_())


class Options(QDialog):
    """Background (find the checker, or a flat colour), the floor, and whether to hide the original."""

    def __init__(self, parent, layer_name):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        app = Krita.instance()
        get = lambda k, dflt: app.readSetting(GROUP, k, dflt)  # noqa: E731
        f = QFormLayout(self)
        f.addRow(QLabel(f'Layer: <b>{layer_name}</b><br>The result goes on a new layer above it.'))
        self.mode = QComboBox()
        self.mode.addItems(['Find the checkerboard', 'A flat colour'])
        self.mode.setCurrentIndex(1 if get('mode', 'checker') == 'flat' else 0)
        f.addRow('Background:', self.mode)
        self.colour = QLineEdit(get('colour', '#000000'))
        self.colour.setToolTip('The painted background colour, as #rrggbb (e.g. #000000 for a black background)')
        f.addRow('Flat colour:', self.colour)
        self.floor = QDoubleSpinBox()
        self.floor.setRange(0.0, 0.5)
        self.floor.setSingleStep(0.01)
        self.floor.setDecimals(2)
        self.floor.setValue(float(get('floor', '0.03')))
        self.floor.setToolTip('Opacity under this becomes fully transparent (clears leftover specks). 0.03 = 3%')
        f.addRow('Floor:', self.floor)
        self.hide = QCheckBox('Hide the original layer')
        self.hide.setChecked(get('hide', '1') == '1')
        f.addRow(self.hide)
        bb = QDialogButtonBox(SB.Ok | SB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.mode.currentIndexChanged.connect(lambda i: self.colour.setEnabled(i == 1))
        self.colour.setEnabled(self.mode.currentIndex() == 1)

    def values(self):
        bg = None
        if self.mode.currentIndex() == 1:
            h = self.colour.text().strip().lstrip('#')
            if len(h) != 6:
                raise ValueError('the flat colour should look like #000000')
            bg = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        app = Krita.instance()
        app.writeSetting(GROUP, 'mode', 'flat' if bg else 'checker')
        app.writeSetting(GROUP, 'colour', self.colour.text().strip())
        app.writeSetting(GROUP, 'floor', str(self.floor.value()))
        app.writeSetting(GROUP, 'hide', '1' if self.hide.isChecked() else '0')
        return bg, self.floor.value(), self.hide.isChecked()


class UnfakeAlphaExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        pass

    def createActions(self, window):
        act = window.createAction('unfake_alpha', 'Unfake Alpha (painted checker to transparency)...',
                                  'tools/scripts')
        act.triggered.connect(self.run)

    def run(self):
        app = Krita.instance()
        win = app.activeWindow().qwindow() if app.activeWindow() else None
        say = lambda text: QMessageBox.information(win, TITLE, text)  # noqa: E731
        doc = app.activeDocument()
        if not doc:
            return say('Open an image first.')
        node = doc.activeNode()
        if node is None or node.type() != 'paintlayer':
            return say('Select the paint layer with the image on it.')
        if node.colorModel() != 'RGBA' or node.colorDepth() != 'U8':
            return say('This works on 8-bit RGBA layers. Image > Convert Image Color Space... to RGB/Alpha, '
                       '8-bit integer, then try again.')
        dlg = Options(win, node.name())
        if not run_dialog(dlg):
            return
        try:
            bg, floor, hide = dlg.values()
        except ValueError as e:
            return say(str(e))

        W, H = doc.width(), doc.height()
        raw = node.pixelData(0, 0, W, H)
        data = raw.data() if hasattr(raw, 'data') else bytes(raw)
        b, g, r, a = data[0::4], data[1::4], data[2::4], data[3::4]  # Krita keeps 8-bit RGBA as B, G, R, A

        prog = QProgressDialog('Unfaking...', 'Cancel', 0, 100, win)
        prog.setWindowTitle(TITLE)
        prog.setWindowModality(WM.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()

        def tick(f):
            prog.setValue(int(f * 100))
            QApplication.processEvents()
            return prog.wasCanceled()

        try:
            res, report = unfake_core.unfake(r, g, b, a, W, H, bg=bg, floor=floor, tick=tick)
        except unfake_core.Cancelled:
            return
        except ValueError as e:
            return say(str(e))
        finally:
            prog.close()
        if res is None:
            return say(report[0].upper() + report[1:] + '.')

        R, G, B, A = res
        out = bytearray(W * H * 4)
        out[0::4], out[1::4], out[2::4], out[3::4] = B, G, R, A
        new = doc.createNode(node.name() + ' (unfaked)', 'paintlayer')
        node.parentNode().addChildNode(new, node)  # just above the original
        new.setPixelData(QByteArray(bytes(out)), 0, 0, W, H)
        if hide:
            node.setVisible(False)
        doc.setActiveNode(new)
        doc.refreshProjection()
        say('Done: ' + report + '.\n\nTo undo, delete the new layer' + (' and show the original again.' if hide else '.'))
