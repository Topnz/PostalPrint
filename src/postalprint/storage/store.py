"""Storage of config, history, label PDFs and backups. No Flask dependency.

Folder layout (everything lives under data/, which is in .gitignore):
    data/config.json
    data/historik/2026/2026-10.json     history for the month
    data/historik/2026/2026-10/*.pdf    one PDF per printed label
    data/backups/2026-10_2026-10-28T140312.json
    data/tmp/                           calibration PDFs
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG = {
    # Empty by default so no real address is ever stored in the code. Filled in via Settings.
    "sender": {"name": "", "street": "", "postcode": "", "city": ""},
    "print": {
        "mode": "file",
        "printer_name": "",
        "sumatra_path": "",  # empty = locate SumatraPDF automatically
        "rotation": 90,
    },
    "address_check": {"online": True},
}

HISTORY_VERSION = 1
FILENAME_NAME_MAX = 40
TMP_MAX_AGE_SECONDS = 24 * 60 * 60
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Writes to <file>.tmp and then atomically replaces the file, so it is never half-written.

    ``os.replace`` is atomic when source and target are on the same drive.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: object) -> None:
    """Writes human-readable UTF-8 JSON (æøå kept as-is) atomically."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_bytes(path, text.encode("utf-8"))


def safe_filename_part(text: str) -> str:
    """Makes ``text`` safe as part of a Windows file name.

    Removes characters Windows forbids, trims trailing dots and spaces and
    truncates to 40 characters. Danish letters are kept. Falls back to "ukendt".
    """
    cleaned = INVALID_FILENAME_CHARS.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned[:FILENAME_NAME_MAX].rstrip(" .")
    return cleaned or "ukendt"


def _deep_merge(defaults: dict, loaded: dict) -> dict:
    """Returns the defaults overridden by the saved values.

    New keys added in later versions therefore appear automatically in old config files.
    """
    result = copy.deepcopy(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Storage:
    """All file access for one data folder. Thread-safe, since Flask serves requests in threads."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.config_path = self.data_dir / "config.json"
        self.history_dir = self.data_dir / "historik"
        self.backups_dir = self.data_dir / "backups"
        self.tmp_dir = self.data_dir / "tmp"
        self._lock = threading.RLock()

    # --- Config ---------------------------------------------------------

    def load_config(self) -> dict:
        """Returns the config, creating it with default values on first run."""
        with self._lock:
            if not self.config_path.exists():
                atomic_write_json(self.config_path, DEFAULT_CONFIG)
                return copy.deepcopy(DEFAULT_CONFIG)
            loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
            return _deep_merge(DEFAULT_CONFIG, loaded)

    def save_config(self, config: dict) -> dict:
        """Saves the config and returns it merged with the defaults."""
        with self._lock:
            merged = _deep_merge(DEFAULT_CONFIG, config)
            atomic_write_json(self.config_path, merged)
            return merged

    # --- Label PDFs -----------------------------------------------------

    def month_dir(self, when: datetime) -> Path:
        """The folder holding the PDFs for the month of ``when``, e.g. historik/2026/2026-10."""
        return self.history_dir / f"{when:%Y}" / f"{when:%Y-%m}"

    def save_label_pdf(self, label_id: str, recipient: dict, pdf_bytes: bytes, printed_at: datetime) -> str:
        """Saves a label PDF in the month's folder.

        The file name starts with date and time so files sort chronologically in
        Explorer, e.g. "2026-10-28_1403_Test Testesen_8700_b3f1c2e0.pdf".

        Returns:
            The path relative to the history folder, using forward slashes.
        """
        name = safe_filename_part(recipient.get("name", ""))
        postcode = safe_filename_part(recipient.get("postcode", ""))
        filename = f"{printed_at:%Y-%m-%d_%H%M}_{name}_{postcode}_{label_id[:8]}.pdf"
        path = self.month_dir(printed_at) / filename
        atomic_write_bytes(path, pdf_bytes)
        return path.relative_to(self.history_dir).as_posix()

    def pdf_path(self, relative: str) -> Path:
        """Resolves a saved PDF's relative path.

        Raises:
            ValueError: If the path points outside the history folder (e.g. "../config.json").
        """
        base = self.history_dir.resolve()
        path = (base / relative).resolve()
        if base not in path.parents:
            raise ValueError("Invalid PDF path")
        return path

    # --- History --------------------------------------------------------

    def _month_file(self, printed_at: str) -> Path:
        when = datetime.fromisoformat(printed_at)
        return self.history_dir / f"{when:%Y}" / f"{when:%Y-%m}.json"

    def _read_month(self, path: Path) -> dict:
        if not path.exists():
            return {"version": HISTORY_VERSION, "entries": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_month(self, path: Path, data: dict) -> None:
        atomic_write_json(path, data)
        self._backup(path)

    def _backup(self, month_file: Path) -> None:
        """Continuous backup: copies the month file after every change. Never deleted automatically."""
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        target = self.backups_dir / f"{month_file.stem}_{stamp}.json"
        counter = 2
        while target.exists():  # several writes within the same second
            target = self.backups_dir / f"{month_file.stem}_{stamp}-{counter}.json"
            counter += 1
        shutil.copy2(month_file, target)

    def _month_files(self) -> list[Path]:
        """All month files, newest first (the names sort chronologically)."""
        return sorted(self.history_dir.glob("*/*.json"), reverse=True)

    def append_history(self, entry: dict) -> None:
        """Adds a confirmed label to its month's history file."""
        with self._lock:
            path = self._month_file(entry["printed_at"])
            data = self._read_month(path)
            data["entries"].append(entry)
            self._write_month(path, data)

    def get_entry(self, entry_id: str) -> dict | None:
        """Finds a history entry by id, or returns None."""
        with self._lock:
            for path in self._month_files():
                for entry in self._read_month(path)["entries"]:
                    if entry["id"] == entry_id:
                        return entry
        return None

    def update_entry(self, entry_id: str, **changes) -> dict | None:
        """Updates fields on a history entry. Returns the updated entry, or None if not found."""
        with self._lock:
            for path in self._month_files():
                data = self._read_month(path)
                for entry in data["entries"]:
                    if entry["id"] == entry_id:
                        entry.update(changes)
                        self._write_month(path, data)
                        return entry
        return None

    def increment_reprints(self, entry_id: str) -> dict | None:
        """Counts one more reprint of a history entry."""
        with self._lock:
            entry = self.get_entry(entry_id)
            if entry is None:
                return None
            return self.update_entry(entry_id, reprints=entry.get("reprints", 0) + 1)

    def all_entries(self) -> list[dict]:
        """All history entries, newest first."""
        with self._lock:
            entries = [e for path in self._month_files() for e in self._read_month(path)["entries"]]
        return sorted(entries, key=lambda e: e["printed_at"], reverse=True)

    def search_history(self, query: str = "", limit: int = 500) -> list[dict]:
        """Searches name, extra line, street, postcode and city, newest first.

        Every word in ``query`` must match (case-insensitive), so "prøvesen vejle" narrows the result.
        """
        words = query.casefold().split()
        results = []
        for entry in self.all_entries():
            r = entry.get("recipient", {})
            haystack = " ".join(r.get(k, "") for k in ("name", "extra", "street", "postcode", "city")).casefold()
            if all(word in haystack for word in words):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def recent_entries(self, months: int = 2) -> list[dict]:
        """Entries from the newest month files. Two months always cover the 14-day duplicate check."""
        with self._lock:
            return [e for path in self._month_files()[:months] for e in self._read_month(path)["entries"]]

    # --- Temporary files ------------------------------------------------

    def tmp_file(self, name: str) -> Path:
        """Path to a file in data/tmp/, creating the folder if needed."""
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        return self.tmp_dir / name

    def cleanup_tmp(self, max_age_seconds: int = TMP_MAX_AGE_SECONDS) -> None:
        """Deletes temporary files older than ``max_age_seconds`` (run at startup)."""
        if not self.tmp_dir.exists():
            return
        cutoff = time.time() - max_age_seconds
        for path in self.tmp_dir.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
