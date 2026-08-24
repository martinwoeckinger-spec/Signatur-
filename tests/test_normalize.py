"""Tests für die Normalisierung vor dem Vergleich (FA-30, FA-31)."""
from signatur.normalize import (
    normalize_address,
    normalize_company,
    normalize_phone,
    normalize_url,
    values_equal,
)


def test_phone_to_e164_from_national_number():
    assert normalize_phone("089 1234-100", "DE") == "+49891234100"
    assert normalize_phone("+49 (0)89 1234 100") == "+49891234100"
    assert normalize_phone("0043 1 5550 100") == "+4315550100"
    assert normalize_phone("+41 44 200 30 40") == "+41442003040"


def test_phone_extension_is_stripped():
    assert normalize_phone("+49 89 1234 Durchwahl 55") == "+49891234"


def test_phone_unparseable_is_empty():
    assert normalize_phone("12345") == ""
    assert normalize_phone("") == ""


def test_format_only_difference_is_no_diff():
    # FA-31: Schreibweise, Leerzeichen, Schema, Rechtsform
    assert values_equal("phone", "+43 1 5550100", "+43 1 5550 100")
    assert values_equal("website", "https://www.Muster-Tech.de/", "www.muster-tech.de")
    assert values_equal("job_title", "Head of  Consulting", "head of consulting")
    assert values_equal("company", "Muster Tech GmbH", "Muster Tech G.m.b.H.")
    assert values_equal("address", "Altstadtring 2, 80331 München",
                        "Altstadtring 2, 80331 Muenchen")


def test_real_difference_is_kept():
    assert not values_equal("phone", "+49 89 1234 100", "+49 89 1234 200")
    assert not values_equal("job_title", "Senior Consultant", "Head of Consulting")
    assert not values_equal("company", "Muster Tech GmbH", "CloudScale AG")


def test_company_legal_form_and_subset():
    assert normalize_company("Nordwind AG") == "nordwind"
    assert values_equal("company", "Muster Tech", "Muster Tech Group")


def test_url_and_address_helpers():
    assert normalize_url("HTTPS://WWW.Example.com/") == "example.com"
    assert normalize_address("Hauptstr. 3") == normalize_address("Hauptstraße 3")
