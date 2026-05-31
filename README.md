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

Keine externen Abhängigkeiten für `.eml` und die Demo. Für `.msg`-Dateien wird
optional [`extract-msg`](https://pypi.org/project/extract-msg/) genutzt
(siehe `requirements.txt`); fehlt das Paket, werden `.msg`-Dateien übersprungen
und im Report vermerkt.

---

## Weboberfläche (zum Vorführen)

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

Statischer Export (eine eigenständige HTML-Datei, ohne laufenden Server):

```bash
python -c "from signatur.web import export_static; export_static('out/dashboard.html','samples','mock')"
```

## Projektstruktur

```
signatur/
  email_loader.py        # .eml/.msg -> LoadedEmail (Header + Text/HTML)
  signature_extractor.py # Signaturblock finden + Felder + Business-Kontext parsen
  reconciler.py          # Signatur ↔ CRM vergleichen -> Abweichungen + Signale
  notifier.py            # Hinweis-Mail (Text/HTML) + Gmail-Draft-Payload bauen
  pipeline.py            # Orchestrierung Ende-zu-Ende
  sender.py              # SMTP-Versand (MIME Text+HTML)
  web.py                 # Web-Oberfläche (stdlib http.server) + Static-Export
  cli.py / __main__.py   # CLI-Einstieg (python -m signatur run|serve)
  models.py              # Datenmodelle (dataclasses)
  crm/
    base.py              # CrmClient-Interface (find_contact)
    mock_crm.py          # CSV-gestütztes Mock-CRM (Demo)
    sap_sales_cloud.py   # SAP-Sales-Cloud-Adapter (OData, konfigurierbar)
config/
  mapping.json           # Signatur-Feld -> CRM-Feld-Mapping (inkl. SAP-Felder)
data/
  crm_mock.csv           # Demodaten fürs Mock-CRM
samples/                 # Beispiel-.eml
tests/                   # Unit-Tests (Extractor + Reconciler)
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

## Roadmap zum Echtbetrieb

- [ ] IMAP-Anbindung des dedizierten Postfachs statt Datei-Upload
- [ ] `SapSalesCloudClient` gegen produktive SAP-Sales-Cloud-Instanz testen
- [ ] Schreib-Pfad (optional): bestätigte Abweichungen als CRM-Update zurückspielen
- [ ] Mehrsprachige Grußformel-/Titel-Wörterbücher erweitern
```
