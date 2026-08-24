"""Normalisierung beider Vergleichsseiten vor der Diff-Bildung (FA-30, FA-31).

Ziel: rein formatbedingte Unterschiede (Schreibweise, Leerzeichen, Rechtsform-
Zusätze, Telefonformate, URL-Präfixe) dürfen keine Abweichung erzeugen.
Der Vergleich läuft immer über die normalisierte Form; angezeigt und ins CRM
geschrieben wird dagegen der Originalwert aus der Signatur.
"""
from __future__ import annotations

import re
import unicodedata

# Landesvorwahlen für die Umsetzung nationaler Nummern nach E.164
COUNTRY_CODES = {
    "DE": "49", "AT": "43", "CH": "41", "LI": "423", "IT": "39", "FR": "33",
    "ES": "34", "NL": "31", "BE": "32", "LU": "352", "PL": "48", "CZ": "420",
    "SK": "421", "HU": "36", "SI": "386", "DK": "45", "SE": "46", "NO": "47",
    "FI": "358", "GB": "44", "IE": "353", "US": "1", "CA": "1",
}

# Rechtsformzusätze, die für den Vergleich von Organisationsnamen entfallen
LEGAL_FORMS = [
    "gesellschaft mit beschränkter haftung", "aktiengesellschaft",
    "gmbh & co. kg", "gmbh & co kg", "gmbh", "mbh", "ag", "kgaa", "kg", "ohg",
    "gbr", "ug (haftungsbeschränkt)", "ug", "se", "e.u.", "e.k.", "e.v.",
    "gesmbh", "ges.m.b.h.", "inc.", "inc", "llc", "l.l.c.", "ltd.", "ltd",
    "limited", "plc", "corp.", "corp", "corporation", "co.", "s.a.", "sa",
    "sarl", "s.à r.l.", "b.v.", "bv", "n.v.", "nv", "srl", "s.r.l.", "oy", "ab",
    "as", "aps", "spa", "s.p.a.",
]

# Gängige Abkürzungen in Adressen und Positionsbezeichnungen
ABBREVIATIONS = {
    r"\bstr\.": "strasse",
    r"\bstr\b": "strasse",
    r"\bstrasse\b": "strasse",
    r"\bstraße\b": "strasse",
    r"\bpl\.": "platz",
    r"\bhauptstr\b": "hauptstrasse",
    r"\bnr\.": "",
    r"\bno\.": "",
    r"\bst\.": "sankt",
    r"\ba\.d\.": "an der",
    r"\bgeschäftsführer(in)?\b": "geschaeftsfuehrer",
    r"\bgf\b": "geschaeftsfuehrer",
    r"\bsen\.": "senior",
    r"\bsr\.": "senior",
    r"\bjun\.": "junior",
    r"\bjr\.": "junior",
    r"\bdipl\.-ing\.": "diplom ingenieur",
    r"\bdipl\.": "diplom",
    r"\bmgmt\b": "management",
    r"\bdept\.?\b": "department",
    r"\babt\.?\b": "abteilung",
}

_ACADEMIC_GRADES = re.compile(
    r"\b(prof|dr|dipl|mag|ing|mba|msc|m\.sc|bsc|b\.sc|ba|ma|llm|phd|habil)\.?\b",
    re.I,
)


def _fold(value: str) -> str:
    """Kleinschreibung, Umlaut-/Akzentfaltung, Whitespace-Normalisierung."""
    text = (value or "").strip().lower()
    text = (text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                .replace("ß", "ss"))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def normalize_text(value: str) -> str:
    """Allgemeine Textnormalisierung inkl. gängiger Abkürzungen."""
    text = _fold(value)
    for pattern, replacement in ABBREVIATIONS.items():
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[.,;:_/\\\-–—|]+", " ", text)
    return " ".join(text.split())


def normalize_name(value: str) -> str:
    """Personenname ohne akademische Grade."""
    return " ".join(_ACADEMIC_GRADES.sub(" ", _fold(value)).replace(".", " ").split())


def normalize_company(value: str) -> str:
    """Organisationsname ohne Rechtsformzusatz und Interpunktion."""
    text = _fold(value)
    text = re.sub(r"[,;]", " ", text)
    for form in sorted(LEGAL_FORMS, key=len, reverse=True):
        text = re.sub(rf"(?:^|\s){re.escape(_fold(form))}(?=\s|$)", " ", text)
    text = re.sub(r"[.\-–—|&]+", " ", text)
    return " ".join(text.split())


def normalize_url(value: str) -> str:
    """Website/URL ohne Schema, 'www.' und abschließenden Slash."""
    text = _fold(value)
    text = re.sub(r"^[a-z]+://", "", text)
    text = re.sub(r"^www\.", "", text)
    return text.rstrip("/")


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def normalize_phone(value: str, default_region: str = "DE") -> str:
    """Telefonnummer nach E.164 (`+<Land><Nummer>`), soweit ableitbar.

    Nicht auflösbare Eingaben liefern die reine Ziffernfolge zurück, damit der
    Vergleich nicht auf ein leeres Ergebnis zurückfällt.
    """
    if not value:
        return ""
    raw = str(value).strip()
    # Durchwahl-Zusätze ("Durchwahl 12", "ext. 12") und (0) entfernen
    raw = re.sub(r"\(0\)", "", raw)
    raw = re.split(r"\b(?:durchwahl|dw|ext|extension|x)\b\.?\s*\d+", raw, flags=re.I)[0]
    digits = re.sub(r"[^\d+]", "", raw)
    lead = "+" if digits.startswith("+") else ""
    digits = lead + digits.replace("+", "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("+"):
        national = re.sub(r"\D", "", digits)
        return "+" + national if len(national) >= 6 else ""
    national = re.sub(r"\D", "", digits)
    if len(national) < 6:
        return ""
    code = COUNTRY_CODES.get((default_region or "DE").upper(), "49")
    return "+" + code + national.lstrip("0")


def normalize_postal_code(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().upper())


def normalize_address(value: str) -> str:
    """Adresse: Abkürzungen auflösen, Interpunktion und Reihenfolge glätten."""
    text = normalize_text(value)
    # "80331 muenchen" und "muenchen 80331" sollen gleich behandelt werden
    tokens = sorted(text.split()) if text else []
    return " ".join(tokens)


_NORMALIZERS = {
    "email": normalize_email,
    "phone": normalize_phone,
    "mobile": normalize_phone,
    "fax": normalize_phone,
    "website": normalize_url,
    "linkedin": normalize_url,
    "company": normalize_company,
    "full_name": normalize_name,
    "first_name": normalize_name,
    "last_name": normalize_name,
    "academic_title": normalize_text,
    "address": normalize_address,
    "street": normalize_text,
    "postal_code": normalize_postal_code,
    "city": normalize_text,
    "country": normalize_text,
}


def normalize_value(field: str, value: str, default_region: str = "DE") -> str:
    """Normalisiert einen Feldwert gemäß Feldtyp (Default: `normalize_text`)."""
    func = _NORMALIZERS.get(field, normalize_text)
    if func is normalize_phone:
        return normalize_phone(value, default_region=default_region)
    return func(value)


def values_equal(field: str, a: str, b: str, default_region: str = "DE") -> bool:
    """True, wenn sich zwei Werte nach Normalisierung nicht unterscheiden."""
    na = normalize_value(field, a, default_region)
    nb = normalize_value(field, b, default_region)
    if not na or not nb:
        return na == nb
    if na == nb:
        return True
    if field in ("company",):
        # "Muster Tech" vs. "Muster Tech Group": Teilmenge gilt als gleich,
        # solange der kürzere Name vollständig im längeren enthalten ist.
        short, long = sorted((na, nb), key=len)
        return bool(short) and (f" {short} " in f" {long} ")
    return False
