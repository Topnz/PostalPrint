import subprocess

import pytest

from postalprint.printing import printers


@pytest.fixture
def sumatra(tmp_path):
    exe = tmp_path / "SumatraPDF.exe"
    exe.write_bytes(b"")
    return str(exe)


@pytest.fixture
def fake_run(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(printers.subprocess, "run", run)
    return calls


def test_sumatra_command_is_argument_list(sumatra, fake_run, tmp_path):
    pdf = tmp_path / "etiket.pdf"
    printers.print_pdf(pdf, {"mode": "sumatra", "printer_name": "Label Printer", "sumatra_path": sumatra})
    assert fake_run == [[sumatra, "-print-to", "Label Printer", "-print-settings", "noscale", "-silent", str(pdf)]]


def test_sumatra_without_printer_uses_default(sumatra, fake_run, tmp_path):
    printers.print_pdf(tmp_path / "x.pdf", {"mode": "sumatra", "printer_name": "", "sumatra_path": sumatra})
    assert fake_run[0][1] == "-print-to-default"


def test_sumatra_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(printers, "find_sumatra", lambda configured="": None)
    with pytest.raises(printers.PrintError, match="SumatraPDF blev ikke fundet"):
        printers.print_pdf(tmp_path / "x.pdf", {"mode": "sumatra", "printer_name": "", "sumatra_path": ""})


def test_unknown_printer_gives_clear_message(sumatra, monkeypatch, tmp_path):
    def run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(printers.subprocess, "run", run)
    monkeypatch.setattr(printers, "list_printers", lambda: ["Anden Printer"])
    with pytest.raises(printers.PrintError, match="findes ikke"):
        printers.print_pdf(tmp_path / "x.pdf", {"mode": "sumatra", "printer_name": "Label", "sumatra_path": sumatra})


def test_timeout_gives_clear_message(sumatra, monkeypatch, tmp_path):
    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(printers.subprocess, "run", run)
    with pytest.raises(printers.PrintError, match="svarede ikke"):
        printers.print_pdf(tmp_path / "x.pdf", {"mode": "sumatra", "printer_name": "Label", "sumatra_path": sumatra})


def test_file_mode_opens_pdf(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(printers, "open_file", opened.append)
    printers.print_pdf(tmp_path / "x.pdf", {"mode": "file"})
    assert opened == [tmp_path / "x.pdf"]


def test_unknown_mode(tmp_path):
    with pytest.raises(printers.PrintError):
        printers.print_pdf(tmp_path / "x.pdf", {"mode": "fax"})


def test_find_sumatra_prefers_configured_path(sumatra):
    assert printers.find_sumatra(sumatra) == sumatra


def test_find_sumatra_ignores_missing_configured_path(monkeypatch, tmp_path):
    monkeypatch.setattr(printers, "sumatra_candidates", lambda: [])
    monkeypatch.setattr(printers.shutil, "which", lambda name: None)
    assert printers.find_sumatra(str(tmp_path / "findes-ikke.exe")) is None
