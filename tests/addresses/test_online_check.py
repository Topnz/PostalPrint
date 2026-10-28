import pytest

from postalprint.addresses import online_check


def osm(road, number, postcode):
    address = {"road": road, "postcode": postcode}
    if number:
        address["house_number"] = number
    return {"address": address}


@pytest.fixture
def fake_fetch(monkeypatch):
    """Replaces Nominatim with one canned response per request and records what was asked."""
    calls = []

    def install(*responses):
        queue = list(responses)

        def fetch(params):
            calls.append(params)
            return queue.pop(0)

        monkeypatch.setattr(online_check, "_fetch", fetch)
        return calls

    return install


def test_found(fake_fetch):
    calls = fake_fetch([osm("Fiktivvej", "12", "8700")])
    result = online_check.check_address("Fiktivvej 12, 2. tv", "8700")
    assert result.status == online_check.FOUND
    assert not result.is_warning
    # Floor/door and name are never sent
    assert calls == [{"street": "12 Fiktivvej", "postalcode": "8700"}]


def test_found_with_letter(fake_fetch):
    fake_fetch([osm("Fiktivvej", "12B", "8700")])
    assert online_check.check_address("Fiktivvej 12 b", "8700").status == online_check.FOUND


def test_wrong_postcode(fake_fetch):
    fake_fetch([], [osm("Fiktivvej", "12", "8000")])
    result = online_check.check_address("Fiktivvej 12", "8700")
    assert result.status == online_check.WRONG_POSTCODE
    assert "8000" in result.message
    assert result.is_warning


def test_number_not_found(fake_fetch):
    fake_fetch([osm("Fiktivvej", None, "8700")])
    result = online_check.check_address("Fiktivvej 999", "8700")
    assert result.status == online_check.NUMBER_NOT_FOUND


def test_not_found(fake_fetch):
    fake_fetch([], [])
    assert online_check.check_address("Findesikkevej 1", "8700").status == online_check.NOT_FOUND


def test_network_error_is_unavailable_not_warning():
    # conftest.py disables the network, so _fetch raises OSError
    result = online_check.check_address("Fiktivvej 12", "8700")
    assert result.status == online_check.UNAVAILABLE
    assert not result.is_warning


def test_results_are_cached(fake_fetch):
    calls = fake_fetch([osm("Fiktivvej", "12", "8700")])
    online_check.check_address("Fiktivvej 12", "8700")
    online_check.check_address("fiktivvej 12", "8700")
    assert len(calls) == 1


@pytest.mark.parametrize("street, postcode", [("Fiktivvej", "8700"), ("Fiktivvej 12", "87"), ("Postboks 123", "8700")])
def test_skipped(street, postcode):
    assert online_check.check_address(street, postcode).status == online_check.SKIPPED
