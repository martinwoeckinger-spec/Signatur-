# Signatur-Sync · Browser-App (ohne Server)

Eigenständige Web-App im **Material-Design-3**-Look (Corporate-Farben), die
`.eml`/`.msg` **direkt im Browser** einliest, Signaturen analysiert und gegen
ein eingebettetes Demo-CRM abgleicht. **Kein Backend, keine Installation,
nichts wird hochgeladen.**

Corporate-Palette: Primary `#F06900` · Secondary `#2C82BE` · Ergänzend
`#555F69` · Features `#C3B9A0`.

## Nutzen

- **Eine Datei:** [`demo.html`](demo.html) im Browser öffnen. Demodaten sind
  vorgeladen; eigene `.eml`/`.msg` per **Drag&Drop** oder „E-Mails einfügen".
- **Quellcode** (entwicklungsfreundlich, gleiche Logik):
  `index.html` + `styles.css` + `app.js` + `data.js`.

## Aufbau

| Datei | Inhalt |
|---|---|
| `app.js` | Kernlogik: `.eml`- und `.msg`-Parser (OLE/CFB), Signatur-Extraktion, CRM-Abgleich. Läuft in Browser **und** Node. |
| `styles.css` | Material-Design-3-Tokens (Farbrollen, Form, Elevation, Typo) + Komponenten auf 8-dp-Raster. |
| `data.js` | Eingebettete Demodaten (CRM, 5 Demo-`.eml`, 1 echte `.msg` als Base64). Auto-generiert. |
| `index.html` | MD3-Markup + UI-Logik (Drag&Drop, Rendering). |
| `generate_data.py` | Erzeugt `data.js` aus `data/crm_mock.csv` + `samples/`. |
| `build.py` | Inlined alles zu einer eigenständigen `demo.html`. |

## Neu bauen

```bash
python webapp/generate_data.py   # data.js aus CRM-CSV + samples/ erzeugen
python webapp/build.py           # -> webapp/demo.html (eine Datei)
```

## Hinweise

- Die `.msg`-Unterstützung im Browser nutzt einen eigenen, abhängigkeitsfreien
  OLE/CFB-Reader (MAPI-Property-Streams) – verifiziert an echten Outlook-`.msg`.
- Das CRM ist hier eine eingebettete Demo-CSV; im Echtbetrieb tritt an seine
  Stelle SAP Sales Cloud (siehe Haupt-`README.md`).
- Die Analyse-Logik ist identisch zur Python-Pipeline und wird per Node gegen
  dieselben Beispiel­dateien getestet.
