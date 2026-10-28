import json
from datetime import datetime, timedelta, timezone

import pytest

from postalprint.storage.store import DEFAULT_CONFIG, Storage, safe_filename_part

TZ = timezone(timedelta(hours=1))


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "data")


def make_entry(entry_id, when, name="Test Testesen", city="Horsens"):
    return {
        "id": entry_id,
        "printed_at": when.isoformat(),
        "recipient": {"name": name, "extra": "", "street": "Fiktivvej 12", "postcode": "8700", "city": city},
        "sender": {"name": "Firmanavn", "street": "Eksempelvej 1", "postcode": "8000", "city": "Aarhus C"},
        "pdf_file": "",
        "reprints": 0,
    }


def test_config_is_created_with_empty_sender(storage):
    config = storage.load_config()
    assert config == DEFAULT_CONFIG
    assert config["sender"]["name"] == ""
    assert storage.config_path.exists()


def test_config_round_trip(storage):
    config = storage.load_config()
    config["sender"]["name"] = "Firmanavn"
    storage.save_config(config)
    assert storage.load_config()["sender"]["name"] == "Firmanavn"


def test_old_config_gets_new_defaults(storage):
    storage.config_path.parent.mkdir(parents=True)
    storage.config_path.write_text(json.dumps({"print": {"mode": "sumatra"}}), encoding="utf-8")
    config = storage.load_config()
    assert config["print"]["mode"] == "sumatra"
    assert config["print"]["rotation"] == 90
    assert config["address_check"]["online"] is True


def test_history_goes_in_month_file(storage):
    storage.append_history(make_entry("a1", datetime(2026, 10, 28, 14, 3, tzinfo=TZ)))
    storage.append_history(make_entry("b2", datetime(2026, 11, 2, 9, 0, tzinfo=TZ)))
    assert (storage.history_dir / "2026" / "2026-10.json").exists()
    data = json.loads((storage.history_dir / "2026" / "2026-11.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert [e["id"] for e in data["entries"]] == ["b2"]


def test_history_is_utf8_and_readable(storage):
    storage.append_history(make_entry("a1", datetime(2026, 10, 28, tzinfo=TZ), name="Test Æblø"))
    text = (storage.history_dir / "2026" / "2026-10.json").read_text(encoding="utf-8")
    assert "Test Æblø" in text  # ensure_ascii=False


def test_backup_after_every_write_and_never_deleted(storage):
    when = datetime(2026, 10, 28, tzinfo=TZ)
    for i in range(5):
        storage.append_history(make_entry(f"id{i}", when))
    storage.increment_reprints("id0")
    backups = list(storage.backups_dir.glob("2026-10_*.json"))
    assert len(backups) == 6
    newest = max(backups, key=lambda p: p.stat().st_mtime_ns)
    assert len(json.loads(newest.read_text(encoding="utf-8"))["entries"]) == 5


def test_no_tmp_files_left_behind(storage):
    storage.append_history(make_entry("a1", datetime(2026, 10, 28, tzinfo=TZ)))
    assert not list(storage.data_dir.rglob("*.tmp"))


def test_get_update_and_reprints(storage):
    storage.append_history(make_entry("a1", datetime(2026, 10, 28, tzinfo=TZ)))
    assert storage.get_entry("a1")["reprints"] == 0
    storage.increment_reprints("a1")
    storage.increment_reprints("a1")
    assert storage.get_entry("a1")["reprints"] == 2
    assert storage.get_entry("findes-ikke") is None
    assert storage.increment_reprints("findes-ikke") is None


def test_search_newest_first(storage):
    storage.append_history(make_entry("old", datetime(2026, 9, 1, tzinfo=TZ), name="Test Testesen"))
    storage.append_history(make_entry("new", datetime(2026, 10, 1, tzinfo=TZ), name="Fiktiv Prøvesen", city="Vejle"))
    storage.append_history(make_entry("newer", datetime(2026, 10, 5, tzinfo=TZ), name="Test Prøvesen"))
    assert [e["id"] for e in storage.search_history("")] == ["newer", "new", "old"]
    assert [e["id"] for e in storage.search_history("test")] == ["newer", "old"]
    assert [e["id"] for e in storage.search_history("prøvesen vejle")] == ["new"]
    assert storage.search_history("8700 fiktivvej")


def test_save_label_pdf(storage):
    when = datetime(2026, 10, 28, 14, 3, tzinfo=TZ)
    rel = storage.save_label_pdf("b3f1c2e0-1234", {"name": "Test Testesen", "postcode": "8700"}, b"%PDF-1.4", when)
    assert rel == "2026/2026-10/2026-10-28_1403_Test Testesen_8700_b3f1c2e0.pdf"
    assert storage.pdf_path(rel).read_bytes() == b"%PDF-1.4"


def test_pdf_path_rejects_traversal(storage):
    with pytest.raises(ValueError):
        storage.pdf_path("../config.json")


@pytest.mark.parametrize("raw, expected", [
    ("Test Testesen", "Test Testesen"),
    ("Test/Testesen?", "TestTestesen"),
    ('a<b>c:d"e|f*g\\h', "abcdefgh"),
    ("Test Æblø Åse", "Test Æblø Åse"),
    ("   ", "ukendt"),
    ("...", "ukendt"),
    ("Navn.", "Navn"),
    ("x" * 100, "x" * 40),
])
def test_safe_filename_part(raw, expected):
    assert safe_filename_part(raw) == expected


def test_recent_entries_reads_two_newest_months(storage):
    storage.append_history(make_entry("aug", datetime(2026, 8, 30, tzinfo=TZ)))
    storage.append_history(make_entry("sep", datetime(2026, 9, 30, tzinfo=TZ)))
    storage.append_history(make_entry("oct", datetime(2026, 10, 1, tzinfo=TZ)))
    assert {e["id"] for e in storage.recent_entries()} == {"sep", "oct"}


def test_cleanup_tmp(storage):
    old = storage.tmp_file("gammel.pdf")
    old.write_bytes(b"x")
    storage.cleanup_tmp(max_age_seconds=-1)
    assert not old.exists()
