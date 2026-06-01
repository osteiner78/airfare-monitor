import pytest


def _airline_code(flight_number):
    from backend.pages import _airline_code as fn
    return fn(flight_number)


# --- NEW-BEHAVIOR ---

def test_extracts_iata_code_from_flight_number():
    assert _airline_code("VY 6201") == "VY"


def test_extracts_first_carrier_code_from_multileg():
    assert _airline_code("VY 6201+IB 5678") == "VY"


def test_uppercases_lowercase_code():
    assert _airline_code("vy 6201") == "VY"


def test_strips_surrounding_whitespace():
    assert _airline_code("  LH 400 ") == "LH"


def test_accepts_alphanumeric_code():
    assert _airline_code("U2 8001") == "U2"
    assert _airline_code("6X 100") == "6X"


# --- FAILURE-MODE ---

def test_returns_empty_for_empty_string():
    assert _airline_code("") == ""


def test_returns_empty_for_none():
    assert _airline_code(None) == ""


def test_returns_empty_for_three_digit_flight_number():
    assert _airline_code("123") == ""


def test_returns_empty_for_overlong_token():
    assert _airline_code("ABCDE 1") == ""


def test_returns_empty_for_unicode_token():
    assert _airline_code("✈ 100") == ""


def test_returns_empty_for_blacklisted_code(monkeypatch):
    import backend.pages as pages
    monkeypatch.setattr(pages, "LOGO_UNAVAILABLE_CODES", {"ZZ"})
    assert _airline_code("ZZ 100") == ""
