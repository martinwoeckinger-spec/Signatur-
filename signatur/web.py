"""Web-Oberflaeche zum Vorfuehren des Signatur-/CRM-Workflows.

Reine Standardbibliothek (http.server) – keine externen Abhaengigkeiten.
Start:

    python -m signatur serve --port 8000
    # oder
    python -m signatur.web --port 8000

UI-Aufbau (am Desktop):
  * App-Bar mit Markenzeile
  * Linke Steuer-Sidebar: Datenquelle, CRM-Backend, Upload, Legende
  * Hauptbereich: Handlungsempfehlung (Banner) -> Kennzahlen -> Tabs
    (Empfehlungen / Alle Kontakte / Hinweis-Mail)
  * Pro-Kontakt-Karten: extrahierte Signaturfelder + klare Empfehlung
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

# --- Design-System (CSS) -----------------------------------------------------

_CSS = """
*{box-sizing:border-box}
:root{
  --bg:#f4f5f7; --surface:#ffffff; --surface-2:#f8f9fb; --surface-3:#f1f3f6;
  --border:#e4e7ec; --border-strong:#d4d8de;
  --text:#1a2233; --muted:#69707d; --faint:#9aa1ad;
  --accent:#4f46e5; --accent-d:#4338ca; --accent-soft:#eef0fe;
  --new:#e11d48; --new-soft:#fdeef1; --upd:#2563eb; --upd-soft:#eaf1fe;
  --ok:#0f9d6e; --ok-soft:#e7f6f0; --warn:#b45309; --warn-soft:#fdf3e6;
  --radius:14px; --radius-s:10px;
  --shadow:0 1px 2px rgba(16,24,40,.04),0 1px 3px rgba(16,24,40,.08);
  --shadow-lg:0 6px 24px rgba(16,24,40,.10);
  --font:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
html{font-size:15px}
body{margin:0;font-family:var(--font);background:var(--bg);color:var(--text);
  line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}
h1,h2,h3,h4{margin:0;font-weight:650;letter-spacing:-.01em}
.muted{color:var(--muted)}

/* App-Bar */
.appbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;
  justify-content:space-between;gap:16px;height:60px;padding:0 24px;
  background:rgba(255,255,255,.85);backdrop-filter:saturate(1.4) blur(8px);
  border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:11px;font-weight:700;font-size:16px}
.brand .logo{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;
  background:linear-gradient(135deg,#6366f1,#4338ca);color:#fff;font-size:16px;
  box-shadow:var(--shadow)}
.brand small{display:block;font-weight:500;color:var(--muted);font-size:11.5px;
  letter-spacing:.02em;margin-top:-2px}
.appbar .env{font-size:12px;color:var(--muted);background:var(--surface-3);
  border:1px solid var(--border);padding:5px 11px;border-radius:20px}

/* Layout */
.layout{max-width:1240px;margin:0 auto;padding:24px;display:grid;
  grid-template-columns:286px 1fr;gap:24px;align-items:start}
@media(max-width:940px){.layout{grid-template-columns:1fr;padding:16px}}

/* Sidebar */
.sidebar{position:sticky;top:84px;display:flex;flex-direction:column;gap:16px}
@media(max-width:940px){.sidebar{position:static}}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow)}
.panel-h{padding:14px 16px 0;font-size:11px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;color:var(--faint)}
.panel-b{padding:14px 16px 16px;display:flex;flex-direction:column;gap:12px}
.field label{display:block;font-size:12px;color:var(--muted);margin-bottom:5px;font-weight:550}
.field input,.field select{width:100%;padding:9px 11px;border:1px solid var(--border-strong);
  border-radius:var(--radius-s);font-size:13.5px;font-family:inherit;background:var(--surface);
  color:var(--text);transition:border .15s,box-shadow .15s}
.field input:focus,.field select:focus{outline:none;border-color:var(--accent);
  box-shadow:0 0 0 3px var(--accent-soft)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;width:100%;
  padding:10px 14px;border:0;border-radius:var(--radius-s);font-size:14px;font-weight:600;
  font-family:inherit;cursor:pointer;transition:filter .15s,background .15s}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:var(--accent-d)}
.btn-ghost{background:var(--surface);color:var(--accent);border:1px solid var(--border-strong)}
.btn-ghost:hover{background:var(--accent-soft)}
.dropzone{border:1.5px dashed var(--border-strong);border-radius:var(--radius-s);
  padding:16px;text-align:center;color:var(--muted);font-size:12.5px;background:var(--surface-2);
  cursor:pointer;transition:border .15s,background .15s}
.dropzone:hover{border-color:var(--accent);background:var(--accent-soft)}
.dropzone input{display:none}
.dropzone .ic{font-size:20px;display:block;margin-bottom:4px}
.dropname{font-size:12px;color:var(--accent);margin-top:2px;font-weight:600}
.legend{display:flex;flex-direction:column;gap:8px;font-size:12.5px;color:var(--muted)}
.legend .row{display:flex;align-items:center;gap:9px}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
.dot.new{background:var(--new)}.dot.upd{background:var(--upd)}.dot.ok{background:var(--ok)}

/* Content */
.content{display:flex;flex-direction:column;gap:18px;min-width:0}
.reco{display:flex;align-items:center;gap:14px;padding:16px 18px;border-radius:var(--radius);
  background:linear-gradient(120deg,#eef0fe,#f6f4ff);border:1px solid #e0e3fb}
.reco.calm{background:var(--ok-soft);border-color:#cdeede}
.reco .emoji{font-size:24px;flex:none}
.reco h2{font-size:16px;margin-bottom:2px}
.reco p{margin:0;font-size:13.5px;color:var(--muted)}

.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:620px){.kpis{grid-template-columns:repeat(2,1fr)}}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 16px;box-shadow:var(--shadow)}
.kpi .n{font-size:26px;font-weight:750;letter-spacing:-.02em}
.kpi .l{font-size:11.5px;color:var(--muted);font-weight:600;margin-top:2px}
.kpi.new .n{color:var(--new)}.kpi.upd .n{color:var(--upd)}.kpi.ok .n{color:var(--ok)}

/* Tabs */
.tabs{display:inline-flex;gap:4px;padding:4px;background:var(--surface-3);
  border:1px solid var(--border);border-radius:11px;align-self:flex-start}
.tab{border:0;background:transparent;padding:8px 15px;border-radius:8px;font-size:13.5px;
  font-weight:600;color:var(--muted);cursor:pointer;font-family:inherit;display:flex;
  align-items:center;gap:7px}
.tab:hover{color:var(--text)}
.tab.active{background:var(--surface);color:var(--text);box-shadow:var(--shadow)}
.tab .cnt{font-size:11px;background:var(--surface-3);color:var(--muted);padding:1px 7px;
  border-radius:9px;font-weight:700}
.tab.active .cnt{background:var(--accent-soft);color:var(--accent-d)}

/* Gruppen */
.group{margin-top:4px}
.group-h{display:flex;align-items:center;gap:9px;margin:18px 2px 10px}
.group-h .gdot{width:8px;height:8px;border-radius:50%}
.group-h.new .gdot{background:var(--new)}.group-h.upd .gdot{background:var(--upd)}
.group-h.ok .gdot{background:var(--ok)}
.group-h h3{font-size:13.5px}
.group-h .gc{font-size:11.5px;color:var(--muted);background:var(--surface-3);
  border:1px solid var(--border);padding:1px 8px;border-radius:9px;font-weight:700}
details.group summary{list-style:none;cursor:pointer}
details.group summary::-webkit-details-marker{display:none}

/* Kontakt-Karte */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:16px 18px;margin-bottom:12px}
.card-top{display:flex;align-items:center;gap:13px;margin-bottom:14px}
.avatar{width:42px;height:42px;border-radius:11px;flex:none;display:grid;place-items:center;
  font-weight:700;font-size:15px;color:#fff}
.avatar.new{background:linear-gradient(135deg,#fb7185,#e11d48)}
.avatar.upd{background:linear-gradient(135deg,#60a5fa,#2563eb)}
.avatar.ok{background:linear-gradient(135deg,#34d399,#0f9d6e)}
.card-id{flex:1;min-width:0}
.card-id h4{font-size:15px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.card-id .sub{font-size:12.5px;color:var(--muted);margin-top:1px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.pill{font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;flex:none}
.pill.new{background:var(--new-soft);color:var(--new)}
.pill.upd{background:var(--upd-soft);color:var(--upd)}
.pill.ok{background:var(--ok-soft);color:var(--ok)}
.tag{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;
  background:var(--warn-soft);color:var(--warn)}

.card-body{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:20px}
@media(max-width:680px){.card-body{grid-template-columns:1fr}}
.block-h{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  color:var(--faint);margin-bottom:9px}
.kv{display:grid;grid-template-columns:84px 1fr;gap:4px 10px;font-size:13px}
.kv dt{color:var(--muted)}
.kv dd{margin:0;overflow:hidden;text-overflow:ellipsis}

.reco-box{border:1px solid var(--border);border-left:3px solid var(--accent);
  border-radius:var(--radius-s);background:var(--surface-2);padding:12px 14px}
.reco-box.new{border-left-color:var(--new)}
.reco-box.upd{border-left-color:var(--upd)}
.reco-box.ok{border-left-color:var(--ok)}
.reco-box .lead{font-size:13px;font-weight:650;margin-bottom:9px;display:flex;
  align-items:center;gap:7px}
table.diff{border-collapse:collapse;width:100%;font-size:12.5px}
table.diff th{text-align:left;padding:5px 8px;color:var(--faint);font-weight:600;
  border-bottom:1px solid var(--border)}
table.diff td{padding:6px 8px;border-bottom:1px solid var(--surface-3);vertical-align:top}
table.diff tr:last-child td{border-bottom:0}
.old{color:var(--faint);text-decoration:line-through}
.arrow{color:var(--faint);padding:0 4px}
.newv{color:var(--text);font-weight:650}
.chips{display:flex;flex-direction:column;gap:6px;margin-top:10px}
.chip{font-size:12.5px;background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:7px 10px;color:var(--text)}
.ok-note{font-size:13px;color:var(--ok);display:flex;align-items:center;gap:7px}

/* Mail-Vorschau */
.mailwrap{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);overflow:hidden}
.mailbar{display:flex;align-items:center;gap:8px;padding:11px 16px;border-bottom:1px solid var(--border);
  background:var(--surface-2);font-size:12.5px;color:var(--muted)}
.mailbar .dotrow{display:flex;gap:6px}
.mailbar .d{width:10px;height:10px;border-radius:50%}
.mailbar .d1{background:#ff6058}.mailbar .d2{background:#ffbd2e}.mailbar .d3{background:#28ca42}
.mailbody{padding:20px;max-height:620px;overflow:auto}

/* Empty / Skip */
.empty{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:40px 28px;text-align:center}
.empty .big{font-size:34px;margin-bottom:8px}
.empty h2{font-size:18px;margin-bottom:6px}
.empty p{color:var(--muted);margin:0 auto 18px;max-width:440px;font-size:14px}
.steps{display:inline-flex;gap:10px;flex-wrap:wrap;justify-content:center}
.step{display:flex;align-items:center;gap:8px;font-size:13px;background:var(--surface-2);
  border:1px solid var(--border);border-radius:20px;padding:7px 14px}
.step .num{width:20px;height:20px;border-radius:50%;background:var(--accent);color:#fff;
  font-size:11px;font-weight:700;display:grid;place-items:center}
.skip{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:12px 16px;font-size:12.5px;color:var(--muted)}
.note{font-size:12px;color:var(--faint);margin-top:8px}
[hidden]{display:none!important}
"""

_JS = """
function sigTab(name){
  document.querySelectorAll('[data-pane]').forEach(function(p){
    p.hidden = p.getAttribute('data-pane')!==name;});
  document.querySelectorAll('.tab').forEach(function(b){
    b.classList.toggle('active', b.getAttribute('data-target')===name);});
}
function sigFile(inp){
  var n = inp.files.length;
  var el = document.getElementById('dropname');
  if(el) el.textContent = n? (n+' Datei(en) gewählt: '+
    Array.from(inp.files).map(function(f){return f.name}).join(', ')) : '';
}
"""


def _page(body: str, *, with_js: bool = True) -> bytes:
    script = f"<script>{_JS}</script>" if with_js else ""
    doc = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signatur-Sync · CRM-Abgleich</title><style>{_CSS}</style></head>
<body>
<div class="appbar">
  <div class="brand"><span class="logo">📇</span>
    <span>Signatur-Sync<small>E-Mail-Signaturen ↔ CRM</small></span></div>
  <div class="env">Demo · Mock-CRM</div>
</div>
{body}
{script}
</body></html>"""
    return doc.encode("utf-8")


def _esc(v: str) -> str:
    return html.escape(v or "")


# --- Sidebar / Steuerung -----------------------------------------------------

def _sidebar(input_dir: str, crm: str, interactive: bool) -> str:
    if not interactive:
        controls = (
            '<div class="panel-b"><p class="muted" style="font-size:12.5px;margin:0">'
            'Statischer Export. Interaktiv mit '
            '<code>python -m signatur serve</code>.</p></div>')
        upload = ""
    else:
        def opt(val, label):
            sel = " selected" if val == crm else ""
            return f'<option value="{val}"{sel}>{label}</option>'
        controls = f"""<div class="panel-b">
  <form method="post" action="/run" style="display:flex;flex-direction:column;gap:12px">
    <div class="field"><label>Eingabe-Ordner (.eml/.msg)</label>
      <input name="input_dir" value="{_esc(input_dir)}"></div>
    <div class="field"><label>CRM-Backend</label>
      <select name="crm">{opt('mock','Mock-CRM (Demo)')}{opt('sap','SAP Sales Cloud')}</select></div>
    <button class="btn btn-primary" type="submit">▶&nbsp; Abgleich starten</button>
  </form></div>"""
        upload = """
<div class="panel"><div class="panel-h">Dateien hochladen</div><div class="panel-b">
  <form method="post" action="/upload" enctype="multipart/form-data"
        style="display:flex;flex-direction:column;gap:10px">
    <label class="dropzone"><span class="ic">📤</span>.eml / .msg hierher wählen
      <input type="file" name="files" accept=".eml,.msg" multiple
             onchange="sigFile(this)"></label>
    <div id="dropname" class="dropname"></div>
    <button class="btn btn-ghost" type="submit">Hochladen &amp; abgleichen</button>
  </form></div></div>"""

    return f"""<aside class="sidebar">
<div class="panel"><div class="panel-h">Datenquelle</div>{controls}</div>
{upload}
<div class="panel"><div class="panel-h">Legende</div><div class="panel-b">
  <div class="legend">
    <div class="row"><span class="dot new"></span> Neu im CRM anlegen (Lead)</div>
    <div class="row"><span class="dot upd"></span> Im CRM aktualisieren</div>
    <div class="row"><span class="dot ok"></span> Aktuell – keine Aktion</div>
  </div></div></div>
</aside>"""


# --- Kennzahlen & Empfehlungs-Banner -----------------------------------------

def _split_groups(report: ReconciliationReport):
    new = [r for r in report.results if not r.matched]
    upd = [r for r in report.results if r.matched and r.has_actionable_changes]
    ok = [r for r in report.results if r.matched and not r.has_actionable_changes]
    return new, upd, ok


def _reco_banner(new, upd, ok) -> str:
    todo = len(new) + len(upd)
    if todo == 0:
        return ('<div class="reco calm"><span class="emoji">✅</span><div>'
                '<h2>Alles aktuell</h2><p>Keine Abweichungen gefunden – das CRM '
                'ist auf dem neuesten Stand.</p></div></div>')
    parts = []
    if new:
        parts.append(f"<b>{len(new)}</b> neue·n Kontakt(e) anlegen")
    if upd:
        parts.append(f"<b>{len(upd)}</b> Kontakt(e) aktualisieren")
    return (f'<div class="reco"><span class="emoji">🎯</span><div>'
            f'<h2>Handlungsbedarf: {todo} Empfehlung(en)</h2>'
            f'<p>{" · ".join(parts)}. Details unten unter „Empfehlungen".</p></div></div>')


def _kpis(report, new, upd, ok) -> str:
    return f"""<div class="kpis">
<div class="kpi"><div class="n">{len(report.results)}</div><div class="l">VERARBEITET</div></div>
<div class="kpi new"><div class="n">{len(new)}</div><div class="l">NEU ANLEGEN</div></div>
<div class="kpi upd"><div class="n">{len(upd)}</div><div class="l">AKTUALISIEREN</div></div>
<div class="kpi ok"><div class="n">{len(ok)}</div><div class="l">AKTUELL</div></div>
</div>"""


# --- Kontakt-Karte -----------------------------------------------------------

_FIELD_LABEL = {"job_title": "Position", "department": "Abteilung",
                "company": "Firma", "phone": "Telefon", "mobile": "Mobil",
                "website": "Website"}


def _tone(r: ContactReconciliation) -> str:
    if not r.matched:
        return "new"
    return "upd" if r.has_actionable_changes else "ok"


def _initials(r: ContactReconciliation) -> str:
    sig = r.signature
    parts = [p for p in (sig.first_name, sig.last_name) if p]
    if not parts and sig.full_name:
        parts = sig.full_name.split()
    if parts:
        a = parts[0][:1]
        b = parts[-1][:1] if len(parts) > 1 else ""
        return (a + b).upper()
    return (sig.email[:2].upper() if sig.email else "–")


def _kv(label: str, value: str) -> str:
    if not value:
        return ""
    return f"<dt>{label}</dt><dd>{_esc(value)}</dd>"


def _signature_block(r: ContactReconciliation) -> str:
    s = r.signature
    role = s.job_title + (f" · {s.seniority}" if s.seniority else "")
    rows = "".join([
        _kv("Name", s.full_name), _kv("Position", role), _kv("Firma", s.company),
        _kv("Abteilung", s.department), _kv("E-Mail", s.email),
        _kv("Telefon", s.phone), _kv("Mobil", s.mobile), _kv("Website", s.website),
        _kv("LinkedIn", s.linkedin), _kv("Standort", s.location),
    ])
    return (f'<div><div class="block-h">Aus Signatur extrahiert</div>'
            f'<dl class="kv">{rows}</dl></div>')


def _diffs(r: ContactReconciliation):
    return [d for d in r.discrepancies
            if d.change_type in (ChangeType.FIELD_CHANGED, ChangeType.FIELD_NEW_IN_CRM)]


def _reco_block(r: ContactReconciliation) -> str:
    tone = _tone(r)
    signals = "".join(f'<div class="chip">{_esc(s)}</div>' for s in r.business_signals)
    chips = f'<div class="chips">{signals}</div>' if signals else ""

    if tone == "ok":
        return ('<div class="reco-box ok"><div class="ok-note">✓ Signatur stimmt '
                'mit dem CRM überein – keine Aktion nötig.</div>'
                f'{chips}</div>')

    diffs = _diffs(r)
    rows = []
    for d in diffs:
        label = _FIELD_LABEL.get(d.field, d.field)
        if d.crm_value:
            cell = (f'<span class="old">{_esc(d.crm_value)}</span>'
                    f'<span class="arrow">→</span>'
                    f'<span class="newv">{_esc(d.signature_value)}</span>')
        else:
            cell = (f'<span class="muted">leer</span><span class="arrow">→</span>'
                    f'<span class="newv">{_esc(d.signature_value)}</span>')
        rows.append(f'<tr><td>{label}</td><td>{cell}</td></tr>')
    table = (f'<table class="diff"><tr><th>Feld</th><th>CRM → Signatur</th></tr>'
             f'{"".join(rows)}</table>') if rows else ""

    lead = ("🆕 Empfehlung: als neuen Kontakt/Lead anlegen" if tone == "new"
            else "✏️ Empfehlung: Stammdaten im CRM aktualisieren")
    return (f'<div class="reco-box {tone}"><div class="lead">{lead}</div>'
            f'{table}{chips}</div>')


def _card(r: ContactReconciliation) -> str:
    tone = _tone(r)
    sig = r.signature
    name = sig.full_name or sig.email or Path(r.source).name
    sub_bits = [b for b in (sig.job_title, sig.company) if b]
    sub = " · ".join(sub_bits) or Path(r.source).name
    pill = {"new": "Neuer Kontakt", "upd": "Aktualisierung", "ok": "Aktuell"}[tone]
    dm = '<span class="tag">Entscheider:in</span>' if sig.is_decision_maker else ""
    return f"""<div class="card">
  <div class="card-top">
    <div class="avatar {tone}">{_esc(_initials(r))}</div>
    <div class="card-id">
      <h4>{_esc(name)} {dm}</h4>
      <div class="sub">{_esc(sub)} · {_esc(Path(r.source).name)}</div>
    </div>
    <span class="pill {tone}">{pill}</span>
  </div>
  <div class="card-body">{_signature_block(r)}{_reco_block(r)}</div>
</div>"""


def _group(title: str, items, tone: str, *, collapsed: bool = False) -> str:
    if not items:
        return ""
    cards = "".join(_card(r) for r in items)
    head = (f'<div class="group-h {tone}"><span class="gdot"></span>'
            f'<h3>{title}</h3><span class="gc">{len(items)}</span></div>')
    if collapsed:
        return (f'<details class="group"><summary>{head}</summary>{cards}</details>')
    return f'<div class="group">{head}{cards}</div>'


# --- Tabs & Hauptbereich -----------------------------------------------------

def _mail_pane(draft_html: str) -> str:
    return f"""<div class="mailwrap">
  <div class="mailbar"><span class="dotrow"><span class="d d1"></span>
    <span class="d d2"></span><span class="d d3"></span></span>
    Vorschau · wird als Gmail-Entwurf bzw. per SMTP versendet</div>
  <div class="mailbody">{draft_html}</div></div>"""


def _results(report: ReconciliationReport, draft_html: str) -> str:
    new, upd, ok = _split_groups(report)
    reco_pane = (_group("Neu im CRM anlegen", new, "new")
                 + _group("Im CRM aktualisieren", upd, "upd"))
    if not reco_pane:
        reco_pane = ('<div class="skip">Keine offenen Empfehlungen – alle '
                     'abgeglichenen Kontakte sind aktuell.</div>')
    all_pane = (_group("Neu im CRM anlegen", new, "new")
                + _group("Im CRM aktualisieren", upd, "upd")
                + _group("Aktuell – keine Aktion", ok, "ok", collapsed=True))

    skipped = ""
    sk = report.to_dict()["skipped"]
    if sk:
        items = "".join(f"<li>{_esc(x.get('source',''))}: {_esc(x.get('reason',''))}</li>"
                        for x in sk)
        skipped = f'<div class="skip">Übersprungen:<ul>{items}</ul></div>'

    todo = len(new) + len(upd)
    return f"""
{_reco_banner(new, upd, ok)}
{_kpis(report, new, upd, ok)}
<nav class="tabs">
  <button class="tab active" data-target="reco" onclick="sigTab('reco')">
    🎯 Empfehlungen <span class="cnt">{todo}</span></button>
  <button class="tab" data-target="all" onclick="sigTab('all')">
    👥 Alle Kontakte <span class="cnt">{len(report.results)}</span></button>
  <button class="tab" data-target="mail" onclick="sigTab('mail')">✉️ Hinweis-Mail</button>
</nav>
<div data-pane="reco">{reco_pane}{skipped}</div>
<div data-pane="all" hidden>{all_pane}{skipped}</div>
<div data-pane="mail" hidden>{_mail_pane(draft_html)}</div>
"""


def _empty() -> str:
    return """<div class="empty">
  <div class="big">📭</div>
  <h2>Bereit für den Abgleich</h2>
  <p>Wähle links einen Ordner mit E-Mails oder lade <code>.eml</code>/<code>.msg</code>
     hoch. Der Workflow liest die Signaturen, gleicht sie mit dem CRM ab und
     schlägt konkrete Aktionen vor.</p>
  <div class="steps">
    <span class="step"><span class="num">1</span> Quelle wählen</span>
    <span class="step"><span class="num">2</span> Abgleich starten</span>
    <span class="step"><span class="num">3</span> Empfehlungen prüfen</span>
  </div></div>"""


def _dashboard(report, input_dir, crm, has_run, draft_html, interactive=True) -> str:
    main = _results(report, draft_html) if has_run else _empty()
    return (f'<div class="layout">{_sidebar(input_dir, crm, interactive)}'
            f'<main class="content">{main}</main></div>')


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


def render_static_page(report: ReconciliationReport, draft_html: str,
                       input_dir: str, crm: str) -> bytes:
    """Statischer Dashboard-Export (eigenstaendige HTML-Datei, JS fuer Tabs)."""
    return _page(_dashboard(report, input_dir, crm, True, draft_html,
                            interactive=False))


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
                                            state.crm, state.has_run,
                                            state.draft_html)))
            elif path == "/email-preview":
                self._send(state.draft_html.encode("utf-8"))
            elif path == "/api/result.json":
                import json
                self._send(json.dumps(state.report.to_dict(), ensure_ascii=False,
                                      indent=2).encode("utf-8"),
                           ctype="application/json; charset=utf-8")
            else:
                self._send(_page('<div class="layout"><main class="content">'
                                 '<div class="empty"><h2>Nicht gefunden</h2></div>'
                                 '</main></div>'), code=404)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(length) if length else b""

        def _error_page(self, exc: Exception):
            self._send(_page('<div class="layout"><main class="content">'
                             f'<div class="empty"><div class="big">⚠️</div>'
                             f'<h2>Fehler beim Abgleich</h2><p>{_esc(str(exc))}</p>'
                             '</div></main></div>'), code=500)

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
                    self._error_page(exc)
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
                    self._error_page(exc)
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
