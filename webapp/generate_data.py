"""Erzeugt webapp/data.js mit eingebetteten Demodaten (CRM + Demo-Mails).

Enthaelt die 5 Beispiel-.eml als Strings sowie eine kleine, echte .msg
(via tests/cfb_writer) als Base64 – damit die Browser-App ohne Server sowohl
.eml- als auch .msg-Parsing demonstriert.
"""
from __future__ import annotations

import base64
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from cfb_writer import build_msg  # noqa: E402


def crm_rows() -> list[dict]:
    with (ROOT / "data" / "crm_mock.csv").open(encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def demo_emls() -> list[dict]:
    out = []
    for p in sorted((ROOT / "samples").glob("*.eml")):
        out.append({"name": p.name, "type": "eml", "content": p.read_text(encoding="utf-8")})
    return out


def demo_msg() -> dict:
    body = (
        "Guten Tag,\r\n\r\nwir benoetigen ein Angebot ueber 200 Einheiten.\r\n\r\n"
        "Mit freundlichen Gruessen\r\n"
        "Jens Hartmann\r\n"
        "Einkaufsleiter\r\n"
        "Stahlwerk Mitte GmbH\r\n"
        "Tel: +49 201 88 77 66\r\n"
        "Mobil: +49 172 6655443\r\n"
        "jens.hartmann@stahlwerk-mitte.de\r\n"
        "www.stahlwerk-mitte.de\r\n"
    )
    props = {
        "0037": "Angebotsanfrage 200 Einheiten",
        "1000": body,
        "0C1A": "Jens Hartmann",
        "0C1F": "jens.hartmann@stahlwerk-mitte.de",
    }
    raw = build_msg(props)
    return {"name": "06_jens_hartmann.msg", "type": "msg",
            "b64": base64.b64encode(raw).decode("ascii")}


def main() -> None:
    crm = crm_rows()
    emls = demo_emls()
    msg = demo_msg()
    parts = [
        "/* Auto-generiert von webapp/generate_data.py – nicht von Hand aendern. */",
        "window.CRM_DATA = " + json.dumps(crm, ensure_ascii=False, indent=2) + ";",
        "window.DEMO_EMAILS = " + json.dumps(emls, ensure_ascii=False) + ";",
        "window.DEMO_MSG = " + json.dumps(msg, ensure_ascii=False) + ";",
    ]
    out = ROOT / "webapp" / "data.js"
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"geschrieben: {out} ({out.stat().st_size} Bytes) – "
          f"{len(crm)} CRM, {len(emls)} eml, 1 msg")


if __name__ == "__main__":
    main()
