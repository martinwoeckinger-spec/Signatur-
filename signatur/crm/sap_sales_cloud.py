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

from ..models import CrmContact, utc_now
from .base import CrmClient, CrmWriteError

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
    supports_write = True

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

    def _request(self, method: str, path: str, params: dict[str, str] | None = None,
                 payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """HTTP-Aufruf gegen die OData-Schnittstelle (GET/PATCH/MERGE)."""
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}/{path.lstrip('/')}" + (f"?{query}" if query else "")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json", **self._auth_header()}
        if data is not None:
            headers["Content-Type"] = "application/json"
            headers["X-Requested-With"] = "XMLHttpRequest"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8") or "{}"
        return json.loads(body) if body.strip().startswith(("{", "[")) else {}

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        return self._request("GET", path, params=params)

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

    def _query_many(self, odata_filter: str, top: int = 10) -> list[CrmContact]:
        """Liefert alle Treffer eines Filters (Basis für FA-22)."""
        try:
            data = self._get(self.contact_set, {
                "$filter": odata_filter,
                "$top": str(top),
                "$format": "json",
            })
        except Exception:  # pragma: no cover - Netzwerk/Anmeldung
            return []
        results = (
            data.get("d", {}).get("results")
            if isinstance(data.get("d"), dict)
            else None
        ) or data.get("value") or []
        return [self._to_contact(r) for r in results]

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

    def find_contacts(self, email: str = "", name: str = "",
                      domain: str = "") -> list[CrmContact]:
        """Alle Treffer: E-Mail exakt (FA-20), sonst Name (+ Domain, FA-21)."""
        email_field = self.field_map.get("email", "Email")
        name_field = self.field_map.get("full_name", "Name")
        if email:
            esc = email.replace("'", "''")
            hits = self._query_many(f"{email_field} eq '{esc}'")
            if hits:
                return hits
        if name:
            esc = name.replace("'", "''")
            hits = self._query_many(f"{name_field} eq '{esc}'")
            if domain:
                dom = domain.strip().lower().lstrip("@")
                narrowed = [h for h in hits
                            if h.email.endswith("@" + dom) or dom in h.website.lower()]
                if narrowed:
                    return narrowed
            return hits
        return []

    def get_contact(self, crm_id: str) -> Optional[CrmContact]:
        """Live-Abruf eines Kontakts über die ObjectID (FA-24)."""
        if not crm_id:
            return None
        id_field = self.field_map.get("crm_id", "ObjectID")
        esc = crm_id.replace("'", "''")
        return self._query(f"{id_field} eq '{esc}'")

    def update_contact(self, crm_id: str, changes: dict[str, str], *,
                       actor: str = "", source: str = "Signature Checker",
                       ) -> dict[str, Any]:
        """Schreibt freigegebene Felder per OData-PATCH zurück (FA-50, FA-51).

        Die Herkunftskennzeichnung wird in die im Mapping hinterlegten Felder
        geschrieben (`provenance_*`); fehlen sie im Mapping, bleibt sie diesem
        Aufruf entzogen und wird ausschliesslich im Audit-Log geführt.
        """
        if not crm_id:
            raise CrmWriteError("Rückschreiben ohne CRM-ID nicht möglich.")
        payload: dict[str, Any] = {}
        unmapped: list[str] = []
        for field, value in changes.items():
            sap_field = self.field_map.get(field)
            if not sap_field:
                unmapped.append(field)
                continue
            payload[sap_field] = value
        if unmapped:
            raise CrmWriteError(
                "Kein SAP-Feldmapping für: " + ", ".join(sorted(unmapped))
                + " (config/mapping.json ergänzen)")
        for key, value in (("provenance_source", source),
                           ("provenance_actor", actor),
                           ("provenance_at", utc_now())):
            sap_field = self.field_map.get(key)
            if sap_field:
                payload[sap_field] = value
        entity = f"{self.contact_set}('{crm_id}')"
        try:
            self._request("PATCH", entity, payload=payload)
        except Exception as exc:  # noqa: BLE001 - Netz-/HTTP-Fehler bündeln
            raise CrmWriteError(f"SAP-Schreibfehler für {crm_id}: {exc}") from exc
        return {"crm_id": crm_id, "geschrieben": dict(changes), "herkunft": source,
                "akteur": actor, "zeitpunkt": utc_now()}
