"""CRM-Adapter: einheitliches Interface über austauschbare Backends."""
from __future__ import annotations

from .base import CrmClient
from .mock_crm import MockCrmClient


def get_client(name: str, **kwargs) -> CrmClient:
    """Factory: liefert eine CRM-Client-Implementierung anhand des Namens."""
    name = (name or "mock").lower()
    if name == "mock":
        return MockCrmClient(**kwargs)
    if name in ("sap", "sap-sales-cloud", "salescloud"):
        from .sap_sales_cloud import SapSalesCloudClient
        return SapSalesCloudClient(**kwargs)
    raise ValueError(f"Unbekanntes CRM-Backend: {name!r} (erlaubt: mock, sap)")


__all__ = ["CrmClient", "MockCrmClient", "get_client"]
