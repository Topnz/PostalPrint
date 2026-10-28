"""The whole flow through Flask's test client. The printer and the network are replaced."""

import pytest

from postalprint.addresses import online_check
from postalprint.printing import printers
from postalprint.web.app import create_app

SENDER = {"name": "Firmanavn", "street": "Eksempelvej 1", "postcode": "8000", "city": "Aarhus C"}
RECIPIENT = {"name": "Test Testesen", "extra": "", "street": "Fiktivvej 12", "postcode": "8700", "city": "Horsens"}


@pytest.fixture
def printed(monkeypatch):
    calls = []
    monkeypatch.setattr(printers, "print_pdf", lambda path, config: calls.append(path))
    return calls


@pytest.fixture
def app(tmp_path, printed):
    app = create_app(tmp_path / "data")
    app.testing = True
    return app


@pytest.fixture
def client(app):
    client = app.test_client()
    response = client.put("/api/config", json={"sender": SENDER, "print": {"mode": "file", "rotation": 90},
                                              "address_check": {"online": False}})
    assert response.status_code == 200
    return client


def print_label(client, **overrides):
    return client.post("/api/labels/print", json={"recipient": RECIPIENT | overrides, "force": False})


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Ny etiket" in response.get_data(as_text=True)


def test_postcodes_endpoint(client):
    assert client.get("/api/postcodes").get_json()["8700"] == "Horsens"


def test_print_confirm_flow(client, app, printed):
    response = print_label(client)
    assert response.status_code == 200
    data = response.get_json()
    assert data["print_error"] is None
    assert len(printed) == 1
    # The PDF is saved in the history folder before the label is confirmed
    assert printed[0].exists()
    assert "historik" in str(printed[0])

    storage = app.config["STORAGE"]
    assert storage.search_history() == []
    assert client.post(f"/api/labels/{data['id']}/confirm").status_code == 200
    entries = storage.search_history()
    assert len(entries) == 1
    assert entries[0]["recipient"]["name"] == "Test Testesen"
    assert entries[0]["sender"]["name"] == "Firmanavn"
    assert storage.pdf_path(entries[0]["pdf_file"]).exists()


def test_validation_errors_return_422(client, printed):
    response = print_label(client, street="Fiktivvej", postcode="99")
    assert response.status_code == 422
    errors = response.get_json()["errors"]
    assert set(errors) == {"street", "postcode"}
    assert printed == []


def test_warning_needs_force(client, printed):
    response = print_label(client, city="Horsenss")
    assert response.status_code == 409
    assert "city" in response.get_json()["warnings"]
    assert printed == []
    forced = client.post("/api/labels/print", json={"recipient": RECIPIENT | {"city": "Horsenss"}, "force": True})
    assert forced.status_code == 200
    assert len(printed) == 1


def test_duplicate_warning_after_confirm(client):
    first = print_label(client).get_json()
    client.post(f"/api/labels/{first['id']}/confirm")
    response = print_label(client)
    assert response.status_code == 409
    assert "duplicate" in response.get_json()["warnings"]


def test_missing_sender_blocks(tmp_path, printed):
    client = create_app(tmp_path / "data").test_client()
    response = print_label(client)
    assert response.status_code == 422
    assert "sender" in response.get_json()["errors"]


def test_print_error_is_reported_and_pdf_kept(client, app, monkeypatch):
    def fail(path, config):
        raise printers.PrintError("Printeren svarede ikke.")

    monkeypatch.setattr(printers, "print_pdf", fail)
    data = print_label(client).get_json()
    assert data["print_error"] == "Printeren svarede ikke."
    assert client.get(data["pdf_url"]).status_code == 200


def test_reprint_and_cancel_pending(client, printed):
    data = print_label(client).get_json()
    assert client.post(f"/api/labels/{data['id']}/reprint").status_code == 200
    assert len(printed) == 2
    assert client.post(f"/api/labels/{data['id']}/cancel").status_code == 200
    assert client.post(f"/api/labels/{data['id']}/confirm").status_code == 404


def test_history_reprint_counts_and_regenerates_missing_pdf(client, app, printed):
    data = print_label(client).get_json()
    client.post(f"/api/labels/{data['id']}/confirm")
    storage = app.config["STORAGE"]
    storage.pdf_path(storage.get_entry(data["id"])["pdf_file"]).unlink()

    response = client.post(f"/api/history/{data['id']}/reprint")
    assert response.status_code == 200
    assert storage.get_entry(data["id"])["reprints"] == 1
    assert printed[-1].exists()


def test_history_search(client):
    data = print_label(client).get_json()
    client.post(f"/api/labels/{data['id']}/confirm")
    assert len(client.get("/api/history?q=test").get_json()["entries"]) == 1
    assert client.get("/api/history?q=bo").get_json()["entries"] == []


def test_pdf_endpoint(client):
    data = print_label(client).get_json()
    response = client.get(data["pdf_url"])
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF")
    assert client.get("/api/labels/findes-ikke/pdf").status_code == 404


def test_dialog_mode_prints_in_browser(client, printed):
    client.put("/api/config", json={"sender": SENDER, "print": {"mode": "dialog", "rotation": 90}})
    data = print_label(client).get_json()
    assert data["print_in_browser"] is True
    assert printed == []


def test_config_validation(client):
    response = client.put("/api/config", json={"sender": SENDER | {"postcode": "12"}, "print": {"rotation": 45}})
    assert response.status_code == 422
    assert set(response.get_json()["errors"]) == {"sender.postcode", "print.rotation"}


def test_preview(client):
    layout = client.post("/api/labels/preview", json={"recipient": RECIPIENT}).get_json()
    assert layout["recipient_size"] == 26
    assert any(t["text"] == "Test Testesen" for t in layout["texts"])


def test_online_warning_when_enabled(client, monkeypatch):
    client.put("/api/config", json={"sender": SENDER, "address_check": {"online": True}})
    monkeypatch.setattr(online_check, "check_address",
                        lambda street, postcode: online_check.AddressCheck(online_check.NOT_FOUND, "Ikke fundet."))
    response = print_label(client)
    assert response.status_code == 409
    assert response.get_json()["warnings"]["address"] == "Ikke fundet."


def test_online_unavailable_does_not_block(client, printed):
    client.put("/api/config", json={"sender": SENDER, "address_check": {"online": True}})
    # conftest.py disables the network → the check is skipped
    assert print_label(client).status_code == 200


def test_calibration(client, printed):
    response = client.post("/api/calibration/print")
    assert response.status_code == 200
    assert printed[-1].name == "kalibrering.pdf"
