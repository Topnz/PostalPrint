from datetime import datetime, timedelta, timezone

import pytest

from postalprint.addresses import validation

NOW = datetime(2026, 10, 28, 14, 0, tzinfo=timezone(timedelta(hours=1)))


def run(recipient, sender, postcodes, **kwargs):
    return validation.validate(recipient, sender, postcodes, now=NOW, **kwargs)


def test_valid_recipient_has_no_errors(recipient, sender, postcodes):
    result = run(recipient, sender, postcodes)
    assert result.ok
    assert result.warnings == {}


def test_whitespace_is_normalized(recipient, sender, postcodes):
    recipient["name"] = "  Test    Testesen "
    recipient["postcode"] = " 87 00"
    result = run(recipient, sender, postcodes)
    assert result.recipient["name"] == "Test Testesen"
    assert result.recipient["postcode"] == "8700"


def test_case_is_not_changed(recipient, sender, postcodes):
    recipient["name"] = "test TESTESEN"
    assert run(recipient, sender, postcodes).recipient["name"] == "test TESTESEN"


@pytest.mark.parametrize("field", ["name", "street", "postcode", "city"])
def test_required_fields(recipient, sender, postcodes, field):
    recipient[field] = "   "
    assert field in run(recipient, sender, postcodes).errors


def test_extra_line_is_optional(recipient, sender, postcodes):
    recipient["extra"] = ""
    assert run(recipient, sender, postcodes).ok


def test_missing_sender_blocks_print(recipient, postcodes):
    empty_sender = {"name": "", "street": "", "postcode": "", "city": ""}
    assert "sender" in run(recipient, empty_sender, postcodes).errors


@pytest.mark.parametrize("street", [
    "Fiktivvej 12",
    "Fiktivvej 12B",
    "Fiktivvej 12 B",
    "Fiktivvej 12, 2. tv",
    "Fiktivvej 12B, st. th.",
    "Kong Fiktiv IX's Gade 3",
    "H.C. Testesens Boulevard 7",
    "10. Testmaj Vej 3",
    "Postboks 123",
])
def test_valid_streets(recipient, sender, postcodes, street):
    recipient["street"] = street
    assert "street" not in run(recipient, sender, postcodes).errors


@pytest.mark.parametrize("street, expected", [
    ("Fiktivvej", "husnummer"),
    ("12", "vejnavn"),
    ("12 Fiktivvej", "efter vejnavnet"),
    ("Fiktivvej 0", "0"),
    ("Fiktivvej 12, 8700 Horsens", "Postnummer"),
    ("Fiktivvej 1234", "Postnummer"),
])
def test_invalid_streets(recipient, sender, postcodes, street, expected):
    recipient["street"] = street
    errors = run(recipient, sender, postcodes).errors
    assert expected in errors["street"]


@pytest.mark.parametrize("postcode, expected", [
    ("870", "4 cifre"),
    ("87000", "4 cifre"),
    ("87a0", "4 cifre"),
    ("9999", "findes ikke"),
])
def test_invalid_postcodes(recipient, sender, postcodes, postcode, expected):
    recipient["postcode"] = postcode
    assert expected in run(recipient, sender, postcodes).errors["postcode"]


@pytest.mark.parametrize("raw", ["DK-8700", "dk8700", "8 700"])
def test_postcode_prefixes_are_removed(recipient, sender, postcodes, raw):
    recipient["postcode"] = raw
    result = run(recipient, sender, postcodes)
    assert result.recipient["postcode"] == "8700"
    assert "postcode" not in result.errors


def test_city_with_digits_is_error(recipient, sender, postcodes):
    recipient["city"] = "8700 Horsens"
    assert "tal" in run(recipient, sender, postcodes).errors["city"]


def test_city_mismatch_is_warning(recipient, sender, postcodes):
    recipient["city"] = "Horsenss"
    result = run(recipient, sender, postcodes)
    assert result.ok
    assert "Horsens" in result.warnings["city"]


def test_city_match_ignores_case(recipient, sender, postcodes):
    recipient["city"] = "HORSENS"
    assert "city" not in run(recipient, sender, postcodes).warnings


# Narrow characters ("il"), so the length limit is tested rather than the label width
@pytest.mark.parametrize("name, ok", [("A", False), ("Al", True), ("il" * 30, True), ("il" * 30 + "i", False), ("123", False)])
def test_name_length_and_letters(recipient, sender, postcodes, name, ok):
    recipient["name"] = name
    assert ("name" not in run(recipient, sender, postcodes).errors) == ok


def test_name_that_looks_like_address_is_warning(recipient, sender, postcodes):
    recipient["name"] = "Fiktivvej 12"
    result = run(recipient, sender, postcodes)
    assert result.ok
    assert "adresse" in result.warnings["name"]


@pytest.mark.parametrize("char", ["ł", "😀", "Ş"])
def test_unprintable_characters(recipient, sender, postcodes, char):
    recipient["name"] = f"Test {char}estesen"
    assert char in run(recipient, sender, postcodes).errors["name"]


def test_danish_and_accented_letters_are_fine(recipient, sender, postcodes):
    recipient["name"] = "Test Æblegrød Østersø-Müller Réné"
    assert run(recipient, sender, postcodes).ok


def test_text_too_wide_for_label(recipient, sender, postcodes):
    recipient["street"] = "Fiktivvej 12, " + "W" * 50
    assert "for lang" in run(recipient, sender, postcodes).errors["street"].lower()


def test_extra_repeating_name_is_warning(recipient, sender, postcodes):
    recipient["extra"] = "test testesen"
    assert "extra" in run(recipient, sender, postcodes).warnings


def entry(days_ago, name="Test Testesen", street="Fiktivvej 12, 2. tv"):
    return {"printed_at": (NOW - timedelta(days=days_ago)).isoformat(),
            "recipient": {"name": name, "street": street}}


def test_duplicate_within_14_days_is_warning(recipient, sender, postcodes):
    result = run(recipient, sender, postcodes, recent_entries=[entry(3)])
    assert "dublet" in result.warnings["duplicate"]


def test_duplicate_ignores_case(recipient, sender, postcodes):
    result = run(recipient, sender, postcodes, recent_entries=[entry(3, name="TEST TESTESEN")])
    assert "duplicate" in result.warnings


def test_old_print_is_not_duplicate(recipient, sender, postcodes):
    assert "duplicate" not in run(recipient, sender, postcodes, recent_entries=[entry(15)]).warnings


def test_other_address_is_not_duplicate(recipient, sender, postcodes):
    result = run(recipient, sender, postcodes, recent_entries=[entry(1, street="Opdigtet Allé 3")])
    assert "duplicate" not in result.warnings


def test_parse_street():
    parts = validation.parse_street("Fiktivvej 12b, 2. tv")
    assert (parts.road, parts.number, parts.letter, parts.rest) == ("Fiktivvej", "12", "b", ", 2. tv")
    assert parts.house_number == "12B"


def test_validate_sender(postcodes):
    sender, errors = validation.validate_sender(
        {"name": " Firmanavn ", "street": "Eksempelvej 1", "postcode": "8000", "city": "Aarhus C"}, postcodes)
    assert errors == {}
    assert sender["name"] == "Firmanavn"


def test_validate_sender_requires_all_fields(postcodes):
    _, errors = validation.validate_sender({"name": "Firmanavn"}, postcodes)
    assert set(errors) == {"street", "postcode", "city"}
