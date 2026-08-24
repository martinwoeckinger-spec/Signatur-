"""Gemeinsame Fixtures für die Checker-Tests."""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signatur.config import load_config          # noqa: E402
from signatur.crm.mock_crm import MockCrmClient  # noqa: E402
from signatur.review import ReviewService        # noqa: E402
from signatur.store import CheckerStore          # noqa: E402

SAMPLES = ROOT / "samples"
CRM_CSV = ROOT / "data" / "crm_mock.csv"


@pytest.fixture
def config(tmp_path):
    """Konfiguration aus config/checker.json mit isoliertem Store."""
    cfg = load_config(ROOT / "config" / "checker.json")
    cfg.store_path = str(tmp_path / "store.json")
    cfg.crm_contact_url_template = "https://crm.example/contact/{id}"
    return cfg


@pytest.fixture
def store(config):
    return CheckerStore(config.store_file())


@pytest.fixture
def crm(tmp_path):
    """Mock-CRM auf einer Kopie der Demodaten (schreibbar)."""
    csv_copy = tmp_path / "crm.csv"
    shutil.copy(CRM_CSV, csv_copy)
    return MockCrmClient(csv_path=csv_copy)


@pytest.fixture
def service(store, crm, config):
    return ReviewService(store, crm, config)
