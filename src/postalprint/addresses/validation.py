"""Offline validation of the recipient and sender (layer 1).

Pure functions with no Flask, network or file access: postcodes and recent
history are passed in as parameters, so everything can be tested in isolation.

- Errors block printing.
- Warnings require an extra Enter to print anyway.

The online check (layer 2) lives in online_check.py and only produces warnings.
Messages are user-facing and therefore in Danish.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from postalprint.labels import layout

RECIPIENT_FIELDS = ("name", "extra", "street", "postcode", "city")
SENDER_FIELDS = ("name", "street", "postcode", "city")

NAME_MIN_LENGTH = 2
NAME_MAX_LENGTH = 60
FIELD_MAX_LENGTH = 100
DUPLICATE_DAYS = 14

# Street name (at least one letter) + house number 1–999 + optional letter + optional floor/door.
# Examples: "Fiktivvej 12", "Fiktivvej 12B", "Fiktivvej 12 B, 2. tv", "Kong Fiktiv IX's Gade 3".
STREET_PATTERN = re.compile(
    r"^(?P<road>.*?[^\W\d_].*?)\s+(?P<number>\d{1,3})\s?(?P<letter>[A-Za-zÆØÅæøå])?(?=$|[\s,])(?P<rest>.*)$"
)
NUMBER_FIRST_PATTERN = re.compile(r"^\d{1,3}\s?[A-Za-z]?\s+[^\W\d_]")
FOUR_DIGITS_PATTERN = re.compile(r"(?<!\d)\d{4}(?!\d)")
LETTER_PATTERN = re.compile(r"[^\W\d_]")


@dataclass
class StreetParts:
    """A street address split into its parts, e.g. "Fiktivvej 12B, 2. tv"."""

    road: str
    number: str
    letter: str
    rest: str  # floor and door, e.g. ", 2. tv"

    @property
    def house_number(self) -> str:
        """The house number including an optional letter, e.g. "12B"."""
        return f"{self.number}{self.letter.upper()}"


@dataclass
class ValidationResult:
    """The cleaned recipient plus any errors and warnings, keyed by field name."""

    recipient: dict
    errors: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize_text(value: object) -> str:
    """Trims and collapses repeated whitespace (including newlines) to one space.

    Upper and lower case are deliberately left unchanged.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_postcode(value: object) -> str:
    """Removes spaces and a "DK-" prefix, so "8 700" and "DK-8700" both become "8700"."""
    text = re.sub(r"\s+", "", normalize_text(value))
    return re.sub(r"^(?i:dk)-?", "", text)


def normalize(raw: dict, fields: tuple[str, ...] = RECIPIENT_FIELDS) -> dict:
    """Returns a dict with exactly ``fields``, each normalized. Missing fields become ""."""
    result = {name: normalize_text(raw.get(name)) for name in fields}
    if "postcode" in result:
        result["postcode"] = normalize_postcode(raw.get("postcode"))
    return result


def parse_street(street: str) -> StreetParts | None:
    """Splits "Fiktivvej 12B, 2. tv" into road, number, letter and the rest.

    Returns:
        The parts, or None if the text is not a street name followed by a house number.
    """
    match = STREET_PATTERN.match(street)
    if not match:
        return None
    return StreetParts(
        road=match.group("road").strip(),
        number=match.group("number"),
        letter=match.group("letter") or "",
        rest=match.group("rest").strip(),
    )


def unprintable_char(text: str) -> str | None:
    """Returns the first character the label font (Helvetica, Windows-1252) cannot print, if any."""
    for char in text:
        try:
            char.encode("cp1252")
        except UnicodeEncodeError:
            return char
    return None


def sender_missing(sender: dict) -> bool:
    """Tells whether any of the sender's required fields is empty."""
    return any(not normalize_text(sender.get(name)) for name in SENDER_FIELDS)


def _check_street(street: str) -> str | None:
    """Returns an error message if the street is not "road name + house number"."""
    if FOUR_DIGITS_PATTERN.search(street):
        return "Postnummeret skal stå i feltet Postnummer, ikke i adressen."
    if not LETTER_PATTERN.search(street):
        return "Adressen mangler et vejnavn, fx 'Vejnavn 12'."
    if not re.search(r"\d", street):
        return "Adressen mangler husnummer, fx 'Vejnavn 12'."
    if NUMBER_FIRST_PATTERN.match(street):
        return "Husnummeret skal stå efter vejnavnet, fx 'Vejnavn 12'."
    parts = parse_street(street)
    if parts is None:
        return "Skriv vejnavn og husnummer, fx 'Vejnavn 12' eller 'Vejnavn 12B, 2. tv'."
    if int(parts.number) == 0:
        return "Husnummeret kan ikke være 0."
    return None


def _check_postcode(postcode: str, postcodes: dict[str, str]) -> str | None:
    """Returns an error message unless the postcode is four digits and exists."""
    if not re.fullmatch(r"\d{4}", postcode):
        return "Postnummeret skal være 4 cifre."
    if postcode not in postcodes:
        return "Postnummeret findes ikke i Danmark."
    return None


def _check_city(city: str) -> str | None:
    """Returns an error message if the city contains digits (usually a pasted postcode)."""
    if re.search(r"\d", city):
        return "Byen må ikke indeholde tal – postnummeret har sit eget felt."
    return None


def _duplicate_warning(recipient: dict, recent_entries, now: datetime) -> str | None:
    """Warns if the same name and street were printed within the last 14 days (case-insensitive)."""
    name, street = recipient["name"].casefold(), recipient["street"].casefold()
    for entry in recent_entries:
        printed_at = datetime.fromisoformat(entry["printed_at"])
        if now - printed_at > timedelta(days=DUPLICATE_DAYS):
            continue
        r = entry.get("recipient", {})
        if r.get("name", "").casefold() == name and r.get("street", "").casefold() == street:
            return f"{recipient['name']} på {recipient['street']} blev printet {printed_at:%d.%m.%Y} – er det en dublet?"
    return None


def validate(
    raw: dict,
    sender: dict,
    postcodes: dict[str, str],
    recent_entries=(),
    now: datetime | None = None,
) -> ValidationResult:
    """Normalizes and validates a recipient.

    Args:
        raw: The fields as typed in the form.
        sender: The configured sender; an incomplete sender is an error.
        postcodes: Mapping of valid postcodes to official city names.
        recent_entries: History entries used for the duplicate check.
        now: The current time (injectable for tests).

    Returns:
        The cleaned recipient together with errors (block printing) and warnings.
    """
    recipient = normalize(raw)
    result = ValidationResult(recipient=recipient)
    errors, warnings = result.errors, result.warnings

    if sender_missing(sender):
        errors["sender"] = "Udfyld din afsenderadresse under Indstillinger først."

    # Required fields
    required = {"name": "Skriv modtagerens navn.", "street": "Skriv adressen.",
                "postcode": "Skriv postnummer.", "city": "Skriv by."}
    for name, message in required.items():
        if not recipient[name]:
            errors[name] = message

    # Characters the label font cannot print (e.g. emoji, Polish or Turkish letters)
    for name in RECIPIENT_FIELDS:
        char = unprintable_char(recipient[name])
        if char and name not in errors:
            errors[name] = f"Tegnet «{char}» kan ikke printes på etiketten."
        elif len(recipient[name]) > FIELD_MAX_LENGTH and name not in errors:
            errors[name] = "Teksten er for lang."

    # Field-specific rules
    name = recipient["name"]
    if name and "name" not in errors:
        if len(name) < NAME_MIN_LENGTH:
            errors["name"] = f"Navnet skal være mindst {NAME_MIN_LENGTH} tegn."
        elif len(name) > NAME_MAX_LENGTH:
            errors["name"] = f"Navnet må højst være {NAME_MAX_LENGTH} tegn."
        elif not LETTER_PATTERN.search(name):
            errors["name"] = "Navnet skal indeholde bogstaver."
        elif parse_street(name):
            # Typical mistake: the address was typed into the name field
            warnings["name"] = "Navnet ligner en adresse – står adressen i navnefeltet?"

    if recipient["street"] and "street" not in errors:
        message = _check_street(recipient["street"])
        if message:
            errors["street"] = message

    if recipient["postcode"] and "postcode" not in errors:
        message = _check_postcode(recipient["postcode"], postcodes)
        if message:
            errors["postcode"] = message

    if recipient["city"] and "city" not in errors:
        message = _check_city(recipient["city"])
        if message:
            errors["city"] = message

    if recipient["extra"] and "extra" not in errors and recipient["extra"].casefold() in (
        name.casefold(), recipient["street"].casefold()
    ):
        warnings["extra"] = "Ekstra linje gentager navn eller adresse."

    # Can the text fit on the label at all, at the smallest font size?
    for field_name in ("name", "extra", "street"):
        text = recipient[field_name]
        if text and field_name not in errors and not layout.fits_at_min_size(text):
            errors[field_name] = "For lang til etiketten – forkort teksten."
    postal_line = f"{recipient['postcode']} {recipient['city']}"
    if recipient["city"] and "city" not in errors and not layout.fits_at_min_size(postal_line):
        errors["city"] = "For lang til etiketten – forkort teksten."

    # Warnings (only for fields without errors)
    official = postcodes.get(recipient["postcode"])
    if official and recipient["city"] and "city" not in errors and recipient["city"].casefold() != official.casefold():
        warnings["city"] = f"Postnummer {recipient['postcode']} hedder officielt «{official}»."

    if not errors:
        duplicate = _duplicate_warning(recipient, recent_entries, now or datetime.now().astimezone())
        if duplicate:
            warnings["duplicate"] = duplicate

    return result


def validate_sender(raw: dict, postcodes: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Validates the sender entered in Settings.

    Returns:
        A tuple of (cleaned sender, errors keyed by field name).
    """
    sender = normalize(raw, SENDER_FIELDS)
    errors: dict[str, str] = {}
    labels = {"name": "Skriv afsenderens navn.", "street": "Skriv adressen.",
              "postcode": "Skriv postnummer.", "city": "Skriv by."}
    for name, message in labels.items():
        if not sender[name]:
            errors[name] = message
        elif unprintable_char(sender[name]):
            errors[name] = f"Tegnet «{unprintable_char(sender[name])}» kan ikke printes."
    if sender["postcode"] and "postcode" not in errors:
        message = _check_postcode(sender["postcode"], postcodes)
        if message:
            errors["postcode"] = message
    if not errors and not layout.sender_fits(sender):
        errors["name"] = "Afsenderen er for lang til at være på to linjer – forkort den."
    return sender, errors
