# Makefile for building and publishing the pdfmd executables.
#
# Requires: GNU Make, Python with PyInstaller installed (pip install pyinstaller).
# Recipes run under PowerShell.
#
#   make build     Build pdfmd.exe + pdfmd-gui.exe into dist/
#   make publish   Build (only if sources changed) and copy pdfmd.exe to MyCliTools
#   make clean     Remove build/ and dist/ artifacts

SHELL       := powershell.exe
.SHELLFLAGS := -NoProfile -Command

PYTHON   := python
SPEC     := packaging/pdfmd.spec
DIST     := dist
WORK     := build/pyinstaller
TOOLS    := D:/projects/MyCliTools
EXE      := pdfmd.exe
EXE_PATH := $(DIST)/$(EXE)

# Rebuild the exe when the spec, launchers, or any package source changes.
SOURCES := $(SPEC) \
           packaging/pdfmd_cli_launcher.py \
           packaging/pdfmd_gui_launcher.py \
           $(wildcard pdfmd/*.py)

.DEFAULT_GOAL := help
.PHONY: help build publish clean

help:
	@echo "pdfmd build targets:"
	@echo "  make build     - build pdfmd.exe + pdfmd-gui.exe into dist/"
	@echo "  make publish   - copy pdfmd.exe to $(TOOLS) (builds first if stale)"
	@echo "  make clean     - remove build/ and dist/"

build: $(EXE_PATH)

# The spec builds both exes; the CLI exe stands in as the build's output marker.
$(EXE_PATH): $(SOURCES)
	$(PYTHON) -m PyInstaller $(SPEC) --noconfirm --distpath $(DIST) --workpath $(WORK)

publish: $(EXE_PATH)
	@if (-not (Test-Path '$(TOOLS)')) { New-Item -ItemType Directory -Path '$(TOOLS)' | Out-Null }
	@Copy-Item -Force '$(EXE_PATH)' '$(TOOLS)/$(EXE)'
	@echo "Published $(EXE) to $(TOOLS)/$(EXE)"

clean:
	@if (Test-Path '$(DIST)') { Remove-Item -Recurse -Force '$(DIST)' }
	@if (Test-Path '$(WORK)') { Remove-Item -Recurse -Force '$(WORK)' }
	@echo "Cleaned build/ and dist/."
