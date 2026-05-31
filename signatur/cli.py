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
    run.add_argument("--out", default="out", help="Ausgabeordner (Default: out).")
    run.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
