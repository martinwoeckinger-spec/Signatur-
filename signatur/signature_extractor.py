"""Findet den Signaturblock einer E-Mail und extrahiert geschäftsrelevanten Kontext."""
from __future__ import annotations

import re
from typing import Optional

from .models import LoadedEmail, Signature

# --- Muster -----------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(
    r"\b((?:https?://)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/[^\s|<>]*)?)",
)
# Telefonnummern: +, Klammern, Leer-/Bindestriche, Slash; mind. 6 Ziffern
PHONE_RE = re.compile(r"(?<![\w@])(\+?\(?\d[\d\s().\-/]{5,}\d)")
LINKEDIN_RE = re.compile(r"(https?://)?([a-z]{2,3}\.)?linkedin\.com/[^\s|<>]+", re.I)

# Deutsche + englische Grußformeln, die typischerweise dem Signaturblock vorangehen
GREETINGS = [
    "mit freundlichen grüßen", "mit freundlichen gruessen", "freundliche grüße",
    "freundliche gruesse", "viele grüße", "viele gruesse", "beste grüße",
    "beste gruesse", "herzliche grüße", "liebe grüße", "mfg", "lg",
    "best regards", "kind regards", "warm regards", "best wishes",
    "regards", "cheers", "sincerely", "yours sincerely", "thanks and regards",
    "thank you", "vielen dank", "danke",
]

# Telefon-Labels → Feldzuordnung
PHONE_LABELS = {
    "phone": ["tel", "tel.", "phone", "fon", "fixed", "festnetz", "office", "büro",
              "buero", "t:", "p:", "ph:", "direct", "durchwahl"],
    "mobile": ["mobil", "mobile", "cell", "cellular", "handy", "m:", "mob", "mo:"],
    "fax": ["fax", "f:", "telefax"],
}

# Firmenrechtsformen / -kennungen
COMPANY_HINTS = [
    "gmbh", "ag", "kg", "ohg", "se", "e.u.", "e.k.", "gbr", "ug", "mbh",
    "inc", "inc.", "llc", "ltd", "ltd.", "plc", "corp", "corporation",
    "co.", "group", "gruppe", "holding", "partners", "& co",
]

# Titel-/Rollen-Schlüsselwörter mit Seniorität
TITLE_KEYWORDS = {
    "C-Level": [
        "ceo", "cfo", "cto", "coo", "cio", "cmo", "cdo", "geschäftsführer",
        "geschaeftsfuehrer", "geschäftsführerin", "vorstand", "managing director",
        "owner", "inhaber", "gesellschafter", "president", "partner",
    ],
    "Leitung": [
        "head of", "leiter", "leiterin", "leitung", "director", "direktor",
        "vp ", "vice president", "vorstandsvorsitz", "abteilungsleiter",
        "teamleiter", "bereichsleiter", "prokurist",
    ],
    "Management": [
        "manager", "managerin", "lead", "principal", "senior manager",
        "projektleiter", "key account",
    ],
    "Fachkraft": [
        "engineer", "developer", "entwickler", "consultant", "berater",
        "specialist", "spezialist", "analyst", "referent", "sachbearbeiter",
        "architect", "designer", "scientist", "expert", "associate",
    ],
}

DECISION_MAKER_LEVELS = {"C-Level", "Leitung"}

# Wörter, die KEINE Personennamen sind (für die Namensheuristik)
_NON_NAME_TOKENS = re.compile(
    r"@|http|www|tel|mobil|fax|gmbh|\bag\b|\d|straße|strasse|str\.|platz|"
    r"www\.|e-mail|mail:|phone|grüße|gruesse|regards",
    re.I,
)


# --- Signaturblock finden ----------------------------------------------------

def _strip_quoted(lines: list[str]) -> list[str]:
    """Entfernt zitierten Verlauf (>, 'Von:', 'On ... wrote:', '-----')."""
    out: list[str] = []
    for ln in lines:
        low = ln.strip().lower()
        if ln.lstrip().startswith(">"):
            break
        if low.startswith(("von:", "from:", "gesendet:", "sent:")) and ":" in ln:
            break
        if re.match(r"^-{3,}original", low) or low.startswith("-----"):
            break
        if re.match(r"^(am|on)\b.*\b(schrieb|wrote):", low):
            break
        out.append(ln)
    return out


def extract_signature_block(body: str) -> str:
    """Isoliert den mutmaßlichen Signaturblock aus dem Mailtext."""
    if not body:
        return ""
    lines = _strip_quoted(body.splitlines())

    # 1) RFC-3676-Trenner "-- "
    for i, ln in enumerate(lines):
        if ln.strip() in ("--", "-- "):
            block = "\n".join(lines[i + 1:]).strip()
            if block:
                return block

    # 2) Letzte Grußformel als Ankerpunkt
    anchor = None
    for i, ln in enumerate(lines):
        low = ln.strip().lower().rstrip(",.!").strip()
        if low in GREETINGS or any(low.startswith(g) for g in GREETINGS):
            anchor = i
    if anchor is not None:
        block = "\n".join(lines[anchor + 1:]).strip()
        if block:
            return block

    # 3) Fallback: letzte bis zu 8 nicht-leeren Zeilen, wenn sie nach
    #    Kontaktinfo aussehen (E-Mail/Telefon/Firmenkennung vorhanden)
    nonempty = [ln for ln in lines if ln.strip()]
    tail = "\n".join(nonempty[-8:])
    if EMAIL_RE.search(tail) or PHONE_RE.search(tail) or _has_company_hint(tail):
        return tail.strip()
    return ""


def _has_company_hint(text: str) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(h)}\b", low) for h in COMPANY_HINTS)


# --- Feld-Extraktion ---------------------------------------------------------

def _classify_phone_line(line: str) -> Optional[str]:
    low = line.lower()
    for field, labels in PHONE_LABELS.items():
        for lab in labels:
            if lab in low:
                return field
    return None


def _detect_seniority(job_title: str) -> str:
    low = job_title.lower()
    for level, keywords in TITLE_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return level
    return ""


def _looks_like_name(line: str) -> bool:
    s = line.strip().strip("|").strip()
    if not s or _NON_NAME_TOKENS.search(s):
        return False
    # akademische Grade entfernen
    s = re.sub(r"\b(dr|prof|dipl|mag|ing|mba|msc|bsc|ba|ma)\.?\b", "", s, flags=re.I)
    words = [w for w in re.split(r"[\s,]+", s.strip()) if w]
    if not (1 < len(words) <= 4):
        return False
    # Mehrheit der Wörter beginnt groß
    capish = sum(1 for w in words if w[:1].isupper())
    return capish >= max(2, len(words) - 1)


def _split_name(full: str) -> tuple[str, str]:
    cleaned = re.sub(r"\b(dr|prof|dipl|mag|ing|mba|msc|bsc|ba|ma)\.?\b", "",
                     full, flags=re.I).strip()
    parts = [p for p in re.split(r"\s+", cleaned) if p]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return cleaned, ""


def _find_company(lines: list[str], used: set[int]) -> tuple[str, int]:
    for i, ln in enumerate(lines):
        if i in used:
            continue
        if _has_company_hint(ln):
            # nur den firmenartigen Teil bei "|"/"," übernehmen
            for chunk in re.split(r"\s*[|·•]\s*", ln):
                if _has_company_hint(chunk):
                    return chunk.strip(" ,;|"), i
            return ln.strip(" ,;|"), i
    return "", -1


def _find_address(lines: list[str], used: set[int]) -> tuple[str, str]:
    """Findet Straße + PLZ/Ort und leitet einen groben Standort ab."""
    street_re = re.compile(
        r"\b(stra(ß|ss)e|str\.|gasse|weg|platz|allee|ring|road|rd\.|street|st\.|ave)\b",
        re.I,
    )
    plz_re = re.compile(r"\b(\d{4,5})\s+([A-Za-zÄÖÜäöüß.\-]+)")
    address_parts: list[str] = []
    location = ""
    for i, ln in enumerate(lines):
        if i in used:
            continue
        if street_re.search(ln) or plz_re.search(ln):
            address_parts.append(ln.strip(" ,;|"))
            m = plz_re.search(ln)
            if m:
                location = m.group(2).strip(" .,-")
    return ", ".join(address_parts), location


def parse_signature(block: str, fallback: LoadedEmail | None = None) -> Signature:
    """Parst einen Signaturblock in ein `Signature`-Objekt."""
    sig = Signature(raw_block=block)
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    used: set[int] = set()

    # E-Mail
    m = EMAIL_RE.search(block)
    if m:
        sig.email = m.group(0).lower()
    elif fallback and fallback.from_email:
        sig.email = fallback.from_email

    # LinkedIn (vor allgemeiner URL, damit es nicht als Website endet)
    lk = LINKEDIN_RE.search(block)
    if lk:
        sig.linkedin = lk.group(0)

    # Website (erste URL, die keine E-Mail und kein LinkedIn ist).
    # E-Mail-Adressen vorab entfernen, damit deren lokaler Teil (z. B.
    # "anna.berger") nicht faelschlich als Domain erkannt wird.
    url_search_text = EMAIL_RE.sub(" ", block)
    for um in URL_RE.finditer(url_search_text):
        cand = um.group(1).strip().rstrip(".,;")
        if "@" in cand or "linkedin.com" in cand.lower():
            continue
        if "." in cand:
            sig.website = cand
            break

    # Telefonnummern nach Label klassifizieren
    for i, ln in enumerate(lines):
        if not PHONE_RE.search(ln):
            continue
        kind = _classify_phone_line(ln) or "phone"
        nums = PHONE_RE.findall(ln)
        if not nums:
            continue
        number = nums[0].strip()
        if kind == "mobile" and not sig.mobile:
            sig.mobile = number
        elif kind == "fax" and not sig.fax:
            sig.fax = number
        elif not sig.phone:
            sig.phone = number
        used.add(i)

    # Name: erst Heuristik im Block, sonst aus dem From-Header
    name_idx = -1
    for i, ln in enumerate(lines):
        if i in used:
            continue
        if _looks_like_name(ln):
            sig.full_name = ln.strip().strip("|").strip()
            name_idx = i
            used.add(i)
            break
    if not sig.full_name and fallback and fallback.from_name:
        sig.full_name = fallback.from_name.strip()

    # Firma
    company, c_idx = _find_company(lines, used)
    if company:
        sig.company = company
        used.add(c_idx)

    # Job-Titel: bevorzugt Zeile direkt nach dem Namen, sonst Zeile mit Titel-Keyword
    title = ""
    if name_idx >= 0 and name_idx + 1 < len(lines) and (name_idx + 1) not in used:
        cand = lines[name_idx + 1]
        if not EMAIL_RE.search(cand) and not PHONE_RE.search(cand):
            title = cand.strip(" ,;|")
            used.add(name_idx + 1)
    if not title:
        for i, ln in enumerate(lines):
            if i in used:
                continue
            if _detect_seniority(ln):
                # ggf. "Titel | Abteilung" trennen
                title = re.split(r"\s*[|·•]\s*", ln)[0].strip(" ,;|")
                used.add(i)
                break
    sig.job_title = title

    # Abteilung (Zeile mit "Abteilung"/"Department"/"Team" oder Teil nach "|")
    for i, ln in enumerate(lines):
        if i in used:
            continue
        if re.search(r"\b(abteilung|department|team|bereich|unit)\b", ln, re.I):
            sig.department = ln.strip(" ,;|")
            used.add(i)
            break

    # Adresse + Standort
    address, location = _find_address(lines, used)
    sig.address = address
    sig.location = location

    # Name aufteilen + abgeleiteter Kontext
    if sig.full_name:
        sig.first_name, sig.last_name = _split_name(sig.full_name)
    sig.seniority = _detect_seniority(sig.job_title)
    sig.is_decision_maker = sig.seniority in DECISION_MAKER_LEVELS

    return sig


def extract_from_email(mail: LoadedEmail) -> Signature:
    """Komfortfunktion: Block finden + parsen für eine geladene E-Mail."""
    body = mail.text_body or ""
    block = extract_signature_block(body)
    if not block and mail.html_body:
        from .email_loader import html_to_text
        block = extract_signature_block(html_to_text(mail.html_body))
    if not block:
        # Notnagel: gesamten (bereinigten) Text als Block verwenden
        block = "\n".join(_strip_quoted(body.splitlines())).strip()
    return parse_signature(block, fallback=mail)
