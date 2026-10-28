"""Renders labels and the calibration page as PDF with ReportLab.

The positions come from layout.py; this module only draws them onto a
portrait 100 × 150 mm page, rotated so the label reads in landscape.

Run the module directly to produce sample PDFs without Flask or a printer:
    .venv\\Scripts\\python -m postalprint.labels.pdf
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from postalprint.labels.layout import (
    CONTENT_TOP, FONT, FONT_BOLD, LABEL_WIDTH, MARGIN, PAGE_HEIGHT, PAGE_WIDTH, RULE_WIDTH,
    LabelTooLongError, build_layout,
)

VALID_ROTATIONS = (90, 270)


def _apply_rotation(c: canvas.Canvas, rotation: int) -> None:
    """Rotates the coordinate system so that (0, 0)–(150, 100) mm covers the portrait page.

    Raises:
        ValueError: If ``rotation`` is not 90 or 270.
    """
    if rotation == 90:
        c.translate(PAGE_WIDTH, 0)
        c.rotate(90)
    elif rotation == 270:
        c.translate(0, PAGE_HEIGHT)
        c.rotate(-90)
    else:
        raise ValueError(f"Rotation must be 90 or 270, not {rotation}")


def _new_canvas(buffer: BytesIO, title: str) -> canvas.Canvas:
    """Creates a portrait 100 × 150 mm canvas with neutral metadata."""
    c = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    # Never put personal data in the PDF metadata
    c.setTitle(title)
    c.setAuthor("")
    c.setCreator("PostalPrint")
    return c


def render_label(recipient: dict, sender: dict, rotation: int = 90) -> bytes:
    """Renders an address label as PDF bytes.

    Args:
        recipient: Dict with name, extra, street, postcode and city.
        sender: Dict with name, street, postcode and city.
        rotation: 90 or 270 degrees, depending on how the printer feeds the label.

    Returns:
        The PDF file as bytes.

    Raises:
        LabelTooLongError: If the recipient cannot fit, even at 14 pt.
        ValueError: If ``rotation`` is invalid.
    """
    layout = build_layout(recipient, sender)
    if layout.recipient_size is None:
        raise LabelTooLongError("The recipient's address is too long for the label.")

    buffer = BytesIO()
    c = _new_canvas(buffer, "Adresseetiket")
    _apply_rotation(c, rotation)
    for item in layout.texts:
        c.setFont(item.font, item.size)
        c.drawString(item.x, item.y, item.text)
    if layout.rule_y is not None:
        c.setLineWidth(RULE_WIDTH)
        c.line(MARGIN, layout.rule_y, LABEL_WIDTH - MARGIN, layout.rule_y)
    c.showPage()
    c.save()
    return buffer.getvalue()


def render_calibration(rotation: int = 90) -> bytes:
    """Renders a test page that shows whether the printer scales or rotates the label.

    The page has a frame exactly 15 mm from the paper edge, tick marks every 10 mm
    along two edges, and an explanation printed in the same direction as a real label.
    """
    buffer = BytesIO()
    c = _new_canvas(buffer, "Kalibrering")
    c.setLineWidth(RULE_WIDTH)

    # Frame exactly 15 mm from the paper edge
    c.rect(MARGIN, MARGIN, PAGE_WIDTH - 2 * MARGIN, PAGE_HEIGHT - 2 * MARGIN)

    # Tick marks every 10 mm along the left and bottom edges (longer at every 50 mm)
    c.setFont(FONT, 6)
    for value in range(10, 150, 10):
        length = 6 * mm if value % 50 == 0 else 3 * mm
        c.line(0, value * mm, length, value * mm)
        c.drawString(length + 1 * mm, value * mm - 2, str(value))
    for value in range(10, 100, 10):
        length = 6 * mm if value % 50 == 0 else 3 * mm
        c.line(value * mm, 0, value * mm, length)
        c.drawCentredString(value * mm, length + 1 * mm, str(value))

    # Explanation (user-facing, so in Danish) in the same direction as a real label
    _apply_rotation(c, rotation)
    lines = [
        (FONT_BOLD, 16, "100 × 150 mm – mål med lineal"),
        (FONT, 10, "Rammen skal sidde præcis 15 mm fra papirets kant,"),
        (FONT, 10, "og stregerne skal ligge præcis for hver 10 mm."),
        (FONT, 10, f"Rotation: {rotation}°. Læses denne tekst liggende som på en kuvert,"),
        (FONT, 10, "er rotationen rigtig. Ellers skift rotation under Indstillinger."),
    ]
    y = CONTENT_TOP - 12 * mm
    for font, size, text in lines:
        c.setFont(font, size)
        c.drawCentredString(LABEL_WIDTH / 2, y, text)
        y -= size * 1.6
    c.showPage()
    c.save()
    return buffer.getvalue()


if __name__ == "__main__":
    from postalprint.paths import DATA_DIR

    # Fictional sample data
    example_sender = {"name": "Firmanavn", "street": "Eksempelvej 1", "postcode": "1234", "city": "Eksempelby"}
    example_recipient = {
        "name": "Test Testesen",
        "extra": "c/o Testklubben",
        "street": "Fiktivvej 12, 2. tv",
        "postcode": "8700",
        "city": "Horsens",
    }
    out_dir = DATA_DIR / "tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eksempel.pdf").write_bytes(render_label(example_recipient, example_sender))
    (out_dir / "kalibrering.pdf").write_bytes(render_calibration())
    print(f"Wrote eksempel.pdf and kalibrering.pdf to {out_dir}")
