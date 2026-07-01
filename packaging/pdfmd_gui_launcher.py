"""PyInstaller entry point for the pdfmd GUI.

Kept separate from the package so PyInstaller has a plain top-level script to
analyze. Imports the package normally, so `from pdfmd.* import ...` resolves.
"""
from pdfmd.app_gui import PdfMdApp


def main() -> None:
    app = PdfMdApp()
    app.mainloop()


if __name__ == "__main__":
    main()
