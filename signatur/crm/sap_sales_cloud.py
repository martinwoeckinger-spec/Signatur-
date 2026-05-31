"""Adapter für SAP Sales Cloud (OData).

Vorbereitet für den Echtbetrieb. Konfiguration über Umgebungsvariablen:

    SAP_SALESCLOUD_BASE_URL   z. B. https://my3xxxxx.crm.ondemand.com
    SAP_SALESCLOUD_USER       Basic-Auth-Benutzer (optional bei Token)
    SAP_SALESCLOUD_PASSWORD   Basic-Auth-Passwort (optional bei Token)
    SAP_SALESCLOUD_TOKEN      Bearer-Token (optional, statt Basic-Auth)
    SAP_SALESCLOUD_CONTACT_SET  OData-EntitySet (Default: ContactCollection)

Das Feld-Mapping (Signatur → SAP) liegt in `config/mapping.json` und kann ohne
Codeänderung angepasst werden. Diese Klasse nutzt nur die Standardbibliothek
(`urllib`), um abhängigkeitsfrei zu bleiben.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from ..models import CrmContact
from .base import CrmClient

_MAPPING_PATH = Path(__file__).resolve().parents[2] / "config" / "mapping.json"


def _load_sap_field_map() -> dict[str, str]:
    """Signatur-Feld -> SAP-OData-Feld (aus config/mapping.json)."""
    try:
        data = json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))
        return data.get("sap_sales_cloud", {})
    except (OSError, json.JSONDecodeError):
        return {}


class SapSalesCloudClient(CrmClient):
    """Liest Kontakte aus SAP Sales Cloud über die OData-Schnittstelle."""

    name = "sap-sales-cloud"

    def __init__(
        self,
        base_url: str | None = None,
        user: str | None = None,
        password: str | None = None,
        token: str | None = None,
        contact_set: str | None = None,
        timeout: int = 30,
        **_ignored,
    ) -> None:
        self.base_url = (base_url or os.getenv("SAP_SALESCLOUD_BASE_URL", "")).rstrip("/")
        self.user = user or os.getenv("SAP_SALESCLOUD_USER", "")
        self.password = password or os.getenv("SAP_SALESCLOUD_PASSWORD", "")
        self.token = token or os.getenv("SAP_SALESCLOUD_TOKEN", "")
        self.contact_set = (
            contact_set
            or os.getenv("SAP_SALESCLOUD_CONTACT_SET", "ContactCollection")
        )
        self.timeout = timeout
        self.field_map = _load_sap_field_map()
        if not self.base_url:
            raise ValueError(
                "SAP Sales Cloud: SAP_SALESCLOUD_BASE_URL ist nicht gesetzt."
            )

    # --- HTTP -------------------------------------------------------------
    def _auth_header(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.user:
            raw = f"{self.user}:{self.password}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        return {}

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}/{path.lstrip('/')}?{query}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            **self._auth_header(),
        })
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    # --- Mapping ----------------------------------------------------------
    def _to_contact(self, rec: dict[str, Any]) -> CrmContact:
        fm = self.field_map
        def g(sig_field: str) -> str:
            sap_field = fm.get(sig_field)
            if not sap_field:
                return ""
            return str(rec.get(sap_field, "") or "").strip()

        full = g("full_name") or " ".join(
            x for x in [g("first_name"), g("last_name")] if x
        )
        return CrmContact(
            crm_id=g("crm_id"),
            full_name=full,
            first_name=g("first_name"),
            last_name=g("last_name"),
            job_title=g("job_title"),
            department=g("department"),
            company=g("company"),
            email=g("email").lower(),
            phone=g("phone"),
            mobile=g("mobile"),
            website=g("website"),
            source=self.name,
        )

    def _query(self, odata_filter: str) -> Optional[CrmContact]:
        try:
            data = self._get(self.contact_set, {
                "$filter": odata_filter,
                "$top": "1",
                "$format": "json",
            })
        except Exception:  # pragma: no cover - Netzwerk/Anmeldung
            return None
        # OData v2 ({"d": {"results": [...]}}) und v4 ({"value": [...]}) abdecken
        results = (
            data.get("d", {}).get("results")
            if isinstance(data.get("d"), dict)
            else None
        ) or data.get("value") or []
        if not results:
            return None
        return self._to_contact(results[0])

    # --- Interface --------------------------------------------------------
    def find_contact(
        self, email: str = "", name: str = ""
    ) -> Optional[CrmContact]:
        email_field = self.field_map.get("email", "Email")
        name_field = self.field_map.get("full_name", "Name")
        if email:
            esc = email.replace("'", "''")
            hit = self._query(f"{email_field} eq '{esc}'")
            if hit:
                return hit
        if name:
            esc = name.replace("'", "''")
            return self._query(f"{name_field} eq '{esc}'")
        return None
