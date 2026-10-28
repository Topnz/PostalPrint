"""Builds the standalone Windows program that is published on GitHub Releases.

Output in dist/:
    PostalPrint.exe            the whole program in one file (Python included)
    PostalPrint-windows.zip    the .exe + a short Danish guide (VEJLEDNING.txt)

GitHub Actions runs this script when a version tag (v*) is pushed, see
.github/workflows/release.yml. To build locally:
    .venv\\Scripts\\pip install -e .[dev]
    .venv\\Scripts\\python scripts\\build_exe.py
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
EXE_NAME = "PostalPrint"

PACKAGE = ROOT / "src" / "postalprint"

# Files the program reads at runtime, bundled inside the .exe at the same place in the package
BUNDLED_DATA = (
    PACKAGE / "addresses" / "postnumre.json",
    PACKAGE / "web" / "templates",
    PACKAGE / "web" / "static",
)

GUIDE = """PostalPrint
===========

Sådan kommer du i gang (Windows 10/11):

1. Pak zip-filen ud i en fast mappe, fx Dokumenter\\PostalPrint.
   Kør ikke programmet direkte inde fra zip-filen.

2. Dobbeltklik på PostalPrint.exe.
   Windows siger måske "Windows beskyttede din pc", fordi programmet ikke er signeret.
   Klik "Flere oplysninger" og derefter "Kør alligevel".

3. Der åbner et sort vindue. Det er selve programmet, så lad det være åbent.
   Efter et par sekunder åbner programmet i sit eget vindue.

4. Første gang skal du udfylde afsenderen under Indstillinger.

5. Vælg under "Sådan printes der":
   - "Åbn PDF'en", hvis du ikke har en labelprinter. Etiketten åbnes så som PDF.
   - "Direkte til labelprinteren", hvis du har en 100 × 150 mm labelprinter og SumatraPDF
     (gratis: https://www.sumatrapdfreader.org). Print en kalibreringsetiket for at tjekke målene.

6. Skriv navn, Tab, adresse, Tab, postnummer og tryk Enter.
   Historik (Ctrl+H): søg i tidligere etiketter og print igen.

7. Luk det sorte vindue for at stoppe programmet.

Alt gemmes i mappen "data" ved siden af PostalPrint.exe og forlader aldrig computeren
(bortset fra det valgfri adressetjek, der kun sender vej, husnummer og postnummer).
Tag backup af mappen "data", hvis du vil beholde historikken.
"""


def build_exe() -> Path:
    """Runs PyInstaller and returns the path to the finished .exe."""
    separator = ";" if sys.platform == "win32" else ":"
    command = [
        sys.executable, "-m", "PyInstaller", str(PACKAGE / "__main__.py"), "--paths", str(ROOT / "src"),
        "--onefile", "--name", EXE_NAME, "--clean", "--noconfirm",
        "--distpath", str(DIST), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
    ]
    for source in BUNDLED_DATA:
        # A file lands in its folder, a folder keeps its own name
        target = source.parent if source.is_file() else source
        command += ["--add-data", f"{source}{separator}{target.relative_to(ROOT / 'src').as_posix()}"]
    subprocess.run(command, check=True, cwd=ROOT)
    return DIST / f"{EXE_NAME}.exe"


def zip_package(exe: Path) -> Path:
    """Zips the .exe together with the Danish guide."""
    target = DIST / f"{EXE_NAME}-windows.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe, f"PostalPrint/{exe.name}")
        # ASCII file name: older unzip tools garble æøå in names inside zip files
        archive.writestr("PostalPrint/VEJLEDNING.txt", GUIDE.replace("\n", "\r\n").encode("utf-8-sig"))
    return target


def main() -> int:
    exe = build_exe()
    for path in (exe, zip_package(exe)):
        print(f"{path.relative_to(ROOT)}  ({path.stat().st_size / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
