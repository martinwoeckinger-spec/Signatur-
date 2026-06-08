"""Kommandozeilen-Einstieg für den Signatur-/CRM-Workflow."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .crm import get_client
from .notifier import build_notification
from .pipeline import run_pipeline
from .sender import get_sender


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
