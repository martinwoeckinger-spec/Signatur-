"""Abstraktes CRM-Client-Interface."""
from __future__ import annotations

import abc
from typing import Optional

from ..models import CrmContact


class CrmClient(abc.ABC):
    """Einheitliche Schnittstelle für CRM-Backends.

    Konkrete Backends (Mock, SAP Sales Cloud, …) implementieren `find_contact`.
    So bleibt der restliche Workflow vom konkreten CRM entkoppelt.
    """

    name: str = "crm"

    @abc.abstractmethod
    def find_contact(
        self, email: str = "", name: str = ""
    ) -> Optional[CrmContact]:
        """Sucht einen Kontakt – primär per E-Mail, ersatzweise per Name.

        Gibt `None` zurück, wenn kein Datensatz gefunden wird.
        """
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - optional
        """Ressourcen freigeben (Default: nichts zu tun)."""
        return None
