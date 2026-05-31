"""Lädt E-Mails aus .eml- und .msg-Dateien in ein normalisiertes Modell."""
from __future__ import annotations

import email
import html as _html
import re
from email import policy
from email.utils import parseaddr
from pathlib import Path
from typing import Iterable

from .models import LoadedEmail

_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_BLOCK_END_RE = re.compile(r"</\s*(p|div|tr|li|h[1-6])\s*>", re.IGNORECASE)


def html_to_text(html: str) -> str:
    """Sehr einfache HTML→Text-Konvertierung (ohne externe Abhängigkeiten)."""
    if not html:
        return ""
    text = _STYLE_RE.sub(" ", html)
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    # Mehrfache Leerzeilen/Whitespace zusammenfassen, Zeilen trimmen
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def _load_eml(path: Path) -> LoadedEmail:
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    from_name, from_email = parseaddr(msg.get("From", ""))

    text_body, html_body = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and not text_body:
                text_body = part.get_content()
            elif ctype == "text/html" and not html_body:
                html_body = part.get_content()
    else:
        if msg.get_content_type() == "text/html":
            html_body = msg.get_content()
        else:
            text_body = msg.get_content()

    if not text_body and html_body:
        text_body = html_to_text(html_body)

    return LoadedEmail(
        source=str(path),
        from_name=from_name or "",
        from_email=(from_email or "").lower(),
        subject=msg.get("Subject", "") or "",
        date=msg.get("Date", "") or "",
        text_body=text_body or "",
        html_body=html_body or "",
    )


def _load_msg(path: Path) -> LoadedEmail:
    """Lädt eine Outlook-.msg-Datei. Benötigt das optionale Paket `extract-msg`."""
    try:
        import extract_msg  # type: ignore
    except ImportError as exc:  # pragma: no cover - abhängig von Umgebung
        raise RuntimeError(
            "Für .msg-Dateien wird das Paket 'extract-msg' benötigt "
            "(pip install extract-msg)."
        ) from exc

    m = extract_msg.Message(str(path))
    from_raw = m.sender or ""
    from_name, from_email = parseaddr(from_raw)
    if not from_email and "@" in from_raw:
        from_email = from_raw.strip()

    html_body = ""
    try:
        raw_html = m.htmlBody
        if isinstance(raw_html, bytes):
            raw_html = raw_html.decode("utf-8", "ignore")
        html_body = raw_html or ""
    except Exception:  # pragma: no cover
        html_body = ""

    text_body = m.body or ""
    if not text_body and html_body:
        text_body = html_to_text(html_body)

    return LoadedEmail(
        source=str(path),
        from_name=from_name or "",
        from_email=(from_email or "").lower(),
        subject=m.subject or "",
        date=str(m.date or ""),
        text_body=text_body or "",
        html_body=html_body or "",
    )


SUPPORTED_SUFFIXES = {".eml", ".msg"}


def load_email(path: str | Path) -> LoadedEmail:
    """Lädt eine einzelne .eml- oder .msg-Datei."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".eml":
        return _load_eml(p)
    if suffix == ".msg":
        return _load_msg(p)
    raise ValueError(f"Nicht unterstütztes Format: {p.suffix} ({p})")


def iter_email_files(input_dir: str | Path) -> Iterable[Path]:
    """Liefert alle unterstützten Mail-Dateien eines Verzeichnisses (sortiert)."""
    base = Path(input_dir)
    if base.is_file():
        yield base
        return
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES:
            yield p
