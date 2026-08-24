"""Abstraktes CRM-Client-Interface (Lesen und Schreiben)."""
from __future__ import annotations

import abc
from typing import Any, Optional

from ..models import CrmContact


class CrmWriteError(RuntimeError):
    """Fehler beim Rückschreiben ins CRM (FA-52: der Fall bleibt offen)."""


class CrmClient(abc.ABC):
    """Einheitliche Schnittstelle für CRM-Backends.

    Konkrete Backends (Mock, SAP Sales Cloud, …) implementieren `find_contact`.
    So bleibt der restliche Workflow vom konkreten CRM entkoppelt.
    Optional: `find_contacts` (Mehrdeutigkeit, FA-22), `get_contact`
    (Live-Abruf bei Fallanzeige, FA-24) und `update_contact` (FA-50).
    """

    name: str = "crm"
    supports_write: bool = False

    @abc.abstractmethod
    def find_contact(
        self, email: str = "", name: str = ""
    ) -> Optional[CrmContact]:
        """Sucht einen Kontakt – primär per E-Mail, ersatzweise per Name.

        Gibt `None` zurück, wenn kein Datensatz gefunden wird.
        """
        raise NotImplementedError

    def find_contacts(
        self, email: str = "", name: str = "", domain: str = ""
    ) -> list[CrmContact]:
        """Alle passenden Kontakte (für Mehrdeutigkeitserkennung, FA-22).

        Default-Implementierung: reicht `find_contact` durch, liefert also
        höchstens einen Treffer.
        """
        hit = self.find_contact(email=email, name=name)
        return [hit] if hit else []

    def get_contact(self, crm_id: str) -> Optional[CrmContact]:
        """Liest einen Kontakt frisch anhand seiner CRM-ID (FA-24)."""
        return None

    def update_contact(self, crm_id: str, changes: dict[str, str], *,
                       actor: str = "", source: str = "Signature Checker",
                       ) -> dict[str, Any]:
        """Schreibt freigegebene Feldwerte zurück (FA-50, FA-51).

        Implementierungen kennzeichnen die Änderung mit Herkunft, Datum und
        freigebender Person und werfen `CrmWriteError` bei Fehlern.
        """
        raise CrmWriteError(
            f"CRM-Backend '{self.name}' unterstützt kein Rückschreiben."
        )

    def close(self) -> None:  # pragma: no cover - optional
        """Ressourcen freigeben (Default: nichts zu tun)."""
        return None
