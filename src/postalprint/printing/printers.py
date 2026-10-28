"""Sends PDFs to the printer.

Modes (chosen in Settings):
- file:    open the PDF in the default PDF viewer (for development without a printer)
- dialog:  the browser shows its print dialog (handled in app.js)
- sumatra: print directly and silently via SumatraPDF (production)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

MODES = ("file", "dialog", "sumatra")
TIMEOUT_SECONDS = 30
SUMATRA_DOWNLOAD_URL = "https://www.sumatrapdfreader.org/download-free-pdf-viewer"

# Prevents a console window from flashing up on every print
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PrintError(Exception):
    """Printing failed. The message is shown directly in the UI and is therefore in Danish."""


def sumatra_candidates() -> list[Path]:
    """Places where SumatraPDF is typically installed on Windows."""
    candidates = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "SumatraPDF" / "SumatraPDF.exe")
    return candidates


def find_sumatra(configured: str = "") -> str | None:
    """Returns the path from Settings if it exists, otherwise searches the usual locations.

    Returns:
        The path to SumatraPDF.exe, or None if it is not installed.
    """
    if configured and Path(configured).is_file():
        return configured
    for candidate in sumatra_candidates():
        if candidate.is_file():
            return str(candidate)
    return shutil.which("SumatraPDF")


def list_printers() -> list[str]:
    """Returns the names of the printers Windows knows about, sorted, or [] if unavailable."""
    if sys.platform != "win32":
        return []
    # Force UTF-8 output so printer names with æøå survive
    command = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Printer | Select-Object -ExpandProperty Name"
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, timeout=20, check=True, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    names = completed.stdout.decode("utf-8", errors="replace").splitlines()
    return sorted({name.strip() for name in names if name.strip()}, key=str.casefold)


def open_file(path: Path) -> None:
    """Opens a file or folder with its default Windows program (e.g. Explorer for folders)."""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 – the path comes from the program itself
    else:
        webbrowser.open(Path(path).resolve().as_uri())


def print_pdf(pdf_path: Path, print_config: dict) -> None:
    """Prints the PDF according to the configured mode.

    Args:
        pdf_path: The PDF to print.
        print_config: The "print" section of the config.

    Raises:
        PrintError: With a user-facing explanation if printing failed.
    """
    mode = print_config.get("mode", "file")
    if mode == "file":
        try:
            open_file(pdf_path)
        except OSError as exc:
            raise PrintError(f"PDF'en kunne ikke åbnes: {exc}") from exc
    elif mode == "sumatra":
        _print_with_sumatra(Path(pdf_path), print_config)
    elif mode == "dialog":
        raise PrintError("Tilstanden 'dialog' printes fra browseren, ikke fra serveren.")
    else:
        raise PrintError(f"Ukendt print-tilstand: {mode}")


def _print_with_sumatra(pdf_path: Path, print_config: dict) -> None:
    """Prints silently with SumatraPDF, without scaling, and translates failures to PrintError."""
    exe = find_sumatra(print_config.get("sumatra_path", ""))
    if not exe:
        raise PrintError(
            "SumatraPDF blev ikke fundet. Installér det gratis fra "
            f"{SUMATRA_DOWNLOAD_URL} eller angiv stien under Indstillinger."
        )
    printer = print_config.get("printer_name", "").strip()
    target = ["-print-to", printer] if printer else ["-print-to-default"]
    # An argument list (not a shell string), so names with spaces and special characters are safe
    command = [exe, *target, "-print-settings", "noscale", "-silent", str(pdf_path)]
    try:
        subprocess.run(command, check=True, timeout=TIMEOUT_SECONDS, capture_output=True, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise PrintError(f"Printeren svarede ikke inden for {TIMEOUT_SECONDS} sekunder. Er den tændt?") from exc
    except subprocess.CalledProcessError as exc:
        # Only ask Windows for the printer list on failure, since it takes about a second
        if printer and printer not in list_printers():
            raise PrintError(f"Printeren «{printer}» findes ikke på denne PC. Vælg den rigtige under Indstillinger.") from exc
        name = f"«{printer}»" if printer else "standardprinteren"
        raise PrintError(f"Kunne ikke printe på {name} (fejlkode {exc.returncode}). Tjek at den er tændt og har papir.") from exc
    except OSError as exc:
        raise PrintError(f"SumatraPDF kunne ikke startes: {exc}") from exc
