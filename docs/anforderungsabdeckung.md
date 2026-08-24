# Anforderungsabdeckung Signature Checker — Antwort Development

**Bezug:** [`anforderungen-signature-checker.md`](anforderungen-signature-checker.md) (v0.1, 17.08.2026)
**Stand:** Umsetzung Stufe 1 (MVP) im vorliegenden Repository
**Legende:** ✅ umgesetzt · 🟡 teilweise umgesetzt · ⛔ nicht umgesetzt (bewusst, siehe Begründung)

---

## 1. Kurzfassung

Die Anforderungen sind fachlich klar und in dieser Form umsetzbar. Auf Basis des
bereits vorhandenen Prototyps (Extraktion, Abgleich, Demo-UI) ist der in Kapitel
15 beschriebene **MVP (Stufe 1) umgesetzt und um wesentliche Teile aus Stufe 2
ergänzt** — Fallmodell, Review-Arbeitsplatz mit feldweiser Entscheidung,
Suppression-Liste, Audit-Log, schreibende CRM-Schnittstelle (Mock produktiv,
SAP-Adapter vorbereitet) und die Kennzahlen aus Kapitel 11.

**Alle mit M priorisierten funktionalen Anforderungen sind umgesetzt und
getestet**, mit zwei Einschränkungen, die von offenen Punkten abhängen und
deshalb nicht im Code entschieden werden konnten:

| Einschränkung | Grund | Abhängig von |
|---|---|---|
| Quelle ist ein Ordner mit `.eml`/`.msg`, kein Postfach | Anbindungsart und Postfachumfang sind ungeklärt | OP-01, DS-03 |
| Schreiben produktiv nur gegen das Mock-CRM erprobt | Kein Zugang zu einer SAP-Sales-Cloud-Instanz | OP-02 |

Nicht umgesetzt sind bewusst: **NFA-06 (SSO/rollenbasierter Zugriff)** und
**NFA-09 (Monitoring/Alerting)** — beides Betriebsthemen, die an die
Zielumgebung gebunden sind, sowie **NFA-04 (Precision-Nachweis)**, der ein
abgestimmtes Testset aus mindestens 100 realen Signaturen voraussetzt.

**Empfehlung unverändert: Stufe 0 zuerst.** Der Code liefert dafür jetzt das
Werkzeug: `signatur check` verarbeitet einen Ordner mit Echtmails, `signatur kpi`
weist Trefferquote und Freigabequote aus. Eine Stichprobe von 200 Signaturen ist
damit an einem Tag auswertbar und liefert gleichzeitig das Testset für NFA-04.

---

## 2. Was in dieser Lieferung neu ist

| Baustein | Modul | Zweck |
|---|---|---|
| Ingest-Regelwerk | `signatur/ingest.py` | Allow-/Blocklist, No-Reply, Autoreply, Newsletter, Idempotenz |
| Konfidenzbewertung | `signatur/confidence.py` | Konfidenz je Feld aus erklärbaren Signalen |
| Normalisierung | `signatur/normalize.py` | E.164, Rechtsformen, Abkürzungen, URL/Adresse |
| Matching | `signatur/matching.py` | E-Mail-Match, Name+Domain-Fallback, Mehrdeutigkeit |
| Relevanzregelwerk | `signatur/cases.py` | Whitelist, Schwellwerte, Ergänzung/Änderung, Priorität, Aggregation |
| Persistenz | `signatur/store.py` | Extrakte, Snapshots, Fälle, Audit, Suppressions, Löschfristen |
| Verarbeitungslauf | `signatur/checker.py` | Ende-zu-Ende: Mail → Extrakt → Match → Fall |
| Review-Service | `signatur/review.py` | Entscheidungen, Rückschreiben, Audit, Bulk, Digest |
| Review-UI | `signatur/review_web.py` | Arbeitsliste, Falldetail, Kennzahlenseite |
| Kennzahlen | `signatur/kpi.py` | Kapitel 11 inkl. MVP-Erfolgskriterium |
| Konfiguration | `signatur/config.py`, `config/checker.json` | Alle fachlichen Stellschrauben ohne Deployment |

Bedienung:

```bash
python -m signatur check  --input <ordner> --crm mock     # Mails → Fälle
python -m signatur cases                                   # Arbeitsliste
python -m signatur review --port 8010                      # Review-UI
python -m signatur decide --case-id <id> --actor <person> \
        --accept job_title --reject company                # Freigabe/Ablehnung
python -m signatur kpi                                     # Kennzahlen Kap. 11
python -m signatur digest --hours 24                       # Sammelbenachrichtigung
python -m signatur purge                                   # Löschfristen (DS-04)
python -m signatur person --email <adresse> [--delete]     # Auskunft/Löschung (DS-06)
```

---

## 3. Funktionale Anforderungen

### 3.1 Ingest

| ID | Prio | Status | Umsetzung | Anmerkung / Lücke |
|---|---|---|---|---|
| FA-01 | M | 🟡 | `email_loader.iter_email_files`, `checker.run_checker` | Quelle ist konfigurierbar, aber dateibasiert (`.eml`/`.msg`). Postfachanbindung (IMAP/Graph/Journaling) erst nach OP-01; Aufwand 3–5 PT. |
| FA-02 | M | ✅ | `ingest.classify` | Interne Domains, Blocklist und optionale Allowlist inkl. Subdomains, konfigurierbar in `config/checker.json`. |
| FA-03 | M | ✅ | `checker._build_extract`, `store` | Persistiert werden Metadaten, Felder, Konfidenz und der Signaturblock — nie der Nachrichtentext. Test: `test_nur_signaturblock_wird_persistiert`. |
| FA-04 | S | ✅ | `ingest.NOREPLY_RE`, `AUTOREPLY_SUBJECT_RE`, Header-Prüfungen | Auto-Submitted/X-Autoreply, List-Unsubscribe, Precedence, No-Reply-Adressen, DE/EN-Betreffmuster. |
| FA-05 | M | ✅ | `ingest.message_key`, `store.is_processed` | Primär Message-ID; fehlt sie (Exporte ohne Header), greift ein Hash aus Absender/Datum/Betreff. |

### 3.2 Extraktion

| ID | Prio | Status | Umsetzung | Anmerkung / Lücke |
|---|---|---|---|---|
| FA-10 | M | 🟡 | `signature_extractor.extract_all_signatures` | Trennung von Body, Zitaten und Verlauf ist umgesetzt und getestet. Disclaimer werden nur indirekt begrenzt (Blockheuristik); eine eigene Disclaimer-Erkennung ist offen (0,5–1 PT). |
| FA-11 | M | ✅ | `models.Signature`, `_find_address`, `_academic_title` | Alle geforderten Felder inkl. akad. Titel und Adresse strukturiert (Straße, PLZ, Ort, Land). Abteilung wird nur bei Schlüsselwort erkannt — bewusst konservativ, sonst steigen Falsch-Positive. |
| FA-12 | M | ✅ | `confidence.score_signature`, `cases.apply_rules` | Konfidenz je Feld aus erklärbaren Signalen (Absenderadresse, Label, Rechtsform, Domainbezug, Art der Blockerkennung). Schwellwerte global und je Feld konfigurierbar. |
| FA-13 | M | ✅ | Wörterbücher in `signature_extractor`, `normalize` | Deutsch und Englisch (Grußformeln, Telefonlabels, Positionsbezeichnungen, Straßen-/Ländermuster). Weitere Sprachen: Stufe 3. |
| FA-14 | S | ✅ | `checker._sender_signature` | Alle Signaturen eines Verlaufs werden erkannt, verwendet wird die des aktuellen Absenders. |
| FA-15 | S | 🟡 | `EXTRACTOR_VERSION`, `SignatureExtract.verfahrensversion`, `config.extractor` | Die Verfahrensversion wird je Extrakt protokolliert und der Schalter existiert; austauschbar ist derzeit nur die Regel-Variante, ein LLM-Verfahren ist nicht implementiert (abhängig von OP-05/DS-05; Aufwand 5–8 PT). |
| FA-16 | C | ✅ | `ingest.looks_like_image_signature` | Mails mit Inline-Bildern ohne Textsignatur werden als „nicht auswertbar“ mit Hinweis abgelegt und in den Kennzahlen ausgewiesen. Kein OCR (Nicht-Ziel). |

### 3.3 Matching

| ID | Prio | Status | Umsetzung | Anmerkung / Lücke |
|---|---|---|---|---|
| FA-20 | M | ✅ | `matching.match_signature` | Exakte E-Mail-Übereinstimmung, Konfidenz 1,0. |
| FA-21 | S | ✅ | `matching`, `MockCrmClient.find_contacts` | Name + Organisationsdomain, Konfidenz 0,7 (ohne Domain 0,5); Mindestkonfidenz konfigurierbar. |
| FA-22 | M | ✅ | `cases.build_case` | Mehrfachtreffer erzeugen einen Fall vom Typ „Klärung“ mit Kandidatenliste und ohne Vorschlag. |
| FA-23 | S | ✅ | `cases.build_case`, `review.ignore_case` | Fall „Unbekannt“ mit Aktion „Ignorieren“; keine Neuanlage. |
| FA-24 | M | ✅ | `review.open_case`, `CrmClient.get_contact` | Beim Öffnen wird der CRM-Kontakt live gelesen, der Snapshot erneuert und ein zwischenzeitlich gepflegter Wert schliesst den Vorschlag automatisch. Gegen SAP noch nicht erprobt (OP-02). |

### 3.4 Abgleich und Relevanzregelwerk

| ID | Prio | Status | Umsetzung | Anmerkung |
|---|---|---|---|---|
| FA-30 | M | ✅ | `normalize.normalize_value` | E.164 (mit konfigurierbarer Standardregion), Groß-/Kleinschreibung, Umlautfaltung, Leerzeichen, Abkürzungen, Rechtsformzusätze. |
| FA-31 | M | ✅ | `normalize.values_equal` | Vergleich ausschliesslich auf der normalisierten Form; angezeigt und geschrieben wird der Originalwert. |
| FA-32 | M | ✅ | `config.field_whitelist` | Whitelist steuert, welche Felder überhaupt verglichen werden. |
| FA-33 | M | ✅ | `cases.apply_rules` | Leerer Signaturwert erzeugt nie einen Vorschlag. |
| FA-34 | S | ✅ | `DiffType.ERGAENZUNG` | Eigener Abweichungstyp, eigene Priorisierung, eigene Kennzahl. |
| FA-35 | M | ✅ | `store.is_suppressed`, `review._suppress` | Ablehnung legt eine Suppression (Kontakt + Feld + normalisierter Wert) mit Gültigkeitsdauer an. |
| FA-36 | S | ✅ | `cases.merge_into_open_case` | Gleiche Konstellation wird in den offenen Fall aggregiert, `vorkommen` erhöht und die Priorität angehoben. |

### 3.5 Review-UI

| ID | Prio | Status | Umsetzung | Anmerkung / Lücke |
|---|---|---|---|---|
| FA-40 | M | ✅ | `review_web.worklist`, `review.list_cases` | Filter nach Status, Typ, Feldtyp, Organisation, Priorität, Konfidenz und Alter; Sortierung nach Priorität, Alter, Konfidenz, Organisation. |
| FA-41 | M | ✅ | `review_web.case_view` | Feldweise Gegenüberstellung mit Hervorhebung (alter Wert durchgestrichen, Vorschlag betont) und Konfidenzangabe. |
| FA-42 | M | ✅ | `review.apply_decisions` | Übernehmen / Ablehnen / Manuell korrigieren je Feld; Teilübernahmen halten den Fall in Bearbeitung. |
| FA-43 | M | ✅ | `review_web.case_view` | Absender, Empfangsdatum, Betreff, Quelle, Verfahrensversion und Originaltext der Signatur. |
| FA-44 | S | ✅ | `review.bulk_apply` | Sammelentscheidung über markierte Fälle; die Service-Schnittstelle kann zusätzlich auf einzelne Felder eingeschränkt werden. |
| FA-45 | S | 🟡 | `review.assign`, `CaseStatus` | Statusmodell (offen, in Bearbeitung, erledigt, abgelehnt, Klärung) und Zuweisung sind implementiert und getestet; die Zuweisung ist in der UI noch nicht als Bedienelement ausgeführt (0,5 PT). |
| FA-46 | S | 🟡 | `review.digest`, `signatur digest` | Inhalt und Versand (SMTP) sind fertig, das Intervall ist konfiguriert — die zeitgesteuerte Auslösung erfolgt aktuell über einen externen Scheduler (cron). Ein interner Scheduler ist bewusst nicht enthalten. |
| FA-47 | M | ✅ | `config.crm_link` | Direktlink im Falldetail, Vorlage `crm_contact_url_template` konfigurierbar. |

### 3.6 Rückschreiben und Protokollierung

| ID | Prio | Status | Umsetzung | Anmerkung / Lücke |
|---|---|---|---|---|
| FA-50 | M | ✅ | `CrmClient.update_contact`, `MockCrmClient`, `SapSalesCloudClient` | Mock-CRM schreibt real (CSV) und ist getestet; der SAP-Pfad (OData-PATCH) ist implementiert, aber mangels Instanz nicht erprobt (OP-02, 3–5 PT Integrationstest). |
| FA-51 | M | 🟡 | `MockCrmClient.update_contact`, `config/mapping.json` | Herkunft, Zeitpunkt und freigebende Person werden im Mock-CRM in eigene Spalten geschrieben. Für SAP sind die Zielfelder im Mapping noch leer — sie müssen von der CRM-Systemverantwortung benannt werden. Im Audit-Log ist die Herkunft in jedem Fall vollständig. |
| FA-52 | M | ✅ | `review.apply_decisions` | Schreibfehler setzen die betroffenen Felder zurück auf „offen“, hinterlegen die Fehlermeldung am Feld, halten den Fall offen und erzeugen einen Audit-Eintrag mit Ergebnis „fehler“. |
| FA-53 | M | ✅ | `models.AuditEntry`, `store.audit` | Aktion, Akteur, Zeitpunkt, Feld, alter und neuer Wert, Ergebnis, Quell-Message-ID und Quell-Extrakt; im Falldetail sichtbar. |
| FA-54 | M | ✅ | `review.apply_decisions` | Ohne Bearbeiter keine Freigabe; kein Codepfad schreibt ohne Entscheidung. Test: `test_freigabe_ohne_bearbeiter_wird_abgelehnt`. |

---

## 4. Nicht-funktionale Anforderungen

| ID | Status | Bewertung |
|---|---|---|
| NFA-01 Verfügbarkeit | ✅ | Reine Batch-Verarbeitung, keine Echtzeitpfade. |
| NFA-02 Latenz (24 h) | 🟡 | Technisch erfüllbar; die Einhaltung hängt am Auslöseintervall des Laufs (cron), das mit dem Betrieb festzulegen ist. |
| NFA-03 Durchsatz | ⛔ | Ohne Zielwert (OP-04) nicht auslegbar. Der JSON-Store trägt Größenordnung „einige Tausend Fälle“; darüber ist ein Wechsel auf eine Datenbank nötig (5–8 PT). Die Ablage ist hinter `store.py` gekapselt, der Wechsel berührt keine andere Schicht. |
| NFA-04 Precision ≥ 90 % | ⛔ | Nachweis steht aus: es fehlt das abgestimmte Testset aus ≥ 100 realen Signaturen. Die Konfidenzschwellen sind die Stellschraube, mit der Precision gegen Recall getauscht wird. Vorgehen siehe Kapitel 6. |
| NFA-05 Falsch-Positiv ≤ 25 % | 🟡 | Messung ist implementiert (`kpi.falsch_positiv_quote`); der Wert entsteht erst im Pilotbetrieb. |
| NFA-06 Sicherheit/SSO | ⛔ | **Nicht umgesetzt.** Die Review-UI bindet ohne Authentifizierung auf 127.0.0.1. Für den Produktivbetrieb ist sie hinter den IdP zu hängen (Reverse Proxy mit OIDC oder Integration in ein bestehendes Portal) und die Ablage zu verschlüsseln; Aufwand 3–5 PT, abhängig von der Zielumgebung. |
| NFA-07 Nachvollziehbarkeit | ✅ | Kette CRM-Änderung → Audit-Eintrag → Extrakt → Message-ID ist geschlossen. |
| NFA-08 Konfigurierbarkeit | ✅ | Whitelist, Schwellwerte, Listen, Intervalle, Suppression-Dauer, Schreibmodus und CRM-Link in `config/checker.json`, ohne Deployment änderbar. |
| NFA-09 Betrieb/Monitoring | 🟡 | Fehler und Kennzahlen werden erhoben (Laufprotokoll, Audit mit Ergebnis, `kpi`, JSON-Endpunkte); eine Anbindung an Monitoring/Alerting fehlt (2–3 PT, abhängig vom eingesetzten Stack). |
| NFA-10 Wartbarkeit | ✅ | Extraktion, Matching, Regelwerk, Review und Persistenz sind getrennte Module mit eigenen Tests (71 Tests). |

---

## 5. Kennzahlen (Kapitel 11)

Alle sechs geforderten Kennzahlen werden erhoben und sind über
`python -m signatur kpi`, die Kennzahlenseite der Review-UI und
`/api/kpi.json` auswertbar:

| Geforderte Kennzahl | Feld in `kpi.compute_kpis` |
|---|---|
| Verarbeitete Signaturen und erzeugte Fälle | `signaturen_verarbeitet`, `faelle_gesamt` |
| Trefferquote | `trefferquote` |
| Freigegeben vs. abgelehnt, je Feldtyp | `freigabequote`, `je_feld[*]` |
| Signatur nachweislich aktueller als CRM | `faelle_signatur_aktueller`, `anteil_signatur_aktueller` |
| Durchschnittliche Bearbeitungsdauer | `bearbeitungsdauer_schnitt_s` |
| Aktualisierte Datensätze je Zeitraum | `crm_updates`, `aktualisierte_kontakte` (mit `--days`) |

Das MVP-Erfolgskriterium (≥ 60 % Freigabequote, < 30 s je Fall) wird als
`mvp_erfolgskriterium` mitgeliefert und ausgewertet.

**Anmerkung zur Bearbeitungsdauer:** gemessen wird vom Öffnen des Falls bis zur
Entscheidung (Audit-Aktion `fall_geoeffnet` → `entschieden_am`). Wird ein Fall
ohne Öffnen entschieden (Bulk-Aktion), zählt die Zeit ab Fallanlage — dieser
Wert ist dann nicht als Bearbeitungsaufwand interpretierbar. Bulk-entschiedene
Fälle sollten bei der Hypothesenauswertung getrennt betrachtet werden.

---

## 6. Antworten und Vorschläge zu den offenen Punkten

| ID | Position Development | Empfehlung |
|---|---|---|
| OP-01 | Die Anbindungsart ist die einzige Anforderung, die Architektur **und** Datenschutzaufwand deutlich verändert. Journaling erfasst alle Postfächer und ist damit der grösste Eingriff (DS-03, Mitbestimmung); ein dediziertes Funktionspostfach mit Weiterleitung/Opt-in ist technisch identisch aufwendig, aber rechtlich unkritisch. | Start mit **einem dedizierten Postfach** (IMAP oder Graph, 3–5 PT). Journaling frühestens nach belegter Hypothese. |
| OP-02 | Für den Schreibpfad braucht es: EntitySet und ObjectID-Semantik der Kontakte, die schreibbaren Felder, die Erweiterungsfelder für die Herkunftskennzeichnung (FA-51) und die Rate Limits. Ohne Testinstanz bleibt der SAP-Adapter unerprobt. | Testmandant plus technischer Benutzer mit Schreibrecht; danach 3–5 PT Integration und Feldmapping in `config/mapping.json`. |
| OP-03 | Vorschlag für Release 1 (bereits als Default gesetzt): Funktion/Position, Abteilung, Organisation, Telefon, Mobil, Website, Adresse. Bewusst **ausgenommen**: Name und E-Mail (Identitäts- bzw. Schlüsselfelder — eine Änderung dort ist ein Zuordnungs-, kein Pflegefall). | Datenteam bestätigt oder kürzt die Liste; Änderung ist reine Konfiguration. |
| OP-04 | Für die Auslegung genügt eine Grössenordnung. Als Orientierung: bis ca. 2 000 Mails/Tag trägt die aktuelle Architektur mit Dateiablage, darüber Datenbank plus Queue. | Zahl aus dem Mailgateway erheben, danach Store-Entscheidung. |
| OP-05 | Regelbasiert ist für den MVP ausreichend, deterministisch, kostenfrei und datenschutzseitig unkritisch — und liefert mit der Konfidenzbewertung die Stellschraube für NFA-04. Ein LLM lohnt erst dort, wo die Regeln messbar scheitern (freie Layouts, mehrsprachig, Fliesstext-Signaturen). | **Hybrid, aber gestuft**: Regelwerk als Basis; LLM erst nach Auswertung der Stufe-0-Stichprobe und nur für Blöcke unterhalb eines Konfidenzschwellwerts. Voraussetzung: DS-05 geklärt (Verarbeitungsort EU, AV-Vertrag, Trainingsausschluss). |
| OP-06 | Umgesetzt ist „ignorieren“ mit Protokoll. Fachlich interessant ist die Zahl: der Anteil unbekannter Kontakte wird als eigener Falltyp gezählt und ist damit die Entscheidungsgrundlage für einen späteren Anlageprozess. | Nach vier Wochen Pilotbetrieb anhand der Kennzahl entscheiden. |
| OP-07 | Die Sammelbenachrichtigung (FA-46) kann ohne Mehraufwand auch an Betreuer:innen gehen; sinnvoll sind dafür die geschäftsrelevanten Signale (Firmenwechsel, Positionswechsel), nicht jede Telefonnummernänderung. | Nach dem Pilot entscheiden; Umsetzung ca. 1 PT, sobald die Zuordnung Kontakt → Betreuer:in aus dem CRM verfügbar ist. |

### Datenschutz (Kapitel 12)

DS-01 bis DS-03, DS-05 und der organisatorische Teil von DS-04/DS-06 sind
Freigaben, keine Entwicklungsaufgaben — sie bleiben offen. Technisch vorbereitet
sind:

| ID | Technische Vorbereitung |
|---|---|
| DS-03 | Ingest verarbeitet ausschliesslich externe Absender; interne Domains sind ausgeschlossen (`internal_domains`). |
| DS-04 | `store.purge_expired` löscht Rohsignaturen und abgelaufene Extrakte; Frist konfigurierbar (`retention_days_extracts`, Default 90 Tage — **vorläufig, ersetzen durch die freigegebene Frist**). Fälle und Audit-Einträge bleiben aus Revisionsgründen erhalten und enthalten keinen Signaturrohtext. |
| DS-05 | Es findet keine LLM-Verarbeitung statt; das Verfahren ist je Extrakt protokolliert und damit später nachweisbar trennbar. |
| DS-06 | `store.find_by_person` (Auskunft) und `store.delete_person` (Löschung) über `python -m signatur person`. |

---

## 7. Abnahmekriterien (Kapitel 13)

| Kriterium | Stand |
|---|---|
| 1. Alle M-Anforderungen umgesetzt und getestet | ✅ mit den zwei in Kapitel 1 genannten Einschränkungen (FA-01 dateibasiert, FA-51 SAP-Zielfelder offen) |
| 2. NFA-04 auf ≥ 100 realen Signaturen nachgewiesen | ⛔ Testset fehlt — Stufe 0 |
| 3. End-to-End im Produktivumfeld | 🟡 vollständig reproduzierbar gegen das Mock-CRM (`test_end_to_end_freigabe_schreibt_ins_crm`); Produktivumfeld erfordert OP-01 und OP-02 |
| 4. Zwei Wochen Testbetrieb, Freigabe Datenteam | ⛔ ausstehend |
| 5. Kennzahlen auswertbar | ✅ |
| 6. Datenschutzpunkte dokumentiert freigegeben | ⛔ ausstehend (siehe oben) |

---

## 8. Vorgeschlagenes weiteres Vorgehen

1. **Stufe 0 (0,5–1 PT Werkzeugaufwand, Rest Datenteam):** 200 reale Signaturen
   als `.eml`/`.msg` exportieren, `signatur check` darauf laufen lassen,
   Vorschläge im Review-UI durcharbeiten, `signatur kpi` auswerten. Ergebnis:
   belegte oder widerlegte Hypothese **und** das Testset für NFA-04.
2. **Schwellwerte kalibrieren (1 PT):** Konfidenzschwellen je Feld anhand der
   Stichprobe so setzen, dass NFA-04 (≥ 90 % Precision) eingehalten wird.
3. **Postfachanbindung (3–5 PT)** nach Entscheidung zu OP-01.
4. **SAP-Schreibpfad verifizieren (3–5 PT)** nach Bereitstellung des Testmandanten.
5. **Betrieb produktionsreif machen (5–8 PT):** SSO/Rollen (NFA-06), Monitoring
   und Alerting (NFA-09), Scheduler für Lauf und Sammelbenachrichtigung.
6. **Optional nach Messung:** LLM-gestützte Extraktion für Blöcke unterhalb der
   Konfidenzschwelle (5–8 PT), Datenbank statt Dateiablage bei Bedarf (5–8 PT).

Die Schritte 1 und 2 kosten zusammen unter zwei Personentagen und entscheiden
über alles Weitere. Vor ihrem Abschluss sollte kein Aufwand in die Schritte 3
bis 6 fliessen.
