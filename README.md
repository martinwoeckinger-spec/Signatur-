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

## Projektstruktur

```
signatur/
  email_loader.py        # .eml/.msg -> LoadedEmail (Header + Text/HTML)
  signature_extractor.py # Signaturblock finden + Felder + Business-Kontext parsen
  reconciler.py          # Signatur ↔ CRM vergleichen -> Abweichungen + Signale
  notifier.py            # Hinweis-Mail (Text/HTML) + Gmail-Draft-Payload bauen
  pipeline.py            # Orchestrierung Ende-zu-Ende
  cli.py / __main__.py   # CLI-Einstieg (python -m signatur ...)
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

Der Workflow erzeugt **keinen** automatischen Versand. `notifier.py` baut ein
Draft-Payload (`to`, `subject`, `text`, `html`), das als **Gmail-Entwurf**
angelegt wird — Freigabe und Versand bleiben beim Menschen.

---

## Roadmap zum Echtbetrieb

- [ ] IMAP-Anbindung des dedizierten Postfachs statt Datei-Upload
- [ ] `SapSalesCloudClient` gegen produktive SAP-Sales-Cloud-Instanz testen
- [ ] Schreib-Pfad (optional): bestätigte Abweichungen als CRM-Update zurückspielen
- [ ] Mehrsprachige Grußformel-/Titel-Wörterbücher erweitern
```
