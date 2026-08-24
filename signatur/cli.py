"""Kommandozeilen-Einstieg für den Signatur-/CRM-Workflow."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import get_config
from .crm import get_client
from .kpi import compute_kpis, format_kpis
from .notifier import build_notification
from .pipeline import run_pipeline
from .sender import get_sender
from .store import CheckerStore


def _cmd_run(args: argparse.Namespace) -> int:
    crm_client = get_client(args.crm, csv_path=args.crm_csv)
    report = run_pipeline(args.input, crm_client)

    recipients = [r.strip() for r in (args.to or "").split(",") if r.strip()]
    draft = build_notification(report, to=recipients or ["<empfänger>"],
                               subject=args.subject)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reconciliation.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "notification.md").write_text(draft.text, encoding="utf-8")
    (out_dir / "notification.html").write_text(draft.html, encoding="utf-8")
    (out_dir / "draft.json").write_text(
        json.dumps(draft.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Optionaler echter Versand per SMTP
    send_result: dict | None = None
    if args.send == "smtp":
        if not recipients:
            print("FEHLER: --send smtp benötigt --to <empfänger>.", file=sys.stderr)
            return 2
        sender = get_sender("smtp", host=args.smtp_host or "",
                            from_addr=args.smtp_from or "")
        send_result = sender.send(draft)
        (out_dir / "send_result.json").write_text(
            json.dumps(send_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    summary = report.to_dict()["summary"]
    print(f"CRM-Backend : {crm_client.name}")
    print(f"Verarbeitet : {summary['processed']}")
    print(f"Neue Kontakte: {summary['new_contacts']}")
    print(f"Mit Änderungen: {summary['with_changes']}")
    print(f"Übersprungen: {summary['skipped']}")
    print(f"\nErgebnisse geschrieben nach: {out_dir.resolve()}")
    print("  - reconciliation.json (strukturiertes Ergebnis)")
    print("  - notification.md / .html (Hinweis-Vorschau)")
    print("  - draft.json (Payload für den Gmail-Entwurf)")
    if send_result:
        print(f"\nVersand (SMTP): {send_result['status']} an "
              f"{', '.join(send_result['to'])}")
        print(f"  Message-ID: {send_result['message_id']}")
        print("  - send_result.json (Versandprotokoll)")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from .web import DEFAULT_INPUT, serve
    serve(host=args.host, port=args.port,
          input_dir=args.input or str(DEFAULT_INPUT), crm=args.crm)
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from .web import DEFAULT_INPUT, export_static
    out = export_static(args.out, args.input or str(DEFAULT_INPUT), args.crm)
    print(f"Statische HTML-Demo geschrieben: {out.resolve()} "
          f"({out.stat().st_size} Bytes)")
    print("Im Browser öffnen – Tabs/Ansichten funktionieren ohne Server.")
    return 0


# --- Signature Checker: Fallverarbeitung, Review, Kennzahlen -----------------

def _checker_context(args: argparse.Namespace):
    """Konfiguration, Store und CRM-Client für die Checker-Befehle."""
    config = get_config(getattr(args, "config", None) or None, reload=True)
    if getattr(args, "store", None):
        config.store_path = args.store
    store = CheckerStore(config.store_file())
    crm_client = get_client(args.crm, csv_path=getattr(args, "crm_csv", None))
    return config, store, crm_client


def _cmd_check(args: argparse.Namespace) -> int:
    from .checker import run_checker

    config, store, crm_client = _checker_context(args)
    report = run_checker(args.input, crm_client, store, config)
    data = report.to_dict()
    print(f"Quelle        : {args.input}")
    print(f"CRM-Backend   : {crm_client.name}")
    print(f"Konfiguration : {config.source_path or 'Defaults'}")
    print(f"Store         : {config.store_file()}")
    print("")
    print(f"Gelesen             : {data['gelesen']}")
    print(f"Verarbeitet         : {data['verarbeitet']}")
    print(f"Verworfen (Ingest)  : {data['verworfen']}")
    print(f"Dubletten (FA-05)   : {data['dubletten']}")
    print(f"Nicht auswertbar    : {data['nicht_auswertbar']}")
    print(f"Neue Fälle          : {data['faelle_neu_anzahl']}")
    print(f"Aggregierte Fälle   : {data['faelle_aggregiert_anzahl']}")
    print(f"Ohne Abweichung     : {data['ohne_abweichung']}")
    for eintrag in report.uebersprungen:
        print(f"  übersprungen: {eintrag['quelle']} – {eintrag['grund']}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nProtokoll geschrieben: {args.json}")
    return 0


def _cmd_cases(args: argparse.Namespace) -> int:
    from .review import ReviewService

    config, store, crm_client = _checker_context(args)
    service = ReviewService(store, crm_client, config)
    cases = service.list_cases(status=args.status or None, typ=args.typ or None,
                               feld=args.feld or None,
                               organisation=args.organisation or None,
                               min_prio=args.min_prio, sort=args.sort)
    if args.case_id:
        case = store.get_case(args.case_id)
        if case is None:
            print(f"Fall '{args.case_id}' nicht gefunden.", file=sys.stderr)
            return 1
        print(json.dumps(case.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.json:
        print(json.dumps([c.to_dict() for c in cases], ensure_ascii=False, indent=2))
        return 0
    if not cases:
        print("Keine Fälle für diesen Filter.")
        return 0
    print(f"{'PRIO':>4}  {'TYP':<10} {'KONTAKT':<26} {'ORGANISATION':<24} FELDER")
    for case in cases:
        felder = ", ".join(config.label_for(d.feld) for d in case.offene_diffs) or "—"
        print(f"{case.prio:>4}  {case.typ.value:<10} "
              f"{(case.kontakt_name or case.absender_email)[:26]:<26} "
              f"{(case.organisation or '—')[:24]:<24} {felder}")
        print(f"      {case.id} · Status {case.status.value} · "
              f"Vorkommen {case.vorkommen}")
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    from .review import ReviewService

    config, store, crm_client = _checker_context(args)
    service = ReviewService(store, crm_client, config)
    if args.ignore:
        case = service.ignore_case(args.case_id, args.actor, grund=args.reason)
        if case is None:
            print(f"Fall '{args.case_id}' nicht gefunden.", file=sys.stderr)
            return 1
        print(f"Fall {case.id} geschlossen (ignoriert).")
        return 0

    entscheidungen: dict[str, dict[str, str]] = {}
    for feld in (args.accept or "").split(","):
        if feld.strip():
            entscheidungen[feld.strip()] = {"entscheidung": "übernehmen"}
    for feld in (args.reject or "").split(","):
        if feld.strip():
            entscheidungen[feld.strip()] = {"entscheidung": "ablehnen"}
    for eintrag in args.manual or []:
        if "=" not in eintrag:
            print(f"--manual erwartet FELD=WERT (erhalten: {eintrag!r})",
                  file=sys.stderr)
            return 2
        feld, wert = eintrag.split("=", 1)
        entscheidungen[feld.strip()] = {"entscheidung": "manuell", "wert": wert}
    if not entscheidungen:
        print("Keine Entscheidung angegeben (--accept/--reject/--manual/--ignore).",
              file=sys.stderr)
        return 2

    result = service.apply_decisions(args.case_id, entscheidungen, args.actor)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def _cmd_review(args: argparse.Namespace) -> int:
    from .review_web import DEFAULT_INPUT, serve as serve_review

    config, _store, _crm = _checker_context(args)
    serve_review(host=args.host, port=args.port, crm=args.crm,
                 input_dir=args.input or str(DEFAULT_INPUT), config=config,
                 actor=args.actor)
    return 0


def _cmd_kpi(args: argparse.Namespace) -> int:
    config, store, _crm = _checker_context(args)
    kpis = compute_kpis(store, config, zeitraum_tage=args.days)
    if args.json:
        print(json.dumps(kpis, ensure_ascii=False, indent=2))
    else:
        print(format_kpis(kpis))
    return 0


def _cmd_digest(args: argparse.Namespace) -> int:
    from .review import ReviewService

    config, store, crm_client = _checker_context(args)
    service = ReviewService(store, crm_client, config)
    digest = service.digest(args.hours)
    print(digest["text"])
    recipients = [r.strip() for r in (args.to or "").split(",") if r.strip()]
    if args.send == "smtp" and recipients:
        from .notifier import NotificationDraft

        draft = NotificationDraft(
            to=recipients,
            subject=f"Signature Checker – {digest['neu']} neue Fälle",
            text=digest["text"],
            html="<pre>" + digest["text"] + "</pre>")
        sender = get_sender("smtp", host=args.smtp_host or "",
                            from_addr=args.smtp_from or "")
        result = sender.send(draft)
        print(f"\nVersand: {result['status']} an {', '.join(result['to'])}")
    return 0


def _cmd_purge(args: argparse.Namespace) -> int:
    config, store, _crm = _checker_context(args)
    tage = args.days if args.days is not None else config.retention_days_extracts
    result = store.purge_expired(tage)
    print(f"Aufbewahrungsfrist {tage} Tage angewendet (DS-04): "
          f"{result['extrakte_bereinigt']} Rohsignatur(en) gelöscht, "
          f"{result['extrakte_geloescht']} Extrakt(e) entfernt.")
    return 0


def _cmd_person(args: argparse.Namespace) -> int:
    config, store, _crm = _checker_context(args)
    if args.delete:
        result = store.delete_person(args.email)
        print(f"Gelöscht (DS-06): {result['extrakte']} Extrakt(e), "
              f"{result['faelle']} Fall/Fälle. Audit-Einträge bleiben erhalten.")
        return 0
    daten = store.find_by_person(args.email)
    print(json.dumps(daten, ensure_ascii=False, indent=2))
    return 0


def _add_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--crm", default="mock", choices=["mock", "sap"],
                        help="CRM-Backend (Default: mock).")
    parser.add_argument("--crm-csv", default=None,
                        help="CSV-Pfad für das Mock-CRM (optional).")
    parser.add_argument("--config", default=None,
                        help="Pfad zur checker.json (sonst config/checker.json).")
    parser.add_argument("--store", default=None,
                        help="Pfad zur Store-Datei (überschreibt die Konfiguration).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signatur",
        description="Abgleich von E-Mail-Signaturen mit CRM-Daten.",
    )
    parser.add_argument("--version", action="version",
                        version=f"signatur {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Workflow ausführen (Mails -> Abgleich -> Hinweis).")
    run.add_argument("--input", required=True,
                     help="Ordner oder Datei mit .eml/.msg-Mails.")
    run.add_argument("--crm", default="mock", choices=["mock", "sap"],
                     help="CRM-Backend (Default: mock).")
    run.add_argument("--crm-csv", default=None,
                     help="CSV-Pfad für das Mock-CRM (optional).")
    run.add_argument("--to", default="",
                     help="Empfänger des Hinweises (Komma-getrennt).")
    run.add_argument("--subject", default=None, help="Betreff des Hinweises (optional).")
    run.add_argument("--send", default="none", choices=["none", "smtp"],
                     help="Versand: 'none' (nur Dateien) oder 'smtp' (echter Versand).")
    run.add_argument("--smtp-host", default=None,
                     help="SMTP-Host (sonst SIGNATUR_SMTP_HOST).")
    run.add_argument("--smtp-from", default=None,
                     help="Absenderadresse (sonst SIGNATUR_SMTP_FROM/USER).")
    run.add_argument("--out", default="out", help="Ausgabeordner (Default: out).")
    run.set_defaults(func=_cmd_run)

    serve = sub.add_parser("serve", help="Web-Oberfläche zum Vorführen starten.")
    serve.add_argument("--host", default="127.0.0.1", help="Host (Default: 127.0.0.1).")
    serve.add_argument("--port", type=int, default=8000, help="Port (Default: 8000).")
    serve.add_argument("--input", default=None,
                       help="Start-Eingabeordner (Default: samples).")
    serve.add_argument("--crm", default="mock", choices=["mock", "sap"],
                       help="CRM-Backend (Default: mock).")
    serve.set_defaults(func=_cmd_serve)

    export = sub.add_parser("export",
                            help="Eigenständige HTML-Demo mit Daten erzeugen.")
    export.add_argument("--input", default=None,
                        help="Eingabeordner (.eml/.msg; Default: samples).")
    export.add_argument("--crm", default="mock", choices=["mock", "sap"],
                        help="CRM-Backend (Default: mock).")
    export.add_argument("--out", default="docs/demo.html",
                        help="Zieldatei (Default: docs/demo.html).")
    export.set_defaults(func=_cmd_export)

    # --- Signature Checker ---------------------------------------------
    check = sub.add_parser(
        "check", help="Mails einlesen und Fälle erzeugen (Ingest → Extrakt → Fall).")
    check.add_argument("--input", required=True,
                       help="Ordner oder Datei mit .eml/.msg-Mails.")
    check.add_argument("--json", default=None,
                       help="Laufprotokoll zusätzlich als JSON schreiben.")
    _add_store_args(check)
    check.set_defaults(func=_cmd_check)

    cases = sub.add_parser("cases", help="Arbeitsliste der Fälle anzeigen.")
    cases.add_argument("--status", default="offen",
                       help="Statusfilter ('offen', 'erledigt', … oder '' für alle).")
    cases.add_argument("--typ", default=None,
                       help="Falltyp (Update/Ergänzung/Klärung/Unbekannt).")
    cases.add_argument("--feld", default=None, help="Nur Fälle mit diesem Feld.")
    cases.add_argument("--organisation", default=None, help="Organisation enthält …")
    cases.add_argument("--min-prio", type=int, default=None, help="Mindestpriorität.")
    cases.add_argument("--sort", default="prio",
                       choices=["prio", "alter", "konfidenz", "organisation"])
    cases.add_argument("--case-id", default=None, help="Einen Fall im Detail ausgeben.")
    cases.add_argument("--json", action="store_true", help="Ausgabe als JSON.")
    _add_store_args(cases)
    cases.set_defaults(func=_cmd_cases)

    decide = sub.add_parser("decide", help="Feldweise entscheiden (Freigabe/Ablehnung).")
    decide.add_argument("--case-id", required=True, help="ID des Falls.")
    decide.add_argument("--actor", required=True,
                        help="Freigebende Person (wird protokolliert).")
    decide.add_argument("--accept", default="",
                        help="Komma-getrennte Felder, die übernommen werden.")
    decide.add_argument("--reject", default="",
                        help="Komma-getrennte Felder, die abgelehnt werden.")
    decide.add_argument("--manual", action="append", default=[],
                        metavar="FELD=WERT", help="Manuell korrigierter Wert.")
    decide.add_argument("--ignore", action="store_true",
                        help="Fall ohne CRM-Änderung schliessen.")
    decide.add_argument("--reason", default="", help="Begründung (nur mit --ignore).")
    _add_store_args(decide)
    decide.set_defaults(func=_cmd_decide)

    review = sub.add_parser("review", help="Review-UI für das Datenteam starten.")
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=8010)
    review.add_argument("--input", default=None,
                        help="Eingabeordner für 'Neue Mails einlesen'.")
    review.add_argument("--actor", default="",
                        help="Vorbelegter Bearbeitername in der UI.")
    _add_store_args(review)
    review.set_defaults(func=_cmd_review)

    kpi = sub.add_parser("kpi", help="Kennzahlen zur Hypothesenvalidierung (Kap. 11).")
    kpi.add_argument("--days", type=int, default=None,
                     help="Nur die letzten n Tage auswerten.")
    kpi.add_argument("--json", action="store_true", help="Ausgabe als JSON.")
    _add_store_args(kpi)
    kpi.set_defaults(func=_cmd_kpi)

    digest = sub.add_parser("digest", help="Sammelbenachrichtigung über neue Fälle.")
    digest.add_argument("--hours", type=float, default=None,
                        help="Zeitfenster in Stunden (Default: Konfiguration).")
    digest.add_argument("--to", default="", help="Empfänger (Komma-getrennt).")
    digest.add_argument("--send", default="none", choices=["none", "smtp"])
    digest.add_argument("--smtp-host", default=None)
    digest.add_argument("--smtp-from", default=None)
    _add_store_args(digest)
    digest.set_defaults(func=_cmd_digest)

    purge = sub.add_parser("purge", help="Aufbewahrungsfristen anwenden (DS-04).")
    purge.add_argument("--days", type=int, default=None,
                       help="Aufbewahrung in Tagen (Default: Konfiguration).")
    _add_store_args(purge)
    purge.set_defaults(func=_cmd_purge)

    person = sub.add_parser("person",
                            help="Betroffenenrechte: Auskunft/Löschung (DS-06).")
    person.add_argument("--email", required=True, help="E-Mail-Adresse der Person.")
    person.add_argument("--delete", action="store_true",
                        help="Datensätze löschen statt nur anzeigen.")
    _add_store_args(person)
    person.set_defaults(func=_cmd_person)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
