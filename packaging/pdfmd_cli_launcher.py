"""PyInstaller entry point for the pdfmd CLI (console build).

Force UTF-8 on stdout/stderr so the help text and log messages (which contain
em-dashes and other non-cp1252 characters) print correctly in a frozen exe on
Windows, where the default console encoding is cp1252.
"""
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

from pdfmd.cli import main

if __name__ == "__main__":
    sys.exit(main())
