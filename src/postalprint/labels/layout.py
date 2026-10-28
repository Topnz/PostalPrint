"""Label geometry and text layout.

Computes where every piece of text goes on the label. The same layout drives
both the PDF (see pdf.py) and the live preview in the browser, so what you
see is what gets printed.

All measurements are in points (pt), where 1 mm = 2.8346 pt.
ReportLab's coordinate system has its origin in the bottom-left corner.
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

# Physical media: portrait 100 × 150 mm, exactly what the printer driver expects
PAGE_WIDTH = 100 * mm
PAGE_HEIGHT = 150 * mm

# The content is laid out in landscape (150 × 100 mm) and rotated onto the portrait page
LABEL_WIDTH = PAGE_HEIGHT
LABEL_HEIGHT = PAGE_WIDTH
MARGIN = 15 * mm
CONTENT_WIDTH = LABEL_WIDTH - 2 * MARGIN  # 120 mm
CONTENT_TOP = LABEL_HEIGHT - MARGIN
CONTENT_BOTTOM = MARGIN

# Built-in PDF fonts; their WinAnsi encoding covers Danish letters (æ, ø, å)
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
LINE_SPACING = 1.25

SENDER_PREFIX = "Afsender: "
SENDER_SEPARATOR = " · "
SENDER_SIZE = 9
SENDER_MIN_SIZE = 7
SENDER_MAX_LINES = 2

RECIPIENT_MAX_SIZE = 26
RECIPIENT_MIN_SIZE = 14

RULE_WIDTH = 0.75  # thermal printers drop lines thinner than 0.5 pt
RULE_GAP = 3  # pt from the sender's descender down to the rule
RECIPIENT_GAP = 6 * mm  # space between the rule and the recipient block

# Helvetica metrics as a fraction of the font size: cap height and descender depth
CAP_HEIGHT = 0.718
DESCENT = 0.207


class LabelTooLongError(ValueError):
    """Raised when the text cannot fit on the label, even at the smallest font size."""


@dataclass
class TextItem:
    """A single line of text positioned on the landscape label."""

    text: str
    x: float  # pt from the left edge of the landscape label
    y: float  # baseline, pt from the bottom of the landscape label
    font: str
    size: float


@dataclass
class Layout:
    """The computed position of everything on the label, shared by the PDF and the preview."""

    texts: list[TextItem]
    rule_y: float | None  # None when there is no sender
    recipient_size: int | None  # None when the recipient does not fit

    def to_dict(self) -> dict:
        """Returns the layout in millimetres for the browser preview (an SVG with viewBox 150 × 100)."""
        return {
            "width": round(LABEL_WIDTH / mm, 2),
            "height": round(LABEL_HEIGHT / mm, 2),
            "margin": round(MARGIN / mm, 2),
            "texts": [
                {
                    "text": item.text,
                    "x": round(item.x / mm, 2),
                    "y": round(item.y / mm, 2),
                    "size": round(item.size / mm, 3),
                    "bold": item.font == FONT_BOLD,
                }
                for item in self.texts
            ],
            "rule": None if self.rule_y is None else {
                "x1": round(MARGIN / mm, 2),
                "x2": round((LABEL_WIDTH - MARGIN) / mm, 2),
                "y": round(self.rule_y / mm, 2),
                "width": round(RULE_WIDTH / mm, 3),
            },
            "recipient_size": self.recipient_size,
            "too_long": self.recipient_size is None,
        }


def text_width(text: str, font: str, size: float) -> float:
    """Returns the rendered width of ``text`` in points."""
    return stringWidth(text, font, size)


def recipient_lines(recipient: dict) -> list[str]:
    """Returns the recipient's lines in print order: name, extra line, street, postcode + city.

    Empty lines (typically the optional extra line) are left out.
    """
    postal_line = f"{recipient.get('postcode', '')} {recipient.get('city', '')}".strip()
    lines = [recipient.get("name", ""), recipient.get("extra", ""), recipient.get("street", ""), postal_line]
    return [line.strip() for line in lines if line and line.strip()]


def fits_at_min_size(text: str) -> bool:
    """Tells whether ``text`` fits on one line at the smallest recipient font size.

    Used by the validation to reject fields that can never fit on the label.
    """
    return text_width(text, FONT_BOLD, RECIPIENT_MIN_SIZE) <= CONTENT_WIDTH


def block_height(line_count: int, size: float) -> float:
    """Returns the height from the top line's cap height to the bottom line's descender."""
    if line_count == 0:
        return 0
    return CAP_HEIGHT * size + (line_count - 1) * size * LINE_SPACING + DESCENT * size


def fit_recipient_size(lines: list[str], available_height: float) -> int | None:
    """Finds the largest font size (26 → 14 pt) at which every line fits in width and height.

    Args:
        lines: The recipient lines to fit.
        available_height: The vertical space in points.

    Returns:
        The font size in points, or None if the lines do not fit even at the minimum size.
    """
    for size in range(RECIPIENT_MAX_SIZE, RECIPIENT_MIN_SIZE - 1, -1):
        widest = max((text_width(line, FONT_BOLD, size) for line in lines), default=0)
        if widest <= CONTENT_WIDTH and block_height(len(lines), size) <= available_height:
            return size
    return None


def _wrap_segments(segments: list[str], size: float) -> list[str]:
    """Joins the sender's parts onto as few lines as possible, separated by ' · '."""
    lines: list[str] = []
    for segment in segments:
        candidate = f"{lines[-1]}{SENDER_SEPARATOR}{segment}" if lines else segment
        if lines and text_width(candidate, FONT, size) <= CONTENT_WIDTH:
            lines[-1] = candidate
        else:
            lines.append(segment)
    return lines


def sender_lines(sender: dict) -> tuple[list[str], float]:
    """Lays out the sender, shrinking from 9 pt down to 7 pt if needed to stay within two lines.

    Returns:
        A tuple of (lines, font size). The lines are empty when no sender is configured.
    """
    postal_line = f"{sender.get('postcode', '')} {sender.get('city', '')}".strip()
    segments = [s.strip() for s in (sender.get("name", ""), sender.get("street", ""), postal_line) if s and s.strip()]
    if not segments:
        return [], SENDER_SIZE
    segments[0] = SENDER_PREFIX + segments[0]
    lines: list[str] = []
    for size in range(SENDER_SIZE, SENDER_MIN_SIZE - 1, -1):
        lines = _wrap_segments(segments, size)
        if len(lines) <= SENDER_MAX_LINES and all(text_width(l, FONT, size) <= CONTENT_WIDTH for l in lines):
            return lines, size
    return lines, SENDER_MIN_SIZE


def sender_fits(sender: dict) -> bool:
    """Tells whether the sender fits within two lines at 7 pt or larger."""
    lines, size = sender_lines(sender)
    return len(lines) <= SENDER_MAX_LINES and all(text_width(l, FONT, size) <= CONTENT_WIDTH for l in lines)


def build_layout(recipient: dict, sender: dict) -> Layout:
    """Computes where every piece of text goes on the landscape label.

    The sender sits at the top in small print with a thin rule below it.
    The recipient is bottom-aligned in the content area, as large as possible.
    """
    texts: list[TextItem] = []

    # Sender at the top, followed by the rule
    lines, size = sender_lines(sender)
    rule_y = None
    y = CONTENT_TOP - CAP_HEIGHT * size
    for line in lines:
        texts.append(TextItem(line, MARGIN, y, FONT, size))
        y -= size * LINE_SPACING
    if lines:
        last_baseline = y + size * LINE_SPACING
        rule_y = last_baseline - DESCENT * size - RULE_GAP

    # Recipient at the bottom of the content area
    top_limit = (rule_y if rule_y is not None else CONTENT_TOP) - RECIPIENT_GAP
    r_lines = recipient_lines(recipient)
    r_size = fit_recipient_size(r_lines, top_limit - CONTENT_BOTTOM)
    draw_size = r_size or RECIPIENT_MIN_SIZE
    bottom_baseline = CONTENT_BOTTOM + DESCENT * draw_size
    for index, line in enumerate(r_lines):
        lines_below = len(r_lines) - 1 - index
        baseline = bottom_baseline + lines_below * draw_size * LINE_SPACING
        texts.append(TextItem(line, MARGIN, baseline, FONT_BOLD, draw_size))

    return Layout(texts=texts, rule_y=rule_y, recipient_size=r_size if r_lines else None)
