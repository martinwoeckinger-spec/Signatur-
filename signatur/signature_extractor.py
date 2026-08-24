"""Findet Signaturblöcke einer E-Mail und extrahiert geschäftsrelevanten Kontext.

Robust gegen reale Mails: erkennt mehrere Signaturen pro E-Mail (z. B. in
weitergeleiteten Verläufen) und leitet Firma notfalls aus der E-Mail-Domain ab.
Relevante Felder: Name, Position, Firma, Adresse, Website, LinkedIn, E-Mail –
die E-Mail-Adresse ist der primäre Schlüssel für den CRM-Abgleich.
"""
from __future__ import annotations

import re
from typing import Optional

from .confidence import score_signature
from .models import LoadedEmail, Signature

# Version des Extraktionsverfahrens – wird je Extrakt protokolliert (FA-15).
EXTRACTOR_VERSION = "rules-1.1"

# --- Muster -----------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(
    r"\b((?:https?://)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+(?:/[^\s|<>]*)?)",
)
PHONE_RE = re.compile(r"(?<![\w@])(\+?\(?\d[\d\s().\-/]{5,}\d)")
LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|company|pub)/[^\s|<>,)]+", re.I
)
# E-Mail-Adressen, die nicht zu Personen gehoeren (Inline-Bilder etc.)
_EMAIL_NOISE = re.compile(r"^(image\d|cid|mm|emns|noreply|no-reply|mailer)", re.I)

GREETINGS = [
    "mit freundlichen grüßen", "mit freundlichen gruessen", "freundliche grüße",
    "freundliche gruesse", "viele grüße", "viele gruesse", "beste grüße",
    "beste gruesse", "herzliche grüße", "liebe grüße", "mit besten grüßen",
    "mfg", "lg", "best regards", "kind regards", "warm regards", "best wishes",
    "regards", "cheers", "sincerely", "yours sincerely", "thanks and regards",
    "thank you", "vielen dank", "danke", "with kind regards",
]

PHONE_LABELS = {
    "phone": ["tel", "tel.", "phone", "fon", "fixed", "festnetz", "office", "büro",
              "buero", "t:", "p:", "ph:", "direct", "durchwahl"],
    "mobile": ["mobil", "mobile", "cell", "cellular", "handy", "m:", "mob", "mo:"],
    "fax": ["fax", "f:", "telefax"],
}

# Firmenrechtsformen / starke Firmenkennungen
COMPANY_HINTS = [
    "gmbh", "ag", "kg", "kgaa", "ohg", "se", "e.u.", "e.k.", "gbr", "ug", "mbh",
    "e.v.", "ev", "inc", "inc.", "llc", "ltd", "ltd.", "plc", "corp", "corporation",
    "co.", "& co", "group", "gruppe", "holding", "partners", "sarl", "s.a.",
    "b.v.", "bv", "n.v.", "srl", "oy", "limited", "technologies", "solutions",
    "systems",
]

TITLE_KEYWORDS = {
    "C-Level": [
        "ceo", "cfo", "cto", "coo", "cio", "cmo", "cdo", "geschäftsführer",
        "geschaeftsfuehrer", "geschäftsführerin", "geschäftsführende", "vorstand",
        "vorständin", "managing director", "owner", "inhaber", "inhaberin",
        "gesellschafter", "president", "präsident", "partner", "partnerin",
        "founder", "co-founder", "gründer", "mitgründer", "geschäftsleitung",
    ],
    "Leitung": [
        "head of", "head", "leiter", "leiterin", "leitung", "director", "direktor",
        "direktorin", "vp ", "vice president", "vorstandsvorsitz", "abteilungsleiter",
        "abteilungsleiterin", "teamleiter", "teamleiterin", "bereichsleiter",
        "bereichsleiterin", "prokurist", "prokuristin", "standortleiter",
        "niederlassungsleiter",
    ],
    "Management": [
        "manager", "managerin", "lead", "principal", "senior manager",
        "projektleiter", "projektleiterin", "key account", "account manager",
        "account executive", "product owner", "produktmanager", "teamlead",
        "team lead", "scrum master",
    ],
    "Fachkraft": [
        "engineer", "developer", "entwickler", "entwicklerin", "consultant",
        "berater", "beraterin", "specialist", "spezialist", "analyst", "referent",
        "referentin", "sachbearbeiter", "sachbearbeiterin", "architect", "designer",
        "scientist", "expert", "associate", "ingenieur", "ingenieurin", "techniker",
        "recruiter", "recruiting", "controller", "buchhalter", "buchhalterin",
        "assistenz", "assistent", "assistentin", "assistant", "kundenberater",
        "kundenbetreuer", "sales", "vertrieb", "marketing",
    ],
}

DECISION_MAKER_LEVELS = {"C-Level", "Leitung"}

_NON_NAME_TOKENS = re.compile(
    r"@|http|www|tel|mobil|fax|gmbh|\bag\b|\d|straße|strasse|str\.|platz|"
    r"e-mail|mail:|phone|grüße|gruesse|gruß|regards|linkedin",
    re.I,
)
_GRADE_RE = re.compile(r"\b(dr|prof|dipl|mag|ing|mba|msc|bsc|ba|ma)\.?\b", re.I)

# Adresse: Strasse + Hausnummer, PLZ + Ort, Land
# Deutsche Strassen-Suffixe sind Komposita (kein fuehrendes \b, z. B.
# "Elbchaussee"); englische Strassen-Woerter brauchen beidseitige Wortgrenzen,
# damit z. B. "ave" nicht in "Brightwave" matcht.
_STREET_RE = re.compile(
    r"(?:stra(?:ß|ss)e|str\.|gasse|weg|platz|allee|ring|chaussee|damm|ufer)\b"
    r"|\b(?:road|rd\.|street|st\.|ave|avenue|lane|boulevard|blvd)\b", re.I,
)
_HOUSENO_RE = re.compile(r"\b[A-Za-zÄÖÜäöü.\- ]{3,}\s+\d{1,4}[a-z]?\b")
_PLZ_RE = re.compile(r"\b([A-Z]{1,2}-)?(\d{4,5})\s+([A-ZÄÖÜ][\wäöüß.\-]+)")
_COUNTRY_RE = re.compile(
    r"^\s*(deutschland|germany|österreich|oesterreich|austria|schweiz|"
    r"switzerland|liechtenstein)\s*$", re.I,
)
_WEB_LABEL_RE = re.compile(r"\b(web|website|homepage|url|internet)\b\s*[:\-]?", re.I)


# --- Hilfen ------------------------------------------------------------------

def _has_company_hint(text: str) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<![a-z]){re.escape(h)}(?![a-z])", low)
               for h in COMPANY_HINTS)


def _is_greeting(line: str) -> bool:
    low = line.strip().lower().rstrip(",.!").strip()
    return low in GREETINGS or any(low.startswith(g) for g in GREETINGS)


def _classify_phone_line(line: str) -> Optional[str]:
    low = line.lower()
    for field, labels in PHONE_LABELS.items():
        if any(lab in low for lab in labels):
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
    s = _GRADE_RE.sub("", s)
    words = [w for w in re.split(r"[\s,]+", s.strip()) if w]
    if not (1 < len(words) <= 4):
        return False
    capish = sum(1 for w in words if w[:1].isupper())
    return capish >= max(2, len(words) - 1)


def _academic_title(full: str) -> str:
    """Akademische Grade aus einer Namenszeile (z. B. "Prof. Dr.")."""
    grades = _GRADE_RE.findall(full or "")
    if not grades:
        return ""
    out: list[str] = []
    for raw in re.finditer(_GRADE_RE, full or ""):
        token = raw.group(0).strip()
        if not token.endswith("."):
            token += "."
        token = token[:1].upper() + token[1:]
        if token not in out:
            out.append(token)
    return " ".join(out)


def _split_name(full: str) -> tuple[str, str]:
    cleaned = _GRADE_RE.sub("", full).strip()
    parts = [p.strip(",") for p in re.split(r"\s+", cleaned)
             if p and any(ch.isalpha() for ch in p)]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return (parts[0] if parts else cleaned), ""


def _brand_tokens(value: str) -> list[str]:
    """Markenbestandteile aus einer Domain/URL/E-Mail (z. B. 'muster-tech')."""
    if not value:
        return []
    host = value.lower().split("@")[-1]
    host = re.sub(r"^https?://", "", host).split("/")[0]
    host = re.sub(r"^www\.", "", host)
    labels = host.split(".")
    core = labels[-2] if len(labels) >= 2 else labels[0]
    return [t for t in re.split(r"[-_]", core) if len(t) >= 3]


def _choose_email(block: str, fallback: LoadedEmail | None) -> str:
    found = [e for e in EMAIL_RE.findall(block)
             if not _EMAIL_NOISE.match(e.split("@")[0])]
    lowered = [e.lower() for e in found]
    if fallback and fallback.from_email and fallback.from_email in lowered:
        return fallback.from_email
    if lowered:
        return lowered[0]
    if fallback and fallback.from_email:
        return fallback.from_email
    return ""


def _find_company(lines: list[str], used: set[int]) -> tuple[str, int]:
    for i, ln in enumerate(lines):
        if i in used:
            continue
        if _has_company_hint(ln):
            for chunk in re.split(r"\s*[|·•]\s*", ln):
                if _has_company_hint(chunk):
                    return chunk.strip(" ,;|"), i
            return ln.strip(" ,;|"), i
    return "", -1


def _find_company_by_domain(lines: list[str], used: set[int],
                            domain_source: str) -> tuple[str, int]:
    toks = _brand_tokens(domain_source)
    if not toks:
        return "", -1
    for i, ln in enumerate(lines):
        if i in used:
            continue
        low = re.sub(r"[^a-z0-9]", "", ln.lower())
        if "linkedin" in ln.lower() or EMAIL_RE.search(ln) or _STREET_RE.search(ln):
            continue
        if any(t in low for t in toks):
            return ln.strip(" ,;|"), i
    return "", -1


def _find_address(lines: list[str], used: set[int]) -> tuple[str, str, dict[str, str]]:
    """Mehrzeilige Adresse (Strasse, PLZ/Ort, Land), Standort und Bestandteile.

    Liefert zusaetzlich die strukturierten Felder Strasse, PLZ, Ort und Land
    (FA-11); eine Zeile kann mehrere davon enthalten ("Musterstr. 1, 1010 Wien").
    """
    parts: list[str] = []
    location = ""
    struct = {"street": "", "postal_code": "", "city": "", "country": ""}
    for i, ln in enumerate(lines):
        if i in used:
            continue
        is_street = bool(_STREET_RE.search(ln))
        plz = _PLZ_RE.search(ln)
        is_country = bool(_COUNTRY_RE.match(ln))
        if not (is_street or plz or is_country):
            continue
        parts.append(ln.strip(" ,;|"))
        used.add(i)
        if plz:
            location = plz.group(3).strip(" .,-")
            if not struct["postal_code"]:
                struct["postal_code"] = ((plz.group(1) or "") + plz.group(2)).strip()
                struct["city"] = location
        if is_street and not struct["street"]:
            for chunk in re.split(r"\s*[,|]\s*", ln):
                if _STREET_RE.search(chunk) and not _PLZ_RE.search(chunk):
                    struct["street"] = chunk.strip(" ,;|")
                    break
        if is_country and not struct["country"]:
            struct["country"] = ln.strip(" ,;|")
    return ", ".join(parts), location, struct


# --- Signaturblock finden (Legacy/Einzel) ------------------------------------

def _strip_quoted(lines: list[str]) -> list[str]:
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
    if not body:
        return ""
    lines = _strip_quoted(body.splitlines())
    for i, ln in enumerate(lines):
        if ln.strip() in ("--", "-- "):
            block = "\n".join(lines[i + 1:]).strip()
            if block:
                return block
    anchor = None
    for i, ln in enumerate(lines):
        if _is_greeting(ln):
            anchor = i
    if anchor is not None:
        block = "\n".join(lines[anchor + 1:]).strip()
        if block:
            return block
    nonempty = [ln for ln in lines if ln.strip()]
    tail = "\n".join(nonempty[-8:])
    if EMAIL_RE.search(tail) or PHONE_RE.search(tail) or _has_company_hint(tail):
        return tail.strip()
    return ""


# --- Feld-Extraktion ---------------------------------------------------------

def parse_signature(block: str, fallback: LoadedEmail | None = None,
                    block_source: str = "unknown") -> Signature:
    """Parst einen Signaturblock in ein `Signature`-Objekt.

    `block_source` beschreibt, wie der Block gefunden wurde ("delimiter",
    "greeting", "tail", "header"); das fliesst in die Konfidenz ein (FA-12).
    """
    sig = Signature(raw_block=block)
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    used: set[int] = set()

    # E-Mail (beste Wahl)
    sig.email = _choose_email(block, fallback)

    # LinkedIn (vor allgemeiner URL)
    lk = LINKEDIN_RE.search(block)
    if lk:
        sig.linkedin = lk.group(0).rstrip(".,;)")

    # Website: bevorzugt mit Label, sonst erste echte URL ohne E-Mail/LinkedIn
    url_search_text = EMAIL_RE.sub(" ", block)
    for um in URL_RE.finditer(url_search_text):
        cand = um.group(1).strip().rstrip(".,;)")
        low = cand.lower()
        if "@" in cand or "linkedin.com" in low or low in ("e.u", "co"):
            continue
        if "." in cand and not cand.replace(".", "").isdigit():
            sig.website = cand
            break

    # Greeting-Zeilen markieren (nicht als Name/Titel verwenden)
    for i, ln in enumerate(lines):
        if _is_greeting(ln):
            used.add(i)

    # Telefonnummern nach Label klassifizieren
    for i, ln in enumerate(lines):
        if i in used or not PHONE_RE.search(ln):
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
        # Zeile nur "verbrauchen", wenn sie reine Telefonzeile ist
        if not _looks_like_name(re.sub(PHONE_RE, "", ln)):
            used.add(i)

    # Name: Heuristik, ggf. "Name | Position" trennen
    name_idx = -1
    for i, ln in enumerate(lines):
        if i in used:
            continue
        chunks = re.split(r"\s*[|·•–-]\s{1,}", ln)
        head = chunks[0].strip()
        if _looks_like_name(head):
            sig.full_name = head.strip("|").strip()
            name_idx = i
            used.add(i)
            if len(chunks) > 1 and _detect_seniority(chunks[1]):
                sig.job_title = chunks[1].strip(" ,;|")
            break
    if not sig.full_name and fallback and fallback.from_name:
        sig.full_name = fallback.from_name.strip()

    # Firma: Rechtsform -> Domain-Marke -> Zeile nach Name
    company, c_idx = _find_company(lines, used)
    if not company:
        company, c_idx = _find_company_by_domain(
            lines, used, sig.website or sig.email)
    if company:
        sig.company = company
        used.add(c_idx)

    # Position: bereits aus "Name | Position"? sonst Zeile nach Name / Keyword
    if not sig.job_title:
        title = ""
        if name_idx >= 0 and name_idx + 1 < len(lines) and (name_idx + 1) not in used:
            cand = lines[name_idx + 1]
            if (not EMAIL_RE.search(cand) and not PHONE_RE.search(cand)
                    and not _STREET_RE.search(cand) and cand != sig.company):
                title = re.split(r"\s*[|·•]\s*", cand)[0].strip(" ,;|")
                used.add(name_idx + 1)
        if not title:
            for i, ln in enumerate(lines):
                if i in used:
                    continue
                if _detect_seniority(ln):
                    title = re.split(r"\s*[|·•]\s*", ln)[0].strip(" ,;|")
                    used.add(i)
                    break
        sig.job_title = title

    # Abteilung
    for i, ln in enumerate(lines):
        if i in used:
            continue
        if re.search(r"\b(abteilung|department|team|bereich|unit)\b", ln, re.I):
            sig.department = ln.strip(" ,;|")
            used.add(i)
            break

    # Adresse + Standort + strukturierte Bestandteile
    sig.address, sig.location, address_parts = _find_address(lines, used)
    sig.street = address_parts["street"]
    sig.postal_code = address_parts["postal_code"]
    sig.city = address_parts["city"]
    sig.country = address_parts["country"]

    # Name aufteilen + akad. Grad + abgeleiteter Kontext
    if sig.full_name:
        sig.academic_title = _academic_title(sig.full_name)
        sig.first_name, sig.last_name = _split_name(sig.full_name)
        sig.full_name = " ".join(
            p for p in (sig.first_name, sig.last_name) if p) or sig.full_name
    sig.seniority = _detect_seniority(sig.job_title)
    sig.is_decision_maker = sig.seniority in DECISION_MAKER_LEVELS

    # Qualitaet und Herkunft der Extraktion protokollieren (FA-12, FA-15)
    sig.extractor_version = EXTRACTOR_VERSION
    sig.confidence = score_signature(sig, fallback, block_source=block_source)
    return sig


# --- Mehrere Signaturen pro E-Mail -------------------------------------------

_BOUNDARY_RE = re.compile(
    r"^\s*(-{2,}\s*(original|ursprüngliche|forwarded|weitergeleitete)|"
    r"(von|from|gesendet|sent|an|to|cc|betreff|subject|datum|date)\s*:|"
    r"(am|on)\b.*\b(schrieb|wrote)\b|"
    r"(gesendet|sent)\s+(von|from)\s+mein|_{5,})", re.I,
)


def _segments(text: str) -> list[list[str]]:
    """Teilt die Mail an Verlaufsgrenzen (Von:/From:/-----/„… schrieb:") in
    Segmente – je Segment i. d. R. eine Nachricht mit (höchstens) einer Signatur."""
    segments: list[list[str]] = []
    cur: list[str] = []
    for ln in text.splitlines():
        stripped = re.sub(r"^[ \t]*>+[ \t]?", "", ln)
        if _BOUNDARY_RE.match(stripped):
            if cur:
                segments.append(cur)
            cur = []
            continue
        cur.append(stripped.rstrip())
    if cur:
        segments.append(cur)
    return segments


def _segment_block(lines: list[str]) -> tuple[str, str]:
    """Signaturblock eines Segments plus Fundart ('delimiter'/'greeting'/'tail').

    Die Fundart geht in die Konfidenzbewertung ein: ein '-- '-Trenner ist ein
    deutlich verlaesslicheres Signal als die Tail-Heuristik (FA-12).
    """
    for i, ln in enumerate(lines):
        if ln.strip() in ("--", "-- "):
            return "\n".join(lines[i + 1:]).strip(), "delimiter"
    anchor = None
    for i, ln in enumerate(lines):
        if _is_greeting(ln):
            anchor = i
    if anchor is not None:
        return "\n".join(lines[anchor + 1:]).strip(), "greeting"
    nonempty = [ln for ln in lines if ln.strip()]
    tail = "\n".join(nonempty[-10:])
    if (EMAIL_RE.search(tail) or PHONE_RE.search(tail)
            or _has_company_hint(tail) or LINKEDIN_RE.search(tail)):
        return tail.strip(), "tail"
    return "", ""


def _sig_min(sig: Signature) -> bool:
    return bool(sig.email
                or (sig.full_name and (sig.company or sig.job_title))
                or sig.linkedin)


def _merge_into(base: Signature, extra: Signature) -> None:
    for f in ("full_name", "first_name", "last_name", "job_title", "department",
              "company", "phone", "mobile", "fax", "website", "linkedin",
              "address", "location", "seniority"):
        if not getattr(base, f) and getattr(extra, f):
            setattr(base, f, getattr(extra, f))
    base.is_decision_maker = base.is_decision_maker or extra.is_decision_maker


def _norm(v: str) -> str:
    return " ".join((v or "").lower().split())


def extract_all_signatures(mail: LoadedEmail) -> list[Signature]:
    """Findet **alle** Signaturen einer E-Mail (auch in Verläufen)."""
    text = mail.text_body or ""
    if not text and mail.html_body:
        from .email_loader import html_to_text
        text = html_to_text(mail.html_body)

    sigs: list[Signature] = []
    for segment in _segments(text):
        block, kind = _segment_block(segment)
        if not block:
            continue
        s = parse_signature(block, block_source=kind)
        # Mail-Kontext fliesst nur in die Konfidenz ein, nicht in die Feldwahl:
        # sonst wuerde die Absenderadresse jeder Signatur im Verlauf zugeordnet.
        s.confidence = score_signature(s, mail, block_source=kind)
        if _sig_min(s):
            sigs.append(s)

    # Deduplizieren (Schlüssel: E-Mail, sonst Name+Firma), Felder zusammenführen
    by_key: dict[str, Signature] = {}
    order: list[str] = []
    for s in sigs:
        key = s.email or ("nc:" + _norm(s.full_name) + "|" + _norm(s.company))
        if key in by_key:
            _merge_into(by_key[key], s)
        else:
            by_key[key] = s
            order.append(key)
    result = [by_key[k] for k in order]

    # Absenderadresse verankern (primärer CRM-Schlüssel)
    if mail.from_email and not any(s.email == mail.from_email for s in result):
        fn = _norm(mail.from_name)
        anchored = False
        for s in result:
            if not s.email and fn and _norm(s.full_name) == fn:
                s.email = mail.from_email
                anchored = True
                break
        if not anchored and not result:
            s = extract_from_email(mail)
            if _sig_min(s):
                result = [s]

    if not result:
        s = extract_from_email(mail)
        if _sig_min(s):
            result = [s]
    return result


def extract_from_email(mail: LoadedEmail) -> Signature:
    """Einzel-Signatur (Legacy/Komfort): Block finden + parsen."""
    body = mail.text_body or ""
    block = extract_signature_block(body)
    source = "greeting" if block else ""
    if not block and mail.html_body:
        from .email_loader import html_to_text
        block = extract_signature_block(html_to_text(mail.html_body))
        source = "greeting" if block else ""
    if not block:
        block = "\n".join(_strip_quoted(body.splitlines())).strip()
        source = "header"
    return parse_signature(block, fallback=mail, block_source=source or "unknown")
