"""Where the program finds its own files and keeps the user's data."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

if getattr(sys, "frozen", False):
    # Built with PyInstaller: the code runs from a temporary folder that is deleted on exit,
    # so data is kept next to the .exe instead
    DATA_DIR = Path(sys.executable).resolve().parent / "data"
else:
    # Running from source: data/ in the project root (src/postalprint/ → project root)
    DATA_DIR = PACKAGE_DIR.parent.parent / "data"
