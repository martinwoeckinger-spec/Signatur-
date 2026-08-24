"""Review-UI für das Datenteam (FA-40 … FA-47).

Standardbibliothek-Server wie die Demo-Oberfläche. Aufbau:

    /            Arbeitsliste offener Fälle mit Filtern und Bulk-Aktionen
    /case?id=…   Fall im Detail: CRM-Wert ↔ Vorschlag, feldweise entscheidbar
    /kpi         Kennzahlen (Kapitel 11)
    /api/cases.json, /api/kpi.json

Start:  python -m signatur review --port 8010

Hinweis zur Authentifizierung: NFA-06 (SSO/IdP, rollenbasiert) ist in dieser
Stufe **nicht** umgesetzt — der Bearbeiter wird im Formular geführt. Vor dem
Produktivbetrieb ist die UI hinter den IdP zu hängen (siehe Abdeckungsdokument).
"""
from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .config import CheckerConfig, get_config
from .crm import get_client
from .checker import run_checker
from .kpi import compute_kpis
from .models import Decision, DiffType
from .review import ReviewService
from .store import CheckerStore
from .web import _CSS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "samples"

_EXTRA_CSS = """
.wrap{max-width:1180px;margin:0 auto;padding:24px;display:flex;
  flex-direction:column;gap:18px}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:end}
.bar .field{min-width:150px}
.tbl{width:100%;border-collapse:collapse;background:var(--surface);
  border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.tbl th,.tbl td{padding:10px 12px;text-align:left;font-size:13.5px;
  border-bottom:1px solid var(--border);vertical-align:top}
.tbl th{background:var(--surface-3);font-size:11.5px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--faint)}
.tbl tr:last-child td{border-bottom:0}
.pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11.5px;
  font-weight:650;border:1px solid var(--border-strong);background:var(--surface-3)}
.pill.upd{background:var(--upd-soft);color:var(--upd);border-color:#cfe0fd}
.pill.add{background:var(--ok-soft);color:var(--ok);border-color:#cdeede}
.pill.warn{background:var(--warn-soft);color:var(--warn);border-color:#f3e0c0}
.pill.new{background:var(--new-soft);color:var(--new);border-color:#f8d6de}
.prio{font-variant-numeric:tabular-nums;font-weight:700}
.diff{display:grid;grid-template-columns:150px 1fr 1fr 250px;gap:12px;
  padding:12px;border-bottom:1px solid var(--border);align-items:start}
@media(max-width:860px){.diff{grid-template-columns:1fr}}
.old{color:var(--muted);text-decoration:line-through;word-break:break-word}
.new-val{color:var(--upd);font-weight:650;word-break:break-word}
.choice{display:flex;flex-direction:column;gap:6px;font-size:13px}
.choice label{display:flex;align-items:center;gap:7px}
.choice input[type=text]{width:100%;padding:6px 9px;border:1px solid var(--border-strong);
  border-radius:8px;font-size:13px;font-family:inherit}
.raw{white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12.5px;background:var(--surface-2);border:1px solid var(--border);
  border-radius:var(--radius-s);padding:12px;color:var(--muted);max-height:320px;
  overflow:auto}
.flash{padding:12px 16px;border-radius:var(--radius);font-size:13.5px}
.flash.ok{background:var(--ok-soft);border:1px solid #cdeede;color:#0b6b4d}
.flash.err{background:var(--new-soft);border:1px solid #f8d6de;color:#9f1239}
.actions{display:flex;gap:10px;flex-wrap:wrap}
.actions .btn{width:auto;padding:9px 16px}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.meta .kv{background:var(--surface-2);border:1px solid var(--border);
  border-radius:var(--radius-s);padding:9px 11px}
.meta .kv b{display:block;font-size:11px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--faint);font-weight:700;margin-bottom:2px}
"""


def _esc(value: str) -> str:
    return html.escape(str(value or ""))


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} · Signature Checker</title>
<style>{_CSS}{_EXTRA_CSS}</style></head><body>
<div class="appbar">
  <div class="brand"><span class="logo">✅</span>
    <span>Signature Checker<small>Review-Arbeitsplatz Datenteam</small></span></div>
  <div class="env"><a href="/">Arbeitsliste</a> · <a href="/kpi">Kennzahlen</a></div>
</div>
{body}
</body></html>""".encode("utf-8")


def _flash(params: dict[str, list[str]]) -> str:
    if msg := params.get("ok", [""])[0]:
        return f'<div class="flash ok">{_esc(msg)}</div>'
    if msg := params.get("err", [""])[0]:
        return f'<div class="flash err">{_esc(msg)}</div>'
    return ""


_TYP_PILL = {"Update": "upd", "Ergänzung": "add", "Klärung": "warn",
             "Unbekannt": "new"}


class ReviewApp:
    """Zustand des Review-Servers (Store, CRM-Verbindung, Konfiguration)."""

    def __init__(self, store: CheckerStore, crm_name: str, config: CheckerConfig,
                 input_dir: str, actor: str = "") -> None:
        self.store = store
        self.crm_name = crm_name
        self.config = config
        self.input_dir = input_dir
        self.actor = actor
        self.crm = get_client(crm_name)
        self.service = ReviewService(store, self.crm, config)

    # -- Arbeitsliste (FA-40) ------------------------------------------------
    def worklist(self, params: dict[str, list[str]]) -> bytes:
        def p(name: str, default: str = "") -> str:
            return params.get(name, [default])[0]

        status = p("status", "offen")
        typ, feld, org, sort = p("typ"), p("feld"), p("org"), p("sort", "prio")
        min_prio = p("prio")
        min_konf = p("konfidenz")
        max_alter = p("alter")
        cases = self.service.list_cases(
            status=status or None, typ=typ or None, feld=feld or None,
            organisation=org or None, sort=sort,
            min_prio=int(min_prio) if min_prio.isdigit() else None,
            min_konfidenz=float(min_konf) if min_konf else None,
            max_alter_tage=float(max_alter) if max_alter else None,
        )

        def sel(name: str, label: str, options: list[tuple[str, str]],
                current: str) -> str:
            opts = "".join(
                f'<option value="{_esc(v)}"'
                f'{" selected" if v == current else ""}>{_esc(t)}</option>'
                for v, t in options)
            return (f'<div class="field"><label>{_esc(label)}</label>'
                    f'<select name="{name}">{opts}</select></div>')

        felder = sorted({d.feld for c in self.store.cases() for d in c.diffs})
        filterbar = f"""<form method="get" action="/" class="panel">
<div class="panel-b"><div class="bar">
{sel("status", "Status", [("offen", "offen (alle aktiven)"), ("", "alle"),
     ("erledigt", "erledigt"), ("abgelehnt", "abgelehnt"),
     ("in Bearbeitung", "in Bearbeitung"), ("Klärung", "Klärung")], status)}
{sel("typ", "Typ", [("", "alle"), ("Update", "Update"), ("Ergänzung", "Ergänzung"),
     ("Klärung", "Klärung"), ("Unbekannt", "Unbekannt")], typ)}
{sel("feld", "Feldtyp", [("", "alle")] +
     [(f, self.config.label_for(f)) for f in felder], feld)}
<div class="field"><label>Organisation</label>
  <input name="org" value="{_esc(org)}" placeholder="enthält …"></div>
<div class="field"><label>Prio ≥</label>
  <input name="prio" value="{_esc(min_prio)}" placeholder="z. B. 30"></div>
<div class="field"><label>Konfidenz ≥</label>
  <input name="konfidenz" value="{_esc(min_konf)}" placeholder="0.8"></div>
<div class="field"><label>Alter ≤ (Tage)</label>
  <input name="alter" value="{_esc(max_alter)}" placeholder="7"></div>
{sel("sort", "Sortierung", [("prio", "Priorität"), ("alter", "Alter"),
     ("konfidenz", "Konfidenz"), ("organisation", "Organisation")], sort)}
<div class="field"><button class="btn btn-primary" type="submit">Filtern</button></div>
</div></div></form>"""

        zeilen = []
        for case in cases:
            felder_txt = ", ".join(
                f"{self.config.label_for(d.feld)}" for d in case.offene_diffs) or "—"
            pill = _TYP_PILL.get(case.typ.value, "")
            zeilen.append(f"""<tr>
<td><input type="checkbox" name="case_id" value="{_esc(case.id)}"></td>
<td class="prio">{case.prio}</td>
<td><span class="pill {pill}">{_esc(case.typ.value)}</span></td>
<td><a href="/case?id={_esc(case.id)}"><b>{_esc(case.kontakt_name or case.absender_email or '—')}</b></a>
    <div class="muted">{_esc(case.absender_email)}</div></td>
<td>{_esc(case.organisation or '—')}</td>
<td>{_esc(felder_txt)}</td>
<td>{_esc(case.status.value)}{f'<div class="muted">{_esc(case.bearbeiter)}</div>' if case.bearbeiter else ''}</td>
<td class="muted">{_esc(case.erstellt_am[:16].replace('T', ' '))}
    {f'<div>×{case.vorkommen}</div>' if case.vorkommen > 1 else ''}</td>
</tr>""")

        tabelle = f"""<form method="post" action="/bulk">
<input type="hidden" name="query" value="{_esc(urlencode(
    {k: v[0] for k, v in params.items() if k in
     ('status', 'typ', 'feld', 'org', 'prio', 'konfidenz', 'alter', 'sort')}))}">
<table class="tbl"><thead><tr><th></th><th>Prio</th><th>Typ</th><th>Kontakt</th>
<th>Organisation</th><th>Offene Felder</th><th>Status</th><th>Erstellt</th></tr></thead>
<tbody>{''.join(zeilen) or '<tr><td colspan="8" class="muted">Keine Fälle für diesen Filter.</td></tr>'}</tbody></table>
<div class="panel"><div class="panel-b"><div class="bar">
<div class="field"><label>Bearbeiter (Freigabe erfolgt in diesem Namen)</label>
  <input name="akteur" value="{_esc(self.actor)}" placeholder="vorname.nachname@apa.at"></div>
<div class="field"><button class="btn btn-primary" name="aktion" value="übernehmen"
  type="submit">Auswahl übernehmen</button></div>
<div class="field"><button class="btn btn-ghost" name="aktion" value="ablehnen"
  type="submit">Auswahl ablehnen</button></div>
</div><p class="muted" style="font-size:12.5px;margin:0">
Bulk-Aktionen wirken auf alle offenen Felder der markierten Fälle (FA-44).</p>
</div></div></form>"""

        kopf = f"""<div class="reco"><span class="emoji">🗂️</span><div>
<h2>{len(cases)} Fälle in der Arbeitsliste</h2>
<p>Quelle: {_esc(self.input_dir)} · CRM: {_esc(self.crm_name)} ·
Konfiguration: {_esc(self.config.source_path or 'Defaults')}</p></div>
<form method="post" action="/ingest" style="margin-left:auto">
<button class="btn btn-ghost" type="submit">📥 Neue Mails einlesen</button></form></div>"""

        body = (f'<div class="wrap">{_flash(params)}{kopf}{filterbar}{tabelle}</div>')
        return _page("Arbeitsliste", body)

    # -- Falldetail (FA-41 … FA-43, FA-47) -----------------------------------
    def case_view(self, params: dict[str, list[str]]) -> bytes:
        case_id = params.get("id", [""])[0]
        case, info = self.service.open_case(case_id)          # FA-24 Live-Abruf
        if case is None:
            return _page("Nicht gefunden",
                         '<div class="wrap"><div class="flash err">'
                         'Fall nicht gefunden.</div></div>')

        extrakt = (self.store.get_extract(case.extract_ids[0])
                   if case.extract_ids else None) or {}
        link = self.service.crm_link(case)
        link_html = (f'<a class="btn btn-ghost" style="width:auto" href="{_esc(link)}" '
                     f'target="_blank" rel="noopener">🔗 Im CRM öffnen</a>'
                     if link else '<span class="muted" style="font-size:12.5px">'
                     'Kein CRM-Direktlink konfiguriert (crm_contact_url_template)</span>')

        hinweis = ""
        if info.get("bereits_gepflegt"):
            felder = ", ".join(self.config.label_for(f)
                               for f in info["bereits_gepflegt"])
            hinweis = (f'<div class="flash ok">CRM war beim Öffnen bereits aktuell: '
                       f'{_esc(felder)} – Vorschlag wurde geschlossen.</div>')
        elif info.get("geaenderte_felder"):
            felder = ", ".join(self.config.label_for(f)
                               for f in info["geaenderte_felder"])
            hinweis = (f'<div class="flash ok">CRM-Werte live nachgeladen; '
                       f'geändert seit Fallanlage: {_esc(felder)}.</div>')

        kontext = f"""<div class="panel"><div class="panel-h">Kontext</div>
<div class="panel-b"><div class="meta">
<div class="kv"><b>Absender</b>{_esc(case.absender_email or '—')}</div>
<div class="kv"><b>Empfangen</b>{_esc(extrakt.get('empfangen_am') or '—')}</div>
<div class="kv"><b>Betreff</b>{_esc(extrakt.get('betreff') or '—')}</div>
<div class="kv"><b>Quelle</b>{_esc(extrakt.get('quelle') or '—')}</div>
<div class="kv"><b>Verfahren</b>{_esc(extrakt.get('verfahrensversion') or '—')}</div>
<div class="kv"><b>Match</b>{_esc(case.crm_kontakt_id or '—')}
  (Konfidenz {case.match_konfidenz:.2f})</div>
<div class="kv"><b>Vorkommen</b>{case.vorkommen}× · Priorität {case.prio}</div>
<div class="kv"><b>CRM-Stand</b>{_esc(info.get('abgerufen_am', 'nicht abgerufen'))}</div>
</div>
<div class="raw">{_esc(extrakt.get('rohtext_signatur') or
    'Kein Signaturtext gespeichert.')}</div>
{link_html}
</div></div>"""

        offene = [d for d in case.diffs if d.entscheidung == Decision.OFFEN]
        rows = []
        for diff in case.diffs:
            typ_pill = "add" if diff.typ == DiffType.ERGAENZUNG else "upd"
            if diff.entscheidung != Decision.OFFEN:
                entscheid = (f'<span class="pill">{_esc(diff.entscheidung.value)}'
                             f'{" → " + _esc(diff.endwert) if diff.endwert else ""}</span>')
            else:
                name = f"d_{diff.feld}"
                entscheid = f"""<div class="choice">
<label><input type="radio" name="{name}" value="übernehmen" checked> Übernehmen</label>
<label><input type="radio" name="{name}" value="ablehnen"> Ablehnen</label>
<label><input type="radio" name="{name}" value="manuell"> Manuell:</label>
<input type="text" name="w_{_esc(diff.feld)}" value="{_esc(diff.wert_signatur)}">
<label><input type="radio" name="{name}" value="offen"> später entscheiden</label>
</div>"""
            fehler = (f'<div class="flash err" style="margin-top:6px">'
                      f'{_esc(diff.fehler)}</div>' if diff.fehler else "")
            rows.append(f"""<div class="diff">
<div><b>{_esc(self.config.label_for(diff.feld))}</b>
  <div><span class="pill {typ_pill}">{_esc(diff.typ.value)}</span></div>
  <div class="muted" style="font-size:12px">Konfidenz {diff.konfidenz:.2f}</div></div>
<div><div class="muted" style="font-size:11.5px">CRM</div>
  <div class="old">{_esc(diff.wert_crm or '— leer —')}</div></div>
<div><div class="muted" style="font-size:11.5px">Vorschlag aus Signatur</div>
  <div class="new-val">{_esc(diff.wert_signatur)}</div></div>
<div>{entscheid}{fehler}</div></div>""")

        if case.kandidaten and case.typ.value == "Klärung":
            liste = "".join(
                f"<li>{_esc(k.get('name'))} · {_esc(k.get('email'))} "
                f"({_esc(k.get('crm_id'))})</li>" for k in case.kandidaten)
            rows.append(f'<div class="diff"><div><b>Kandidaten</b></div>'
                        f'<div style="grid-column:span 3"><ul>{liste}</ul></div></div>')

        notizen = "".join(f"<li>{_esc(n)}</li>" for n in case.notizen)
        audit_rows = "".join(
            f"<tr><td class='muted'>{_esc(a['zeitpunkt'][:19].replace('T', ' '))}</td>"
            f"<td>{_esc(a['aktion'])}</td><td>{_esc(a.get('feld') or '—')}</td>"
            f"<td class='muted'>{_esc(a.get('alter_wert') or '—')}</td>"
            f"<td>{_esc(a.get('neuer_wert') or '—')}</td>"
            f"<td>{_esc(a.get('akteur') or '—')}</td>"
            f"<td>{_esc(a.get('ergebnis'))}</td></tr>"
            for a in self.store.audit(case.id))

        formular = f"""<form method="post" action="/decide" class="panel">
<input type="hidden" name="id" value="{_esc(case.id)}">
<div class="panel-h">Abweichungen · {len(offene)} offen</div>
{''.join(rows) or '<div class="panel-b muted">Keine Abweichungen.</div>'}
<div class="panel-b"><div class="bar">
<div class="field"><label>Bearbeiter</label>
  <input name="akteur" value="{_esc(case.bearbeiter or self.actor)}"
         placeholder="vorname.nachname@apa.at" required></div>
</div>
<div class="actions">
<button class="btn btn-primary" style="width:auto" type="submit">
  Entscheidungen anwenden</button>
<button class="btn btn-ghost" style="width:auto" name="modus" value="ignorieren"
  type="submit" formnovalidate>Fall ignorieren</button>
</div>
<p class="muted" style="font-size:12.5px;margin:0">Teilübernahmen sind möglich:
Felder auf „später entscheiden“ bleiben offen. Geschrieben wird ausschliesslich
nach dieser Freigabe (FA-54); jede Änderung wird protokolliert (FA-53).</p>
</div></form>"""

        body = f"""<div class="wrap">{_flash(params)}{hinweis}
<div class="reco"><span class="emoji">🔍</span><div>
<h2>{_esc(case.kontakt_name or case.absender_email)} · {_esc(case.typ.value)}</h2>
<p>{_esc(case.organisation or '—')} · Status {_esc(case.status.value)} ·
Fall {_esc(case.id)}</p></div></div>
{kontext}{formular}
<div class="panel"><div class="panel-h">Notizen</div>
<div class="panel-b"><ul class="muted" style="margin:0;font-size:13px">
{notizen or '<li>—</li>'}</ul></div></div>
<div class="panel"><div class="panel-h">Audit-Log (FA-53)</div>
<table class="tbl"><thead><tr><th>Zeit</th><th>Aktion</th><th>Feld</th>
<th>Alt</th><th>Neu</th><th>Akteur</th><th>Ergebnis</th></tr></thead>
<tbody>{audit_rows or '<tr><td colspan="7" class="muted">—</td></tr>'}</tbody>
</table></div>
<a href="/">← zurück zur Arbeitsliste</a></div>"""
        return _page(case.kontakt_name or "Fall", body)

    # -- Kennzahlen (Kapitel 11) ---------------------------------------------
    def kpi_view(self) -> bytes:
        kpis = compute_kpis(self.store, self.config)
        karten = [
            ("Signaturen ausgewertet", kpis["signaturen_verarbeitet"], ""),
            ("Fälle gesamt", kpis["faelle_gesamt"], ""),
            ("Trefferquote", f"{kpis['trefferquote']:.0%}",
             "Fälle mit ≥1 relevanter Abweichung"),
            ("Freigabequote", f"{kpis['freigabequote']:.0%}", "Ziel ≥ 60 %"),
            ("Falsch-Positiv-Quote", f"{kpis['falsch_positiv_quote']:.0%}",
             "NFA-05: ≤ 25 %"),
            ("Ø Bearbeitungsdauer", f"{kpis['bearbeitungsdauer_schnitt_s']:.0f} s",
             "Ziel < 30 s"),
            ("Signatur aktueller", f"{kpis['anteil_signatur_aktueller']:.0%}",
             f"{kpis['faelle_signatur_aktueller']} Fälle"),
            ("CRM-Updates", kpis["crm_updates"],
             f"{kpis['aktualisierte_kontakte']} Kontakte, "
             f"{kpis['crm_schreibfehler']} Fehler"),
        ]
        kacheln = "".join(
            f'<div class="kpi"><div class="kpi-v">{_esc(str(wert))}</div>'
            f'<div class="kpi-l">{_esc(titel)}</div>'
            f'<div class="muted" style="font-size:11.5px">{_esc(sub)}</div></div>'
            for titel, wert, sub in karten)
        zeilen = "".join(
            f"<tr><td>{_esc(v['label'])}</td><td>{v['vorschlaege']}</td>"
            f"<td>{v['freigegeben']}</td><td>{v['abgelehnt']}</td>"
            f"<td>{v['offen']}</td><td>{v['freigabequote']:.0%}</td></tr>"
            for _, v in sorted(kpis["je_feld"].items(),
                               key=lambda kv: kv[1]["vorschlaege"], reverse=True))
        body = f"""<div class="wrap">
<div class="reco"><span class="emoji">📊</span><div><h2>Kennzahlen</h2>
<p>Hypothesenvalidierung nach Kapitel 11 der Anforderungsdefinition</p></div></div>
<div class="kpis">{kacheln}</div>
<table class="tbl"><thead><tr><th>Feld</th><th>Vorschläge</th><th>Freigegeben</th>
<th>Abgelehnt</th><th>Offen</th><th>Freigabequote</th></tr></thead>
<tbody>{zeilen or '<tr><td colspan="6" class="muted">Noch keine Vorschläge.</td></tr>'}
</tbody></table>
<a href="/">← zurück zur Arbeitsliste</a></div>"""
        return _page("Kennzahlen", body)


def _redirect_target(params: dict[str, str]) -> str:
    query = urlencode({k: v for k, v in params.items() if v})
    return "/?" + query if query else "/"


def make_handler(app: ReviewApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # ruhiger Server
            pass

        def _send(self, payload: bytes, ctype="text/html; charset=utf-8", code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, data) -> None:
            self._send(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                       ctype="application/json; charset=utf-8")

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def do_GET(self):
            url = urlparse(self.path)
            params = parse_qs(url.query)
            if url.path == "/":
                self._send(app.worklist(params))
            elif url.path == "/case":
                self._send(app.case_view(params))
            elif url.path == "/kpi":
                self._send(app.kpi_view())
            elif url.path == "/api/cases.json":
                self._json([c.to_dict() for c in app.service.list_cases()])
            elif url.path == "/api/kpi.json":
                self._json(compute_kpis(app.store, app.config))
            else:
                self._send(_page("Nicht gefunden",
                                 '<div class="wrap"><div class="flash err">'
                                 'Seite nicht gefunden.</div></div>'), code=404)

        def _form(self) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            return parse_qs(raw, keep_blank_values=True)

        def do_POST(self):
            path = urlparse(self.path).path
            form = self._form()
            if path == "/decide":
                self._decide(form)
            elif path == "/bulk":
                self._bulk(form)
            elif path == "/ingest":
                self._ingest()
            else:
                self._send(_page("Nicht gefunden", ""), code=404)

        def _decide(self, form: dict[str, list[str]]) -> None:
            case_id = form.get("id", [""])[0]
            akteur = form.get("akteur", [""])[0].strip()
            if form.get("modus", [""])[0] == "ignorieren":
                app.service.ignore_case(case_id, akteur or "unbekannt")
                self._redirect(_redirect_target({"ok": "Fall geschlossen."}))
                return
            if not akteur:
                self._redirect(f"/case?id={case_id}&err=Bitte+Bearbeiter+angeben.")
                return
            case = app.store.get_case(case_id)
            if case is None:
                self._redirect(_redirect_target({"err": "Fall nicht gefunden."}))
                return
            entscheidungen: dict[str, dict[str, str]] = {}
            for diff in case.diffs:
                wahl = form.get(f"d_{diff.feld}", [""])[0]
                if not wahl or wahl == "offen":
                    continue
                entscheidungen[diff.feld] = {
                    "entscheidung": wahl,
                    "wert": form.get(f"w_{diff.feld}", [""])[0],
                }
            if not entscheidungen:
                self._redirect(f"/case?id={case_id}&err=Keine+Entscheidung+getroffen.")
                return
            result = app.service.apply_decisions(case_id, entscheidungen, akteur)
            if not result.ok:
                self._redirect(f"/case?id={case_id}&err={result.fehler}")
                return
            if result.modus == "manuell":
                msg = (f"{len(result.uebernommen)} Feld(er) zur manuellen Übernahme "
                       f"freigegeben.")
            else:
                msg = (f"{len(result.uebernommen)} Feld(er) ins CRM geschrieben, "
                       f"{len(result.abgelehnt)} abgelehnt.")
            self._redirect(_redirect_target({"ok": msg}))

        def _bulk(self, form: dict[str, list[str]]) -> None:
            case_ids = form.get("case_id", [])
            aktion = form.get("aktion", ["übernehmen"])[0]
            akteur = form.get("akteur", [""])[0].strip()
            query = form.get("query", [""])[0]
            if not case_ids:
                self._redirect("/?err=Keine+F%C3%A4lle+markiert.")
                return
            if not akteur:
                self._redirect("/?err=Bitte+Bearbeiter+angeben.")
                return
            ergebnisse = app.service.bulk_apply(case_ids, aktion, akteur)
            fehler = [r for r in ergebnisse if not r.ok]
            msg = (f"{len(ergebnisse) - len(fehler)} Fall/Fälle verarbeitet"
                   + (f", {len(fehler)} mit Fehler" if fehler else ""))
            self._redirect(("/?" + query + "&" if query else "/?")
                           + urlencode({"ok": msg}))

        def _ingest(self) -> None:
            try:
                report = run_checker(app.input_dir, app.crm, app.store, app.config)
            except Exception as exc:  # noqa: BLE001 - UI soll nicht abstürzen
                self._redirect(_redirect_target({"err": str(exc)}))
                return
            msg = (f"{report.verarbeitet} Mail(s) verarbeitet · "
                   f"{len(report.faelle_neu)} neue Fälle · "
                   f"{len(report.faelle_aggregiert)} aggregiert · "
                   f"{report.dubletten} Dubletten · {report.verworfen} verworfen")
            self._redirect(_redirect_target({"ok": msg}))

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8010, crm: str = "mock",
          input_dir: str | Path = DEFAULT_INPUT, config: CheckerConfig | None = None,
          actor: str = "") -> None:
    cfg = config or get_config()
    store = CheckerStore(cfg.store_file())
    app = ReviewApp(store, crm, cfg, str(input_dir), actor=actor)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"Review-UI läuft auf http://{host}:{port}  "
          f"(Store: {cfg.store_file()}, CRM: {crm})")
    print("Hinweis: keine Authentifizierung – nur für internen Test (NFA-06 offen).")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        httpd.server_close()
