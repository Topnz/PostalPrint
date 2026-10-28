from io import BytesIO

import pytest
from pypdf import PdfReader

from postalprint.labels import layout, pdf


def page_size(pdf_bytes):
    page = PdfReader(BytesIO(pdf_bytes)).pages[0]
    return float(page.mediabox.width), float(page.mediabox.height)


@pytest.mark.parametrize("rotation", [90, 270])
def test_page_is_portrait_100_by_150_mm(recipient, sender, rotation):
    width, height = page_size(pdf.render_label(recipient, sender, rotation))
    assert width == pytest.approx(283.46, abs=0.01)
    assert height == pytest.approx(425.20, abs=0.01)


def test_pdf_contains_recipient_text(recipient, sender):
    text = PdfReader(BytesIO(pdf.render_label(recipient, sender))).pages[0].extract_text()
    assert "Test Testesen" in text
    assert "8700 Horsens" in text
    assert "Afsender: Firmanavn" in text


def test_invalid_rotation_is_rejected(recipient, sender):
    with pytest.raises(ValueError):
        pdf.render_label(recipient, sender, rotation=180)


def test_short_address_uses_max_font_size(recipient, sender):
    result = layout.build_layout(recipient, sender)
    assert result.recipient_size == layout.RECIPIENT_MAX_SIZE


def test_long_name_shrinks_font(recipient, sender):
    recipient["name"] = "Testine Fiktivsen-Prøvegaard Navnesen"
    result = layout.build_layout(recipient, sender)
    assert layout.RECIPIENT_MIN_SIZE <= result.recipient_size < layout.RECIPIENT_MAX_SIZE


def test_too_long_raises(recipient, sender):
    recipient["name"] = "W" * 80
    with pytest.raises(layout.LabelTooLongError):
        pdf.render_label(recipient, sender)


def test_all_text_inside_margins(recipient, sender):
    recipient["extra"] = "c/o Testklubben"
    result = layout.build_layout(recipient, sender)
    for item in result.texts:
        width = layout.text_width(item.text, item.font, item.size)
        assert item.x >= layout.MARGIN
        assert item.x + width <= layout.LABEL_WIDTH - layout.MARGIN + 0.01
        assert item.y - layout.DESCENT * item.size >= layout.CONTENT_BOTTOM - 0.01
        assert item.y + layout.CAP_HEIGHT * item.size <= layout.CONTENT_TOP + 0.01


def test_recipient_is_below_rule(recipient, sender):
    result = layout.build_layout(recipient, sender)
    recipient_items = [t for t in result.texts if t.font == layout.FONT_BOLD]
    top = max(t.y + layout.CAP_HEIGHT * t.size for t in recipient_items)
    assert top <= result.rule_y - layout.RECIPIENT_GAP + 0.01


def test_empty_extra_line_is_skipped(recipient):
    assert layout.recipient_lines(recipient) == ["Test Testesen", "Fiktivvej 12, 2. tv", "8700 Horsens"]


def test_extra_line_goes_between_name_and_street(recipient):
    recipient["extra"] = "c/o Testklubben"
    assert layout.recipient_lines(recipient)[1] == "c/o Testklubben"


def test_long_sender_wraps_to_two_lines():
    sender = {"name": "Et meget langt firmanavn med mange ord ApS", "street": "Langgadevejen 123",
              "postcode": "8000", "city": "Aarhus C"}
    lines, size = layout.sender_lines(sender)
    assert len(lines) == 2
    assert lines[0].startswith("Afsender: ")
    assert layout.sender_fits(sender)


def test_layout_to_dict_is_in_mm(recipient, sender):
    data = layout.build_layout(recipient, sender).to_dict()
    assert data["width"] == pytest.approx(150)
    assert data["height"] == pytest.approx(100)
    assert all(15 <= t["x"] < 150 for t in data["texts"])
    assert data["too_long"] is False


@pytest.mark.parametrize("rotation", [90, 270])
def test_calibration_renders(rotation):
    pdf_bytes = pdf.render_calibration(rotation)
    width, height = page_size(pdf_bytes)
    assert (round(width, 1), round(height, 1)) == (283.5, 425.2)
    assert "mål med lineal" in PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
