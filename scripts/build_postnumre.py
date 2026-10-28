"""Builds src/postalprint/addresses/postnumre.json from the GeoNames list of Danish postcodes.

Source: https://download.geonames.org/export/zip/DK.zip
License: Creative Commons Attribution 4.0 (GeoNames is credited in the README).

DAWA shut down on 1 October 2026 and Datafordeleren requires an API key,
so GeoNames is the simplest free source. Run the script again whenever
new postcodes are introduced:

    .venv\\Scripts\\python scripts\\build_postnumre.py
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

SOURCE_URL = "https://download.geonames.org/export/zip/DK.zip"
OUTPUT = Path(__file__).resolve().parent.parent / "src" / "postalprint" / "addresses" / "postnumre.json"


def download(url: str = SOURCE_URL) -> str:
    """Downloads the zip archive and returns the contents of DK.txt as text."""
    with urllib.request.urlopen(url, timeout=60) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    return archive.read("DK.txt").decode("utf-8")


def parse(text: str) -> dict[str, str]:
    """Converts GeoNames' tab-separated format to {postcode: city}, sorted by postcode.

    Columns: country code, postcode, place name, ... (see GeoNames' readme.txt).
    """
    postcodes: dict[str, str] = {}
    for line in text.splitlines():
        columns = line.split("\t")
        if len(columns) < 3 or columns[0] != "DK":
            continue
        code, city = columns[1].strip(), columns[2].strip()
        if len(code) == 4 and code.isdigit() and city:
            postcodes.setdefault(code, city)
    return dict(sorted(postcodes.items()))


def main() -> int:
    print(f"Downloading {SOURCE_URL} ...")
    postcodes = parse(download())
    # Guard against writing a broken file if the source format changes
    if len(postcodes) < 1000:
        print(f"Only {len(postcodes)} postcodes found – that looks wrong. The file was not changed.")
        return 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(postcodes, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"Wrote {len(postcodes)} postcodes to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
