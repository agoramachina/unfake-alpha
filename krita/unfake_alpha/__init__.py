# Unfake Alpha for Krita: registers the Tools > Scripts menu item. See unfake_alpha.py.
from krita import Krita

from .unfake_alpha import UnfakeAlphaExtension

Krita.instance().addExtension(UnfakeAlphaExtension(Krita.instance()))
