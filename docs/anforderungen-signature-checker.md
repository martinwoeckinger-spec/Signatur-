# Anforderungsdefinition: Signature Checker
**Version:** 0.1 (Entwurf zur Abstimmung)
**Datum:** 17.08.2026
**Auftraggeber:** APA-Comm, Produktmanagement
**Adressat:** Software Development
**Status:** Offen — Punkte in Kapitel 12 sind vor Umsetzungsbeginn zu klären

> Dieses Dokument ist die vom Produktmanagement übergebene Fassung 0.1.
> Es wird unverändert im Repository geführt. Die Antwort aus Entwicklungssicht
> (Abdeckung, Lücken, Aufwände, offene Punkte) steht in
> [`anforderungsabdeckung.md`](anforderungsabdeckung.md).

---

## 1. Zweck des Dokuments

Dieses Dokument beschreibt die fachlichen und technischen Anforderungen an ein Werkzeug ("Signature Checker") zur Extraktion von Kontaktdaten aus E-Mail-Signaturen, deren Abgleich mit CRM-Livedaten und die Aufbereitung von Abweichungen zur menschlichen Freigabe. Es dient als Grundlage für Aufwandsschätzung, Umsetzung und Abnahme.

## 2. Ausgangslage und Hypothese

**Hypothese:** Die Angaben in E-Mail-Signaturen unserer Ansprechpartner sind aktueller als die im CRM gepflegten Daten. Sie eignen sich daher als Impuls und Quelle für die Überprüfung und Aktualisierung des eigenen Datenbestands.

**Problem:** Der manuelle Abgleich ist nicht skalierbar. Ohne Automatisierung bleibt das in Signaturen enthaltene Aktualisierungspotenzial ungenutzt.

**Lösungsansatz:** Automatisierte Extraktion → automatisierter Abgleich → automatisierte Vorfilterung relevanter Abweichungen → aufbereitete Vorlage zur menschlichen Freigabe → Rückschreiben ins CRM.

> Die Hypothese ist bislang unbelegt. Der MVP ist so zu bauen, dass er die Hypothese messbar validiert (siehe Kapitel 11).

## 3. Ziele und Nicht-Ziele

### 3.1 Ziele

| ID | Ziel |
|---|---|
| Z-01 | Automatisierte Erkennung von Abweichungen zwischen Signaturdaten und CRM-Datensatz |
| Z-02 | Minimaler Bearbeitungsaufwand pro Fall für das Datenteam (Ziel: < 30 Sekunden) |
| Z-03 | Nachvollziehbare, revisionssichere Datenänderungen im CRM |
| Z-04 | Messbare Validierung der Hypothese (Anteil bestätigter Aktualisierungen) |

### 3.2 Nicht-Ziele (Out of Scope für Release 1)

- Vollautomatisches Schreiben ins CRM ohne menschliche Freigabe
- Anreicherung aus externen Quellen (Web, LinkedIn, Firmenbuch, Data Provider)
- Verarbeitung von Signaturbildern/Grafiken (OCR)
- Dublettenbereinigung, Neuanlage von Kontakten/Organisationen
- Auswertung von E-Mail-Inhalten (Body) außerhalb des Signaturblocks

## 4. Stakeholder und Rollen

| Rolle | Verantwortung |
|---|---|
| Datenteam APA | Prüft Vorschläge, gibt frei oder verwirft, Fachliche Abnahme |
| Produktmanagement | Fachliche Anforderungen, Priorisierung, Hypothesenauswertung |
| Development | Umsetzung, Betrieb, Monitoring |
| Datenschutzbeauftragter / Legal | Freigabe Verarbeitungskonzept, Rechtsgrundlage, Löschfristen |
| CRM-Systemverantwortung | Bereitstellung Lese-/Schreibschnittstelle, Feldmapping, Berechtigungen |
| Betriebsrat (falls einschlägig) | Mitbestimmung bei Zugriff auf Mitarbeiterpostfächer |

## 5. Begriffsdefinitionen

- **Signaturblock:** Der abschließende Kontaktdatenbereich einer E-Mail.
- **Extrakt:** Strukturierter Datensatz, der aus einem Signaturblock gewonnen wurde.
- **Match:** Eindeutige Zuordnung eines Extrakts zu einem CRM-Kontaktdatensatz.
- **Abweichung (Diff):** Feldbezogener Unterschied zwischen Extrakt und CRM-Wert nach Normalisierung.
- **Fall (Case):** Einheit zur Bearbeitung durch das Datenteam, bestehend aus Match + n Abweichungen.
- **Konfidenz:** Numerischer Wert (0–1) für die Verlässlichkeit von Extraktion bzw. Match.

## 6. Systemkontext

```
[E-Mail-Quelle]  ──►  [Ingest]  ──►  [Signatur-Extraktion]  ──►  [Matching]
                                                                     │
                                              [CRM (Lesen)]  ◄───────┤
                                                                     ▼
                                                            [Diff & Regelwerk]
                                                                     │
                                                                     ▼
                                                    [Review-UI Datenteam]
                                                                     │
                                              [CRM (Schreiben)] ◄────┘
                                                                     │
                                                                     ▼
                                                          [Audit-Log / KPI]
```

### 6.1 Schnittstellen

| ID | Schnittstelle | Richtung | Anmerkung |
|---|---|---|---|
| S-01 | E-Mail-Quelle (Postfach/Journal/Export) | Lesen | Anbindungsart offen, siehe OP-01 |
| S-02 | CRM — Kontaktsuche und -abruf | Lesen | Feldmapping erforderlich |
| S-03 | CRM — Kontaktaktualisierung | Schreiben | Nur nach Freigabe, mit Herkunftskennzeichnung |
| S-04 | Authentifizierung (SSO/IdP) | Lesen | Zugriff auf Review-UI nur für berechtigte Rollen |
| S-05 | Benachrichtigung (E-Mail/Chat) | Schreiben | Sammelbenachrichtigung offener Fälle |

## 7. Fachlicher Ablauf (End-to-End)

1. Ingest einer E-Mail aus definierter Quelle.
2. Identifikation und Isolation des Signaturblocks; Verwerfen von Zitaten, Disclaimern, Threads.
3. Extraktion strukturierter Felder inkl. Konfidenzwert je Feld.
4. Zuordnung zum CRM-Datensatz, primär über die E-Mail-Adresse des Absenders.
5. Normalisierung beider Seiten und Bildung der Abweichungen.
6. Anwendung des Relevanzregelwerks; irrelevante Abweichungen werden verworfen.
7. Erzeugung bzw. Aggregation eines Falls; Deduplizierung gegen bereits offene/entschiedene Fälle.
8. Vorlage im Review-UI: Gegenüberstellung CRM-Wert ↔ Vorschlag, feldweise entscheidbar.
9. Freigabe → Schreiben ins CRM; Ablehnung → Fall wird als geprüft geschlossen und für gleiche Konstellation unterdrückt.
10. Protokollierung aller Schritte und Kennzahlen.

## 8. Funktionale Anforderungen

Priorisierung nach MoSCoW: **M** = Must, **S** = Should, **C** = Could.

### 8.1 Ingest

| ID | Anforderung | Prio |
|---|---|---|
| FA-01 | Das System liest E-Mails aus einer konfigurierbaren Quelle ein. | M |
| FA-02 | Nur eingehende E-Mails externer Absender werden verarbeitet; interne Absender und definierte Domains sind ausschließbar (Blocklist/Allowlist). | M |
| FA-03 | Nur Metadaten und der erkannte Signaturblock werden persistiert, nicht der vollständige Nachrichtentext. | M |
| FA-04 | Automatische Antworten, Newsletter, Systemmails und No-Reply-Adressen werden verworfen. | S |
| FA-05 | Wiederholte Verarbeitung derselben Nachricht wird verhindert (Idempotenz über Message-ID). | M |

### 8.2 Extraktion

| ID | Anforderung | Prio |
|---|---|---|
| FA-10 | Das System erkennt den Signaturblock und trennt ihn von Body, Zitaten und Disclaimer. | M |
| FA-11 | Extrahierte Felder mindestens: Vorname, Nachname, akad. Titel, Funktion/Position, Abteilung, Organisation, Telefon, Mobil, E-Mail, Website, Adresse (Straße, PLZ, Ort, Land). | M |
| FA-12 | Je Feld wird ein Konfidenzwert ausgegeben; Felder unter konfigurierbarem Schwellwert werden nicht als Vorschlag verwendet. | M |
| FA-13 | Deutsch- und englischsprachige Signaturen werden unterstützt. | M |
| FA-14 | Mehrere Signaturen in einem Thread werden erkannt; nur die des aktuellen Absenders wird verwendet. | S |
| FA-15 | Das Extraktionsverfahren (Regelwerk und/oder LLM) ist austauschbar konfigurierbar; die verwendete Verfahrensversion wird je Extrakt protokolliert. | S |
| FA-16 | Signaturen in Bildern werden nicht ausgewertet, aber als "nicht auswertbar" markiert. | C |

### 8.3 Matching

| ID | Anforderung | Prio |
|---|---|---|
| FA-20 | Zuordnung primär über exakte Übereinstimmung der E-Mail-Adresse mit einem CRM-Kontakt. | M |
| FA-21 | Ohne E-Mail-Treffer: Fallback über Name + Organisationsdomain, mit reduzierter Konfidenz. | S |
| FA-22 | Mehrdeutige Treffer erzeugen keinen automatischen Vorschlag, sondern einen Fall vom Typ "Klärung". | M |
| FA-23 | Kein CRM-Treffer: Fall vom Typ "Unbekannter Kontakt" mit Option "Ignorieren" (keine Neuanlage in Release 1). | S |
| FA-24 | Der CRM-Wert wird zum Zeitpunkt der Fallanzeige erneut live abgerufen, um veraltete Vergleiche zu vermeiden. | M |

### 8.4 Abgleich und Relevanzregelwerk

| ID | Anforderung | Prio |
|---|---|---|
| FA-30 | Vor dem Vergleich werden beide Seiten normalisiert (Telefonnummern nach E.164, Groß-/Kleinschreibung, Leerzeichen, gängige Abkürzungen, Rechtsformzusätze). | M |
| FA-31 | Rein formatbedingte Unterschiede erzeugen keine Abweichung. | M |
| FA-32 | Die zu prüfenden Felder sind über eine konfigurierbare Whitelist steuerbar. | M |
| FA-33 | Ein leerer Signaturwert überschreibt nie einen gefüllten CRM-Wert und erzeugt keinen Vorschlag. | M |
| FA-34 | Ein leeres CRM-Feld mit gefülltem Signaturwert wird als Ergänzung ausgewiesen (eigener Abweichungstyp). | S |
| FA-35 | Abweichungen mit identischer Konstellation, die bereits abgelehnt wurden, werden erneut unterdrückt (Suppression-Liste). | M |
| FA-36 | Wiederholte gleiche Vorschläge aus mehreren E-Mails werden zu einem Fall aggregiert und erhöhen dessen Priorität. | S |

### 8.5 Review-UI (Datenteam)

| ID | Anforderung | Prio |
|---|---|---|
| FA-40 | Arbeitsliste offener Fälle mit Filter (Priorität, Feldtyp, Organisation, Alter, Konfidenz) und Sortierung. | M |
| FA-41 | Feldweise Gegenüberstellung CRM-Wert ↔ Vorschlag mit visueller Hervorhebung der Differenz. | M |
| FA-42 | Entscheidung je Feld: Übernehmen / Ablehnen / Manuell korrigieren. Teilübernahmen sind möglich. | M |
| FA-43 | Anzeige des Kontextes: Absender, Empfangsdatum, extrahierter Signaturtext im Original. | M |
| FA-44 | Bulk-Aktionen über mehrere Fälle bzw. Felder. | S |
| FA-45 | Fallzuweisung an Bearbeiter und Statusverwaltung (offen, in Bearbeitung, erledigt, abgelehnt, Klärung). | S |
| FA-46 | Sammelbenachrichtigung über neue Fälle in konfigurierbarem Intervall. | S |
| FA-47 | Direktlink zum Kontaktdatensatz im CRM. | M |

### 8.6 Rückschreiben und Protokollierung

| ID | Anforderung | Prio |
|---|---|---|
| FA-50 | Nach Freigabe schreibt das System die Änderung über die CRM-Schnittstelle zurück. | M |
| FA-51 | Jede Änderung wird im CRM als systemseitig herkunftsgekennzeichnet ("Signature Checker") mit Datum und freigebender Person hinterlegt. | M |
| FA-52 | Schreibfehler werden erkannt, dem Bearbeiter gemeldet und der Fall bleibt offen (kein stiller Verlust). | M |
| FA-53 | Vollständiges Audit-Log: Was wurde wann von wem aufgrund welcher Quelle geändert (alter Wert, neuer Wert). | M |
| FA-54 | Kein automatisches Schreiben ohne menschliche Freigabe in Release 1. | M |

## 9. Datenmodell (fachlich)

| Entität | Wesentliche Attribute |
|---|---|
| SignatureExtract | id, message_id, empfangen_am, absender_email, rohtext_signatur, felder[], konfidenz[], verfahrensversion |
| CrmSnapshot | id, crm_kontakt_id, abgerufen_am, felder[] |
| Case | id, typ (Update/Ergänzung/Klärung/Unbekannt), crm_kontakt_id, status, prio, erstellt_am, bearbeiter, entschieden_am |
| Diff | id, case_id, feld, wert_crm, wert_signatur, konfidenz, entscheidung, endwert |
| AuditEntry | id, case_id, aktion, akteur, zeitpunkt, alter_wert, neuer_wert, ergebnis |
| Suppression | crm_kontakt_id, feld, abgelehnter_wert, gültig_bis |

## 10. Nicht-funktionale Anforderungen

| ID | Anforderung |
|---|---|
| NFA-01 | **Verfügbarkeit:** Werktags 08:00–18:00; keine Echtzeitanforderung, Batch-Verarbeitung zulässig. |
| NFA-02 | **Latenz:** Fall steht spätestens 24 h nach E-Mail-Eingang im Review-UI. |
| NFA-03 | **Durchsatz:** Auslegung auf das erwartete tägliche E-Mail-Volumen mit Faktor 3 Reserve; konkreter Zielwert siehe OP-04. |
| NFA-04 | **Extraktionsqualität:** Precision der vorgeschlagenen Feldwerte ≥ 90 % auf einem abgestimmten Testset (Abnahmekriterium). |
| NFA-05 | **Falsch-Positiv-Rate:** Anteil abgelehnter Vorschläge ≤ 25 % nach Einschwingphase. |
| NFA-06 | **Sicherheit:** Zugriff nur authentifiziert über SSO, rollenbasiert; Transport- und Speicherverschlüsselung. |
| NFA-07 | **Nachvollziehbarkeit:** Jede CRM-Änderung ist bis zur Ursprungs-E-Mail rückverfolgbar. |
| NFA-08 | **Konfigurierbarkeit:** Feld-Whitelist, Schwellwerte, Block-/Allowlists und Intervalle ohne Deployment änderbar. |
| NFA-09 | **Betrieb:** Monitoring von Verarbeitungsfehlern, Schnittstellenfehlern und Warteschlangenlänge inkl. Alerting. |
| NFA-10 | **Wartbarkeit:** Extraktion, Matching und Regelwerk sind getrennte, einzeln testbare Komponenten. |

## 11. Kennzahlen zur Hypothesenvalidierung

Verpflichtend ab Release 1 zu erheben und auswertbar bereitzustellen:

- Anzahl verarbeiteter Signaturen und daraus erzeugter Fälle
- Anteil der Fälle mit mindestens einer relevanten Abweichung ("Trefferquote")
- Anteil freigegebener vs. abgelehnter Vorschläge, je Feldtyp
- Anteil der Fälle, in denen die Signatur nachweislich aktueller war als das CRM
- Durchschnittliche Bearbeitungsdauer je Fall
- Anzahl der im CRM tatsächlich aktualisierten Datensätze je Zeitraum

**Erfolgskriterium MVP (Vorschlag, abzustimmen):** ≥ 60 % der vorgelegten Vorschläge werden freigegeben, bei einer durchschnittlichen Bearbeitungsdauer < 30 Sekunden je Fall.

## 12. Datenschutz und Compliance

Die Verarbeitung betrifft personenbezogene Daten von Ansprechpartnern sowie ggf. von eigenen Beschäftigten (Postfachzugriff). Vor Umsetzungsbeginn zwingend zu klären:

| ID | Punkt |
|---|---|
| DS-01 | Rechtsgrundlage der Verarbeitung und Dokumentation im Verzeichnis von Verarbeitungstätigkeiten |
| DS-02 | Notwendigkeit einer Datenschutz-Folgenabschätzung |
| DS-03 | Umfang des Postfachzugriffs, Information der betroffenen Beschäftigten, ggf. Mitbestimmung |
| DS-04 | Löschfristen für Rohsignaturen, Extrakte und abgelehnte Vorschläge |
| DS-05 | Zulässigkeit einer LLM-gestützten Extraktion inkl. Verarbeitungsort, Auftragsverarbeitung und Ausschluss von Trainingsnutzung |
| DS-06 | Umsetzung von Betroffenenrechten (Auskunft, Löschung) auf den gespeicherten Extrakten |

## 13. Abnahmekriterien

Die Lieferung gilt als abgenommen, wenn:

1. Alle mit **M** priorisierten funktionalen Anforderungen umgesetzt und fachlich getestet sind.
2. NFA-04 auf einem gemeinsam definierten Testset aus mindestens 100 realen Signaturen nachgewiesen ist.
3. Ein vollständiger End-to-End-Durchlauf (E-Mail → Fall → Freigabe → CRM-Änderung → Audit-Eintrag) im Produktivumfeld reproduzierbar funktioniert.
4. Das Datenteam einen Testbetrieb über mindestens zwei Wochen fachlich freigibt.
5. Die Kennzahlen aus Kapitel 11 auswertbar vorliegen.
6. Die Punkte aus Kapitel 12 dokumentiert freigegeben sind.

## 14. Offene Punkte

| ID | Offener Punkt | Zu klären mit |
|---|---|---|
| OP-01 | Anbindungsart und Umfang der E-Mail-Quelle (welche Postfächer, Journaling vs. Einzelpostfach, Opt-in) | IT, Datenschutz |
| OP-02 | Ziel-CRM, verfügbare Lese-/Schreibschnittstelle, Feldmapping, Rate Limits | CRM-Systemverantwortung |
| OP-03 | Verbindliche Feld-Whitelist für Release 1 | Datenteam |
| OP-04 | Erwartetes E-Mail-Volumen pro Tag als Auslegungsgröße | Produktmanagement |
| OP-05 | Extraktionsverfahren: regelbasiert, LLM-gestützt oder hybrid — inkl. Kosten- und Datenschutzbewertung | Development, Datenschutz |
| OP-06 | Umgang mit Kontakten ohne CRM-Treffer (ignorieren vs. späterer Anlageprozess) | Datenteam |
| OP-07 | Ob und wie eine Rückmeldung an den Vertrieb/Betreuer erfolgen soll | Produktmanagement |

## 15. Umsetzungsvorschlag in Stufen

| Stufe | Inhalt |
|---|---|
| Stufe 0 — Vorabprüfung | Manuelle Auswertung einer Stichprobe (z. B. 200 Signaturen) zur Vorabvalidierung der Hypothese, bevor Entwicklungsaufwand entsteht |
| Stufe 1 — MVP | Eine E-Mail-Quelle, regelbasierte Extraktion, Matching über E-Mail-Adresse, reduzierte Feld-Whitelist, Review-UI, manuelles Rückschreiben mit Direktlink ins CRM |
| Stufe 2 | Schreibende CRM-Schnittstelle, Suppression-Liste, Bulk-Aktionen, Kennzahlen-Dashboard |
| Stufe 3 | Erweiterte Extraktion (LLM, mehrsprachig), Fallback-Matching, Priorisierung, Anbindung weiterer Quellen |

Stufe 0 wird ausdrücklich empfohlen: Sie kostet wenig, liefert das Testset für NFA-04 und entscheidet, ob sich die Umsetzung überhaupt lohnt.
