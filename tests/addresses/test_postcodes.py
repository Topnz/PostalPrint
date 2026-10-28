from postalprint.addresses import postcodes


def test_known_postcode():
    assert postcodes.lookup("8700") == "Horsens"
    assert postcodes.lookup("2100") == "København Ø"


def test_unknown_postcode():
    assert postcodes.lookup("0000") is None


def test_whitespace_is_ignored():
    assert postcodes.lookup(" 8000 ") == "Aarhus C"


def test_full_list_is_loaded():
    data = postcodes.load()
    assert len(data) > 1000
    assert all(len(code) == 4 and code.isdigit() for code in data)
