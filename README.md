# Signatur-Abgleich · E-Mail-Signaturen ↔ CRM

Workflow, der **E-Mail-Signaturen ausliest, daraus geschäftsrelevanten Kontext
extrahiert, gegen ein CRM abgleicht** und anschließend einen **Hinweis per
E-Mail** (als Gmail-Entwurf zur Freigabe) erzeugt.

> Zielbild Produktion: Signaturen kommen aus einem **dedizierten Postfach**,
> CRM ist **SAP Sales Cloud**.
> Aktueller Stand: Eingabe per **`.eml`/`.msg`-Upload**, CRM über einen
> austauschbaren Adapter (Mock für Demo, SAP-Sales-Cloud-Adapter vorbereitet).

---

## Workflow in 5 Schritten

```
 ┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐   ┌──────────────┐
 │ 1 E-Mails  │ → │ 2 Signatur   │ → │ 3 Business-   │ → │ 4 CRM-       │ → │ 5 Hinweis    │
 │   laden    │   │   extrahieren│   │   Kontext     │   │   Abgleich   │   │   (Entwurf)  │
 │ .eml/.msg  │   │ (Block trenn)│   │ (Felder+Sig.) │   │ (Adapter)    │   │ Gmail-Draft  │
 └────────────┘   └──────────────┘   └───────────────┘   └──────────────┘   └──────────────┘
```

1. **E-Mails laden** — `.eml`/`.msg` aus einem Eingabeordner (später: IMAP-Postfach).
2. **Signatur extrahieren** — Signaturblock vom Fließtext trennen (Grußformel/`-- `).
3. **Business-Kontext** — Name, Titel/Rolle, Abteilung, Firma, Telefon/Mobil,
   E-Mail, Website, LinkedIn, Adresse; abgeleitet: Seniorität, Entscheider-Flag, Standort.
4. **CRM-Abgleich** — Kontakt per E-Mail/Name matchen; Abweichungen & Signale
   erkennen (neuer Kontakt, Jobwechsel, Firmenwechsel, neue/ geänderte Telefonnummer …).
5. **Hinweis** — kompakter Report als **Gmail-Entwurf** an den/die Verantwortliche·n.

---

## Schnellstart

```bash
# Demo-Lauf gegen das Mock-CRM mit den Beispiel-Mails
python -m signatur run --input samples --crm mock --out out

# Ergebnis ansehen
cat out/reconciliation.json        # strukturiertes Ergebnis
cat out/notification.md            # Hinweis-Text (Vorschau des Gmail-Entwurfs)
```

Keine externen Abhängigkeiten für `.eml` und die Demo. Für den Import echter
**Outlook-`.msg`-Dateien** wird [`olefile`](https://pypi.org/project/olefile/)
(pure-Python) genutzt — einmalig installieren:

```bash
pip install -r requirements.txt   # bzw. pip install olefile
```

Fehlt `olefile`, werden `.msg`-Dateien übersprungen und im Report vermerkt
(`.eml` funktioniert immer). Der `.msg`-Parser liest die MAPI-Properties direkt
(Betreff, Absender aus Transport-Headern bzw. Sender-Properties, Text-/HTML-Body).

---

## Browser-App (ohne Server, .eml/.msg einfügen)

Eigenständige Web-App im **Material-Design-3**-Look (Corporate-Farben), die
`.eml`/`.msg` **direkt im Browser** parst und abgleicht – kein Backend, nichts
wird hochgeladen. Einfach [`webapp/demo.html`](webapp/demo.html) öffnen und
Dateien per Drag&Drop einfügen. Details: [`webapp/README.md`](webapp/README.md).

```bash
python webapp/generate_data.py && python webapp/build.py   # demo.html neu bauen
```

## Weboberfläche (Server, zum Vorführen)

Schlanke Demo-UI auf Basis der Standardbibliothek (kein Flask o. ä.):

```bash
python -m signatur serve --port 8000      # dann http://127.0.0.1:8000 öffnen
```

Funktionen:
- Dashboard mit Kennzahlen (verarbeitet / neue Kontakte / mit Änderungen)
- Pro-Kontakt-Karten: **aus der Signatur extrahierte Felder** + **Abweichungen
  zum CRM** (Diff) + Business-Signale, sortiert nach Handlungsbedarf
- **Live-Vorschau der Hinweis-Mail** (HTML)
- **Upload** von `.eml`/`.msg` direkt im Browser
- JSON-Endpunkt `/api/result.json`

**Eigenständige HTML-Demo** (eine Datei, ohne Server – zum Vorführen/Verschicken):

```bash
python -m signatur export --input samples --crm mock --out docs/demo.html
```

Eine vorgenerierte Version mit Demodaten liegt unter [`docs/demo.html`](docs/demo.html)
(einfach im Browser öffnen – Tabs und Ansichten funktionieren ohne Backend).

## Echtdaten importieren (.eml / .msg)

Reale E-Mails lassen sich direkt verarbeiten:

- **`.eml`** — aus den meisten Mail-Clients per „Speichern unter" / Drag&Drop
  (Apple Mail, Thunderbird, Gmail „Nachricht herunterladen").
- **`.msg`** — Outlook: E-Mail markieren → „Speichern unter" → Outlook-Format
  `.msg` (benötigt `olefile`, siehe oben).

Zwei Wege:

```bash
# A) Ordner mit Echtdaten per CLI abgleichen
python -m signatur run --input /pfad/zu/echtdaten --crm mock --out out

# B) In der Weboberfläche hochladen (Drag&Drop von .eml/.msg)
python -m signatur serve --port 8000
```

Mehrere Dateien und gemischte Formate (`.eml` + `.msg`) in einem Lauf werden
unterstützt; nicht lesbare Dateien landen mit Begründung im Abschnitt
„Übersprungen".

---

## Signature Checker (Umsetzung der Anforderungsdefinition v0.1)

Zusätzlich zum Demo-Workflow oben enthält das Repository die Umsetzung der
[Anforderungsdefinition Signature Checker](docs/anforderungen-signature-checker.md)
für **Stufe 1 (MVP)** samt wesentlicher Teile aus Stufe 2: Fallmodell,
Review-Arbeitsplatz mit feldweiser Freigabe, Suppression-Liste, Audit-Log,
schreibende CRM-Schnittstelle und Kennzahlen.

Welche Anforderung wo umgesetzt ist — und was bewusst offen bleibt — steht in
der [Anforderungsabdeckung](docs/anforderungsabdeckung.md).

```
[E-Mails] → [Ingest-Regeln] → [Extraktion + Konfidenz] → [Matching] →
[Normalisierung + Relevanzregeln] → [Fall] → [Review-UI] → [CRM-Schreiben] → [Audit + KPI]
```

### Ablauf in der Praxis

```bash
# 1) Mails einlesen und Fälle erzeugen (Ingest → Extrakt → Match → Fall)
python -m signatur check --input samples --crm mock

# 2) Arbeitsliste ansehen
python -m signatur cases

# 3) Review-UI für das Datenteam starten (Arbeitsliste, Falldetail, Kennzahlen)
python -m signatur review --port 8010     # http://127.0.0.1:8010

# 4) Alternativ per CLI entscheiden (feldweise, mit Protokollierung)
python -m signatur decide --case-id case-… --actor vorname.nachname@apa.at \
       --accept job_title,mobile --reject company

# 5) Kennzahlen zur Hypothesenvalidierung (Kapitel 11)
python -m signatur kpi

# 6) Sammelbenachrichtigung über neue Fälle
python -m signatur digest --hours 24 [--to team@firma.at --send smtp]

# 7) Datenschutz: Löschfristen anwenden, Auskunft/Löschung je Person
python -m signatur purge
python -m signatur person --email kontakt@firma.de [--delete]
```

### Was das Regelwerk garantiert

- **Kein Schreiben ohne Freigabe** — jede CRM-Änderung braucht eine Person und
  landet mit altem und neuem Wert im Audit-Log.
- **Kein Rauschen** — verglichen wird nur die konfigurierte Feld-Whitelist, nur
  oberhalb des Konfidenz-Schwellwerts und nur nach Normalisierung (E.164,
  Rechtsformen, Abkürzungen); ein leerer Signaturwert überschreibt nie.
- **Keine Wiedervorlage abgelehnter Werte** — Ablehnungen landen auf der
  Suppression-Liste; wiederholte gleiche Vorschläge werden zu einem Fall
  aggregiert und erhöhen dessen Priorität.
- **Aktueller CRM-Stand** — beim Öffnen eines Falls wird der Kontakt live neu
  gelesen; zwischenzeitlich gepflegte Werte schliessen den Vorschlag.

### Konfiguration ohne Deployment

Alle fachlichen Stellschrauben liegen in [`config/checker.json`](config/checker.json):
Feld-Whitelist, Konfidenz-Schwellwerte je Feld, Allow-/Blocklists, interne
Domains, Suppression-Dauer, Benachrichtigungsintervall, Schreibmodus
(`crm` oder `manuell` mit Direktlink) und die Vorlage für den CRM-Direktlink.

---

## Projektstruktur

```
signatur/
  email_loader.py        # .eml/.msg -> LoadedEmail (Header + Text/HTML)
  signature_extractor.py # Signaturblock finden + Felder + Business-Kontext parsen
  confidence.py          # Konfidenz je extrahiertem Feld (FA-12)
  normalize.py           # Normalisierung vor dem Vergleich (E.164, Rechtsformen …)
  ingest.py              # Ingest-Regeln: extern/intern, No-Reply, Idempotenz
  matching.py            # Zuordnung Extrakt -> CRM-Kontakt (inkl. Mehrdeutigkeit)
  cases.py               # Relevanzregelwerk, Fallbildung, Priorität, Aggregation
  store.py               # Persistenz: Extrakte, Fälle, Audit, Suppressions
  checker.py             # Ende-zu-Ende-Lauf: Mail -> Extrakt -> Match -> Fall
  review.py              # Entscheidungen, CRM-Rückschreiben, Audit, Bulk, Digest
  review_web.py          # Review-UI für das Datenteam (Arbeitsliste/Fall/KPI)
  kpi.py                 # Kennzahlen zur Hypothesenvalidierung (Kapitel 11)
  config.py              # Laufzeit-Konfiguration (ohne Deployment änderbar)
  reconciler.py          # Signatur ↔ CRM vergleichen -> Abweichungen + Signale
  notifier.py            # Hinweis-Mail (Text/HTML) + Gmail-Draft-Payload bauen
  pipeline.py            # Orchestrierung des Demo-Workflows
  sender.py              # SMTP-Versand (MIME Text+HTML)
  web.py                 # Demo-Oberfläche (stdlib http.server) + Static-Export
  cli.py / __main__.py   # CLI-Einstieg (run|serve|export|check|cases|review|…)
  models.py              # Datenmodelle inkl. Fall/Diff/Audit/Suppression
  crm/
    base.py              # CrmClient-Interface (Lesen + Schreiben)
    mock_crm.py          # CSV-gestütztes Mock-CRM inkl. Schreibpfad
    sap_sales_cloud.py   # SAP-Sales-Cloud-Adapter (OData, lesend + schreibend)
config/
  mapping.json           # Signatur-Feld -> CRM-Feld-Mapping (inkl. SAP-Felder)
  checker.json           # Fachliche Konfiguration des Signature Checkers
data/
  crm_mock.csv           # Demodaten fürs Mock-CRM
docs/
  anforderungen-signature-checker.md  # Anforderungsdefinition v0.1 (Produktmanagement)
  anforderungsabdeckung.md            # Umsetzungsstand je Anforderung + offene Punkte
samples/                 # Beispiel-.eml
tests/                   # Tests (Extraktion, Regelwerk, Review-Flow, KPI, UI)
```

---

## CRM-Adapter (austauschbar)

`signatur/crm/base.py` definiert das Interface `CrmClient` mit der zentralen
Methode `find_contact(email, name) -> CrmContact | None`. Implementierungen:

- **`mock_crm.MockCrmClient`** — liest `data/crm_mock.csv`, für Demo/Tests.
- **`sap_sales_cloud.SapSalesCloudClient`** — fragt die SAP-Sales-Cloud-OData-API
  ab. Konfiguration über Umgebungsvariablen:

  | Variable | Bedeutung |
  |---|---|
  | `SAP_SALESCLOUD_BASE_URL` | z. B. `https://myXXXXXX.crm.ondemand.com` |
  | `SAP_SALESCLOUD_USER` / `SAP_SALESCLOUD_PASSWORD` | Basic-Auth (oder OAuth-Token) |
  | `SAP_SALESCLOUD_TOKEN` | optional, Bearer-Token statt Basic-Auth |

  Das Feld-Mapping (Signatur → SAP) liegt in `config/mapping.json`.

Umschalten per CLI: `--crm mock` (Default) oder `--crm sap`.

---

## Versand des Hinweises

Zwei Wege:

1. **Gmail-Entwurf (Default, Freigabe durch Mensch)** — `notifier.py` baut ein
   Draft-Payload (`to`, `subject`, `text`, `html`), das als Gmail-Entwurf
   angelegt wird. Versand bleibt beim Menschen.
2. **Echter Versand per SMTP** — `signatur/sender.py` (`SmtpSender`) verschickt
   den Hinweis als MIME-Mail (Text + HTML-Alternative). Aktivierung über die CLI:

   ```bash
   python -m signatur run --input samples --crm mock \
     --to vertrieb@firma.de --send smtp --smtp-host smtp.firma.de
   ```

   SMTP-Konfiguration über Umgebungsvariablen:

   | Variable | Bedeutung |
   |---|---|
   | `SIGNATUR_SMTP_HOST` | SMTP-Server (z. B. `smtp.gmail.com`) |
   | `SIGNATUR_SMTP_PORT` | Port (Default 587 STARTTLS / 465 SSL) |
   | `SIGNATUR_SMTP_USER` / `SIGNATUR_SMTP_PASSWORD` | Login (App-Passwort) |
   | `SIGNATUR_SMTP_FROM` | Absenderadresse (Default: User) |
   | `SIGNATUR_SMTP_SECURITY` | `starttls` (Default) / `ssl` / `none` |

   > Hinweis: Das angebundene Gmail-MCP kann nur **Entwürfe** anlegen, nicht
   > senden — echter Versand läuft daher über SMTP (z. B. das dedizierte Postfach).

**Versand lokal testen** (ohne echte Zustellung, mit Auffang-SMTP-Server):

```bash
python scripts/smtp_send_demo.py   # sendet real per SMTP an lokalen Server & prüft Empfang
```

---

## Tests

```bash
pip install pytest && python -m pytest -q
```

## Roadmap zum Echtbetrieb

- [x] Fallmodell, Review-Arbeitsplatz und Audit-Log (Anforderungen FA-40 … FA-54)
- [x] Schreib-Pfad: freigegebene Abweichungen als CRM-Update zurückspielen
- [x] Kennzahlen zur Hypothesenvalidierung (Kapitel 11)
- [ ] IMAP-Anbindung des dedizierten Postfachs statt Datei-Upload (OP-01)
- [ ] `SapSalesCloudClient` gegen produktive SAP-Sales-Cloud-Instanz testen (OP-02)
- [ ] SSO/rollenbasierter Zugriff auf die Review-UI (NFA-06)
- [ ] Monitoring und Alerting für Verarbeitungs- und Schnittstellenfehler (NFA-09)
- [ ] Precision-Nachweis auf ≥ 100 realen Signaturen (NFA-04, Stufe 0)
```
