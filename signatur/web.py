"""Schlanke Web-Oberflaeche zum Vorfuehren des Signatur-/CRM-Workflows.

Reine Standardbibliothek (http.server) – keine externen Abhaengigkeiten.
Start:

    python -m signatur serve --port 8000
    # oder
    python -m signatur.web --port 8000

Funktionen:
  * Dashboard mit Kennzahlen
  * Pro-Kontakt-Karten: extrahierte Signaturfelder + Abweichungen zum CRM
  * Live-Vorschau der Hinweis-Mail (HTML)
  * Upload von .eml/.msg per Drag&Drop/Dateiauswahl
"""
from __future__ import annotations

import html
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .crm import get_client
from .models import ChangeType, ContactReconciliation, ReconciliationReport
from .notifier import build_notification
from .pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "samples"

# --- CSS / Seitenrahmen ------------------------------------------------------

_CSS = """
:root{--bg:#0f172a;--card:#ffffff;--muted:#64748b;--line:#e2e8f0;
--blue:#2563eb;--red:#dc2626;--green:#16a34a;--amber:#d97706;--ink:#0f172a}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
background:#f1f5f9;color:var(--ink)}
header{background:linear-gradient(120deg,#1e3a8a,#2563eb);color:#fff;padding:22px 28px}
header h1{margin:0;font-size:20px;letter-spacing:.2px}
header p{margin:4px 0 0;opacity:.85;font-size:13px}
.wrap{max-width:1080px;margin:0 auto;padding:24px 20px 60px}
.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:end;background:#fff;
border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:22px}
.toolbar label{display:block;font-size:12px;color:var(--muted);margin-bottom:4px}
.toolbar input,.toolbar select{padding:8px 10px;border:1px solid var(--line);
border-radius:8px;font-size:14px;min-width:200px}
.btn{background:var(--blue);color:#fff;border:0;padding:10px 16px;border-radius:8px;
font-size:14px;cursor:pointer;font-weight:600}
.btn:hover{filter:brightness(1.07)}
.btn.ghost{background:#fff;color:var(--blue);border:1px solid var(--blue)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
margin-bottom:24px}
.kpi{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi .n{font-size:28px;font-weight:700}
.kpi .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.kpi.blue .n{color:var(--blue)}.kpi.red .n{color:var(--red)}.kpi.green .n{color:var(--green)}
.contact{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px;
margin-bottom:16px}
.contact h3{margin:0 0 2px;font-size:16px}
.src{color:var(--muted);font-size:12px;margin-bottom:12px}
.badge{font-size:11px;color:#fff;padding:2px 9px;border-radius:20px;margin-left:8px;
vertical-align:middle}
.badge.new{background:var(--red)}.badge.upd{background:var(--blue)}
.badge.ok{background:var(--green)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:720px){.grid2{grid-template-columns:1fr}}
.kv{font-size:13px;line-height:1.7}
.kv b{display:inline-block;min-width:108px;color:var(--muted);font-weight:600}
table.diff{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
table.diff th{text-align:left;padding:6px 8px;background:#f8fafc;color:var(--muted);
font-weight:600}
table.diff td{padding:6px 8px;border-top:1px solid var(--line)}
.old{color:#94a3b8;text-decoration:line-through}
.newv{color:var(--ink);font-weight:600}
.signals{list-style:none;padding:0;margin:12px 0 0}
.signals li{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;
padding:8px 10px;border-radius:8px;margin-bottom:6px;font-size:13px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:6px;margin-left:6px}
.tag.dm{background:#fef3c7;color:#92400e}
.section-h{font-size:13px;font-weight:700;color:var(--muted);text-transform:uppercase;
letter-spacing:.5px;margin:0 0 8px}
.mailframe{width:100%;height:560px;border:1px solid var(--line);border-radius:12px;background:#fff}
.drop{border:2px dashed #94a3b8;border-radius:12px;padding:18px;text-align:center;
color:var(--muted);font-size:13px;background:#fff}
.empty{background:#fff;border:1px dashed var(--line);border-radius:12px;padding:40px;
text-align:center;color:var(--muted)}
.split{display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:start}
@media(max-width:900px){.split{grid-template-columns:1fr}}
"""


def _page(body: str) -> bytes:
    doc = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signatur-/CRM-Abgleich</title><style>{_CSS}</style></head>
<body><header><h1>📇 Signatur-/CRM-Abgleich</h1>
<p>E-Mail-Signaturen auslesen · Business-Kontext extrahieren · gegen CRM abgleichen · Hinweis erzeugen</p>
</header><div class="wrap">{body}</div></body></html>"""
    return doc.encode("utf-8")


def _esc(v: str) -> str:
    return html.escape(v or "")


# --- Render-Bausteine --------------------------------------------------------

def _toolbar(input_dir: str, crm: str) -> str:
    def opt(val, label):
        sel = " selected" if val == crm else ""
        return f'<option value="{val}"{sel}>{label}</option>'
    return f"""
<form class="toolbar" method="post" action="/run">
  <div><label>Eingabe-Ordner (.eml/.msg)</label>
    <input name="input_dir" value="{_esc(input_dir)}"></div>
  <div><label>CRM-Backend</label>
    <select name="crm">{opt('mock','Mock-CRM (Demo)')}{opt('sap','SAP Sales Cloud')}</select></div>
  <div><button class="btn" type="submit">▶ Abgleich starten</button></div>
</form>
<form class="toolbar" method="post" action="/upload" enctype="multipart/form-data">
  <div style="flex:1"><label>Oder Dateien hochladen</label>
    <div class="drop">📤 <input type="file" name="files" accept=".eml,.msg" multiple></div></div>
  <div><button class="btn ghost" type="submit">Hochladen &amp; abgleichen</button></div>
</form>"""


def _kpis(report: ReconciliationReport) -> str:
    s = report.to_dict()["summary"]
    return f"""<div class="cards">
<div class="kpi"><div class="n">{s['processed']}</div><div class="l">Verarbeitet</div></div>
<div class="kpi red"><div class="n">{s['new_contacts']}</div><div class="l">Neue Kontakte</div></div>
<div class="kpi blue"><div class="n">{s['with_changes']}</div><div class="l">Mit Änderungen</div></div>
<div class="kpi"><div class="n">{s['skipped']}</div><div class="l">Übersprungen</div></div>
</div>"""


_FIELD_LABEL = {"job_title": "Position/Titel", "department": "Abteilung",
                "company": "Firma", "phone": "Telefon", "mobile": "Mobil",
                "website": "Website"}


def _signature_kv(r: ContactReconciliation) -> str:
    sig = r.signature
    dm = '<span class="tag dm">Entscheider:in</span>' if sig.is_decision_maker else ""
    rows = [
        ("Name", sig.full_name), ("Position", sig.job_title + (
            f' · {sig.seniority}' if sig.seniority else '')),
        ("Firma", sig.company), ("Abteilung", sig.department),
        ("E-Mail", sig.email), ("Telefon", sig.phone), ("Mobil", sig.mobile),
        ("Website", sig.website), ("LinkedIn", sig.linkedin),
        ("Standort", sig.location), ("Adresse", sig.address),
    ]
    out = [f'<div class="section-h">Aus Signatur extrahiert {dm}</div><div class="kv">']
    for label, val in rows:
        if val:
            out.append(f"<div><b>{label}</b> {_esc(val)}</div>")
    out.append("</div>")
    return "".join(out)


def _diff_table(r: ContactReconciliation) -> str:
    diffs = [d for d in r.discrepancies
             if d.change_type in (ChangeType.FIELD_CHANGED, ChangeType.FIELD_NEW_IN_CRM)]
    if not diffs:
        if r.matched:
            return ('<div class="section-h">CRM-Abgleich</div>'
                    '<p style="color:var(--green);font-size:13px">✓ Signatur stimmt '
                    'mit CRM überein – keine Aktion nötig.</p>')
        return ""
    head = ('<div class="section-h">Abweichungen zum CRM</div>'
            '<table class="diff"><tr><th>Feld</th><th>CRM</th><th>Signatur</th></tr>')
    rows = []
    for d in diffs:
        label = _FIELD_LABEL.get(d.field, d.field)
        crm_v = (f'<span class="old">{_esc(d.crm_value)}</span>'
                 if d.crm_value else '<span style="color:#cbd5e1">— leer —</span>')
        rows.append(f'<tr><td>{label}</td><td>{crm_v}</td>'
                    f'<td class="newv">{_esc(d.signature_value)}</td></tr>')
    return head + "".join(rows) + "</table>"


def _signals(r: ContactReconciliation) -> str:
    if not r.business_signals:
        return ""
    items = "".join(f"<li>{_esc(s)}</li>" for s in r.business_signals)
    return f'<ul class="signals">{items}</ul>'


def _contact_card(r: ContactReconciliation) -> str:
    sig = r.signature
    name = sig.full_name or sig.email or Path(r.source).name
    company = f" · {_esc(sig.company)}" if sig.company else ""
    if not r.matched:
        badge = '<span class="badge new">Neuer Kontakt</span>'
    elif r.has_actionable_changes:
        badge = '<span class="badge upd">Aktualisierung</span>'
    else:
        badge = '<span class="badge ok">Aktuell</span>'
    return f"""<div class="contact">
  <h3>{_esc(name)}{company}{badge}</h3>
  <div class="src">Quelle: {_esc(Path(r.source).name)} · Match: {_esc(r.match_key or '—')}</div>
  <div class="grid2"><div>{_signature_kv(r)}</div><div>{_diff_table(r)}{_signals(r)}</div></div>
</div>"""


def _results_block(report: ReconciliationReport) -> str:
    if not report.results:
        return ('<div class="empty">Noch keine Ergebnisse. Ordner wählen oder '
                'Dateien hochladen und „Abgleich starten".</div>')
    # actionable zuerst
    ordered = sorted(report.results,
                     key=lambda r: (r.matched, not r.has_actionable_changes))
    cards = "".join(_contact_card(r) for r in ordered)
    skipped = ""
    sk = report.to_dict()["skipped"]
    if sk:
        items = "".join(f"<li>{_esc(x.get('source',''))}: {_esc(x.get('reason',''))}</li>"
                        for x in sk)
        skipped = f'<div class="section-h">Übersprungen</div><ul>{items}</ul>'
    return cards + skipped


def render_static_page(report: ReconciliationReport, draft_html: str,
                       input_dir: str, crm: str) -> bytes:
    """Statischer Dashboard-Export – Mail-Vorschau inline statt per iframe.

    Geeignet zum Verschicken/Oeffnen ohne laufenden Server.
    """
    body = [_toolbar(input_dir, crm), _kpis(report),
            '<div class="split"><div>', _results_block(report),
            '</div><div>',
            '<div class="section-h">Vorschau Hinweis-Mail</div>',
            f'<div class="mailframe" style="height:auto;padding:16px;overflow:auto">'
            f'{draft_html}</div>',
            '</div></div>']
    return _page("".join(body))


def export_static(out_path: str | Path, input_dir: str | Path = DEFAULT_INPUT,
                  crm: str = "mock") -> Path:
    """Fuehrt den Abgleich aus und schreibt eine eigenstaendige HTML-Datei."""
    client = get_client(crm)
    report = run_pipeline(input_dir, client)
    draft = build_notification(report, to=["vertrieb@firma.de"])
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(render_static_page(report, draft.html, str(input_dir), crm))
    return out


def _dashboard(report: ReconciliationReport, input_dir: str, crm: str,
               has_run: bool) -> str:
    body = [_toolbar(input_dir, crm)]
    if has_run:
        body.append(_kpis(report))
        body.append('<div class="split"><div>')
        body.append(_results_block(report))
        body.append('</div><div>')
        body.append('<div class="section-h">Vorschau Hinweis-Mail</div>')
        body.append('<iframe class="mailframe" src="/email-preview"></iframe>')
        body.append('<p style="font-size:12px;color:var(--muted)">'
                    'Wird als Gmail-Entwurf bzw. per SMTP versendet.</p>')
        body.append('</div></div>')
    else:
        body.append('<div class="empty">Bereit. Klicke „Abgleich starten" '
                    '(Standard: Ordner <code>samples</code>, Mock-CRM).</div>')
    return "".join(body)


# --- Server ------------------------------------------------------------------

class _State:
    def __init__(self, input_dir: str, crm: str) -> None:
        self.input_dir = input_dir
        self.crm = crm
        self.report = ReconciliationReport()
        self.draft_html = "<p>Noch kein Abgleich ausgeführt.</p>"
        self.has_run = False

    def run(self, input_dir: str, crm: str) -> None:
        self.input_dir, self.crm = input_dir, crm
        client = get_client(crm)
        self.report = run_pipeline(input_dir, client)
        draft = build_notification(self.report, to=["vertrieb@firma.de"])
        self.draft_html = draft.html
        self.has_run = True


def _parse_multipart(body: bytes, content_type: str) -> list[tuple[str, bytes]]:
    m = re.search(r"boundary=([^;]+)", content_type)
    if not m:
        return []
    boundary = m.group(1).strip().strip('"').encode()
    files: list[tuple[str, bytes]] = []
    for part in body.split(b"--" + boundary):
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        header_blob, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = header_blob.decode("utf-8", "replace")
        fm = re.search(r'filename="([^"]*)"', headers)
        if not fm or not fm.group(1):
            continue
        files.append((fm.group(1), content))
    return files


def make_handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # ruhiger Server
            pass

        def _send(self, payload: bytes, ctype="text/html; charset=utf-8", code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send(_page(_dashboard(state.report, state.input_dir,
                                            state.crm, state.has_run)))
            elif path == "/email-preview":
                self._send(state.draft_html.encode("utf-8"))
            elif path == "/api/result.json":
                import json
                self._send(json.dumps(state.report.to_dict(), ensure_ascii=False,
                                      indent=2).encode("utf-8"),
                           ctype="application/json; charset=utf-8")
            else:
                self._send(_page('<div class="empty">Nicht gefunden.</div>'), code=404)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(length) if length else b""

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/run":
                params = parse_qs(self._read_body().decode("utf-8"))
                input_dir = (params.get("input_dir", [str(DEFAULT_INPUT)])[0]
                             or str(DEFAULT_INPUT))
                crm = params.get("crm", ["mock"])[0]
                try:
                    state.run(input_dir, crm)
                except Exception as exc:  # noqa: BLE001
                    self._send(_page(f'<div class="empty">Fehler: {_esc(str(exc))}'
                                     '</div>'), code=500)
                    return
                self._redirect("/")
            elif path == "/upload":
                files = _parse_multipart(self._read_body(),
                                         self.headers.get("Content-Type", ""))
                if not files:
                    self._redirect("/")
                    return
                tmp = Path(tempfile.mkdtemp(prefix="signatur_upload_"))
                for name, content in files:
                    safe = Path(name).name or "mail.eml"
                    if not safe.lower().endswith((".eml", ".msg")):
                        safe += ".eml"
                    (tmp / safe).write_bytes(content)
                try:
                    state.run(str(tmp), state.crm)
                except Exception as exc:  # noqa: BLE001
                    self._send(_page(f'<div class="empty">Fehler: {_esc(str(exc))}'
                                     '</div>'), code=500)
                    return
                self._redirect("/")
            else:
                self._send(_page('<div class="empty">Nicht gefunden.</div>'), code=404)

        def _redirect(self, location: str):
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000,
          input_dir: str = str(DEFAULT_INPUT), crm: str = "mock") -> None:
    state = _State(input_dir, crm)
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    print(f"Signatur-Weboberfläche läuft auf http://{host}:{port}  "
          f"(Ordner: {input_dir}, CRM: {crm})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="signatur.web")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--crm", default="mock", choices=["mock", "sap"])
    a = ap.parse_args()
    serve(a.host, a.port, a.input, a.crm)
