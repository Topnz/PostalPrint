"""Shared test fixtures. All names and addresses are fictional."""

import pytest

from postalprint.addresses import online_check


@pytest.fixture
def sender():
    return {"name": "Firmanavn", "street": "Eksempelvej 1", "postcode": "8000", "city": "Aarhus C"}


@pytest.fixture
def recipient():
    return {"name": "Test Testesen", "extra": "", "street": "Fiktivvej 12, 2. tv", "postcode": "8700", "city": "Horsens"}


@pytest.fixture
def postcodes():
    return {"8000": "Aarhus C", "8700": "Horsens", "2100": "København Ø"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests must never call the real online service."""
    def fail(*args, **kwargs):
        raise OSError("network is disabled in tests")

    monkeypatch.setattr(online_check, "_fetch", fail)
    online_check.clear_cache()
