# PyInstaller spec for pdfmd — builds two one-file executables:
#   pdfmd-gui.exe   (windowed Tkinter app)
#   pdfmd.exe       (console CLI)
#
# Build from anywhere:
#   python -m PyInstaller packaging/pdfmd.spec --noconfirm
#
# Output lands in dist/. The Tesseract / OCRmyPDF *binaries* are NOT bundled
# (they are invoked via subprocess and must be installed separately on PATH).
# The ocrmypdf Python package is intentionally excluded for the same reason.
#
# One-file vs one-dir: this spec is one-file — Analysis binaries/datas are
# passed straight into each EXE() with no COLLECT() step.

import os
from PyInstaller.utils.hooks import collect_submodules

here = os.path.abspath(SPECPATH)          # packaging/
repo_root = os.path.dirname(here)         # repo root — needed so `import pdfmd` resolves

# PyMuPDF ships as the top-level module `fitz`; make sure it is fully collected.
hiddenimports = collect_submodules("fitz")

excludes = [
    "ocrmypdf",   # invoked as an external binary, not imported
    "pytest",
    "black",
    "mypy",
    "flake8",
]

gui_a = Analysis(
    [os.path.join(here, "pdfmd_gui_launcher.py")],
    pathex=[repo_root],
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
gui_pyz = PYZ(gui_a.pure)
gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    gui_a.binaries,
    gui_a.datas,
    [],
    name="pdfmd-gui",
    console=False,      # windowed — no console window
    upx=False,
)

cli_a = Analysis(
    [os.path.join(here, "pdfmd_cli_launcher.py")],
    pathex=[repo_root],
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
cli_pyz = PYZ(cli_a.pure)
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    cli_a.binaries,
    cli_a.datas,
    [],
    name="pdfmd",
    console=True,       # console CLI
    upx=False,
)
