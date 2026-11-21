"""build_zip: packs the Unfake Alpha plugin into unfake_alpha_krita_plugin.zip for Krita's
Tools > Scripts > Import Python Plugin from File.
    python krita/build_zip.py

The zip holds unfake_alpha.desktop and the unfake_alpha/ folder, AND an entry for the folder itself
("unfake_alpha/"). Krita's importer finds a plugin's module by that folder entry (plugin_importer.py,
get_source_module), and Python's zipfile only writes entries for files, so without it Krita says
"No plugins found in archive". (An early zip had exactly that bug.)
"""
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ['__init__.py', 'unfake_alpha.py', 'unfake_core.py', 'Manual.html']
OUT = os.path.join(HERE, 'unfake_alpha_krita_plugin.zip')

with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
    z.write(os.path.join(HERE, 'unfake_alpha.desktop'), 'unfake_alpha.desktop')
    z.writestr(zipfile.ZipInfo('unfake_alpha/'), '')  # the folder's own entry
    for f in FILES:
        z.write(os.path.join(HERE, 'unfake_alpha', f), 'unfake_alpha/' + f)
print(OUT)
for n in zipfile.ZipFile(OUT).namelist():
    print('  ' + n)
