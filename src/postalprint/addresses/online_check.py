"""Online address check (layer 2) using OpenStreetMap Nominatim.

- Produces warnings only, never errors: OpenStreetMap may lack brand-new addresses.
- If the internet is down or the service does not answer, the check is skipped.
- Only the road, house number and postcode are sent. The recipient's name never is.
- Nominatim's usage policy: at most one request per second and a descriptive
  User-Agent. Results are cached in memory, so each address is looked up once.

Nominatim needs no API key. Datafordeleren (DAR) can later be swapped in as the
source by writing a new lookup function with the same return type.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from postalprint.addresses.postcodes import lookup
from postalprint.addresses.validation import parse_street

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "PostalPrint/1.0 (local address label tool)"
TIMEOUT_SECONDS = 4
MIN_INTERVAL_SECONDS = 1.1

# Possible outcomes of a check
FOUND = "found"
WRONG_POSTCODE = "wrong_postcode"
NUMBER_NOT_FOUND = "number_not_found"
NOT_FOUND = "not_found"
UNAVAILABLE = "unavailable"
SKIPPED = "skipped"


@dataclass
class AddressCheck:
    """The outcome of an online check. ``message`` is user-facing (Danish)."""

    status: str
    message: str = ""

    @property
    def is_warning(self) -> bool:
        """True when the user should be warned before printing."""
        return self.status in (WRONG_POSTCODE, NUMBER_NOT_FOUND, NOT_FOUND)

    def to_dict(self) -> dict:
        return asdict(self) | {"is_warning": self.is_warning}


_cache: dict[tuple[str, str, str], AddressCheck] = {}
_lock = threading.Lock()  # serializes requests to respect the rate limit
_last_request = 0.0


def _fetch(params: dict[str, str]) -> list[dict]:
    """Sends one search request to Nominatim, waiting so requests are at least 1 s apart."""
    global _last_request
    query = urllib.parse.urlencode(params | {"countrycodes": "dk", "format": "jsonv2", "addressdetails": 1, "limit": 10})
    request = urllib.request.Request(f"{NOMINATIM_URL}?{query}", headers={"User-Agent": USER_AGENT})
    wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    finally:
        _last_request = time.monotonic()


def _same(a: str, b: str) -> bool:
    """Compares road names and house numbers, ignoring case and spaces ("12 B" == "12b")."""
    return a.replace(" ", "").casefold() == b.replace(" ", "").casefold()


def _evaluate(results: list[dict], road: str, house_number: str, postcode: str) -> AddressCheck | None:
    """Interprets Nominatim's results.

    Returns:
        The outcome, or None if nothing relevant was found.
    """
    addresses = [r.get("address", {}) for r in results]
    on_road = [a for a in addresses if _same(a.get("road", ""), road)]
    exact = [a for a in on_road if _same(a.get("house_number", ""), house_number)]
    if any(a.get("postcode") == postcode for a in exact):
        return AddressCheck(FOUND, "Adressen findes.")
    if exact:
        # The same road name often exists in many towns, so show up to three postcodes
        others = sorted({a.get("postcode", "") for a in exact} - {""})[:3]
        places = ", ".join(f"{code} {lookup(code) or ''}".strip() for code in others)
        return AddressCheck(WRONG_POSTCODE,
                            f"{road} {house_number} blev ikke fundet i {postcode}, men findes i {places}. Tjek postnummeret.")
    if any(a.get("postcode") == postcode for a in on_road):
        return AddressCheck(NUMBER_NOT_FOUND, f"{road} findes i {postcode}, men husnummer {house_number} blev ikke fundet.")
    return None


def check_address(street: str, postcode: str) -> AddressCheck:
    """Looks up an address online.

    Never raises: network problems return an UNAVAILABLE result instead,
    so a missing internet connection can never block printing.

    Args:
        street: The street as typed, e.g. "Fiktivvej 12B, 2. tv". Floor and door are not sent.
        postcode: A four-digit postcode.
    """
    parts = parse_street(street)
    if parts is None or len(postcode) != 4:
        return AddressCheck(SKIPPED)
    if parts.road.casefold().startswith(("postboks", "boks")):
        return AddressCheck(SKIPPED)  # PO boxes are not in OpenStreetMap

    key = (parts.road.casefold(), parts.house_number.casefold(), postcode)
    with _lock:
        if key in _cache:
            return _cache[key]
        try:
            street_query = f"{parts.house_number} {parts.road}"
            result = _evaluate(_fetch({"street": street_query, "postalcode": postcode}),
                               parts.road, parts.house_number, postcode)
            if result is None:
                # Maybe the postcode is wrong: search for road and number in the whole country
                result = _evaluate(_fetch({"street": street_query}), parts.road, parts.house_number, postcode)
            if result is None:
                result = AddressCheck(NOT_FOUND, f"{parts.road} {parts.house_number}, {postcode} blev ikke fundet online – tjek stavningen.")
        except Exception:  # network, timeout, invalid response: just skip the check
            return AddressCheck(UNAVAILABLE, "Online-tjek er ikke tilgængeligt lige nu.")
        _cache[key] = result
        return result


def clear_cache() -> None:
    """Forgets all cached results (used by tests)."""
    _cache.clear()
