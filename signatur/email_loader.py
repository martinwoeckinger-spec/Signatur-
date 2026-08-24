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
    inline_images = 0
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if ctype.startswith("image/"):
                inline_images += 1
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

    headers = {k.lower(): str(v) for k, v in msg.items()}
    return LoadedEmail(
        source=str(path),
        from_name=from_name or "",
        from_email=(from_email or "").lower(),
        subject=msg.get("Subject", "") or "",
        date=msg.get("Date", "") or "",
        text_body=text_body or "",
        html_body=html_body or "",
        message_id=(msg.get("Message-ID", "") or "").strip(),
        headers=headers,
        inline_images=inline_images,
    )


def _msg_get_str(ole, prop_id: str) -> str:
    """Liest eine .msg-String-Property (Unicode bevorzugt, sonst ASCII/CP1252)."""
    for typ, dec in (("001F", "utf-16-le"), ("001E", "cp1252")):
        entry = f"__substg1.0_{prop_id}{typ}"
        if ole.exists(entry):
            return ole.openstream(entry).read().decode(dec, "ignore")
    return ""


def _msg_get_bytes(ole, prop_id: str, typ: str = "0102") -> bytes:
    entry = f"__substg1.0_{prop_id}{typ}"
    return ole.openstream(entry).read() if ole.exists(entry) else b""


def _load_msg_olefile(path: Path) -> LoadedEmail:
    """Liest eine Outlook-.msg ueber olefile (MAPI-Property-Streams)."""
    import olefile  # pure-python, installiert sauber als Wheel

    ole = olefile.OleFileIO(str(path))
    try:
        subject = _msg_get_str(ole, "0037")          # PR_SUBJECT
        body = _msg_get_str(ole, "1000")             # PR_BODY
        html_bytes = _msg_get_bytes(ole, "1013")     # PR_HTML
        headers = _msg_get_str(ole, "007D")          # PR_TRANSPORT_MESSAGE_HEADERS
        sender_name = _msg_get_str(ole, "0C1A")      # PR_SENDER_NAME
        sender_email = ""
        for pid in ("5D01", "0C1F", "5D02", "0065"):  # SMTP-Adresse bevorzugen
            val = _msg_get_str(ole, pid)
            if "@" in val:
                sender_email = val
                break
    finally:
        ole.close()

    html_body = ""
    if html_bytes:
        for dec in ("utf-8", "cp1252", "latin-1"):
            try:
                html_body = html_bytes.decode(dec)
                break
            except UnicodeDecodeError:
                continue

    from_name, from_email, date = sender_name, sender_email, ""
    header_map: dict[str, str] = {}
    message_id = ""
    if headers:
        hmsg = email.message_from_string(headers, policy=policy.default)
        date = hmsg.get("Date", "") or ""
        hn, he = parseaddr(hmsg.get("From", ""))
        if he:
            from_name, from_email = (hn or sender_name), he
        header_map = {k.lower(): str(v) for k, v in hmsg.items()}
        message_id = (hmsg.get("Message-ID", "") or "").strip()

    if not body and html_body:
        body = html_to_text(html_body)

    return LoadedEmail(
        source=str(path),
        from_name=(from_name or "").strip(),
        from_email=(from_email or "").strip().lower(),
        subject=(subject or "").strip(),
        date=date or "",
        text_body=body or "",
        html_body=html_body or "",
        message_id=message_id,
        headers=header_map,
    )


def _load_msg_extractmsg(path: Path) -> LoadedEmail:
    """Fallback ueber das optionale Paket extract-msg."""
    import extract_msg  # type: ignore

    m = extract_msg.Message(str(path))
    from_name, from_email = parseaddr(m.sender or "")
    if not from_email and "@" in (m.sender or ""):
        from_email = (m.sender or "").strip()
    raw_html = getattr(m, "htmlBody", None)
    if isinstance(raw_html, bytes):
        raw_html = raw_html.decode("utf-8", "ignore")
    html_body = raw_html or ""
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
        message_id=str(getattr(m, "messageId", "") or ""),
    )


def _load_msg(path: Path) -> LoadedEmail:
    """Laedt eine Outlook-.msg. Primaer ueber olefile, Fallback extract-msg."""
    try:
        import olefile  # noqa: F401
    except ImportError:
        olefile = None  # type: ignore
    if olefile is not None:
        return _load_msg_olefile(path)
    try:
        return _load_msg_extractmsg(path)
    except ImportError as exc:  # pragma: no cover - abhaengig von Umgebung
        raise RuntimeError(
            "Fuer .msg-Dateien wird 'olefile' (empfohlen) oder 'extract-msg' "
            "benoetigt: pip install olefile"
        ) from exc


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
