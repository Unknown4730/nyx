"""Required runtime data: missing, malformed and incomplete files must fail loudly.

The catalogue and the sample templates are shipped under backend/app/data/.  These
tests exercise the loaders with temporary broken copies, and check that the real
shipped files are complete and internally consistent.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.services import cloud_catalog as catalog_module
from app.services import templates as templates_module
from app.services.cloud_catalog import CatalogDataError, CloudCatalogService, load_catalog_document
from app.services.templates import TemplateDataError, read_template_document, _build_template

REAL_CATALOG = catalog_module.CATALOG_PATH
REAL_TEMPLATES = templates_module.TEMPLATES_PATH


def _write(tmp_path: Path, name: str, payload) -> Path:
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def _real_catalog() -> dict:
    return json.loads(REAL_CATALOG.read_text(encoding="utf-8"))


def _real_templates() -> dict:
    return json.loads(REAL_TEMPLATES.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Shipped files
# ---------------------------------------------------------------------------


def test_shipped_catalogue_and_templates_exist_under_the_tracked_data_directory():
    assert REAL_CATALOG.is_file(), "backend/app/data/cloud_services.json must be tracked"
    assert REAL_TEMPLATES.is_file(), "backend/app/data/templates.json must be tracked"
    assert REAL_CATALOG.parent.name == "data" and REAL_CATALOG.parent.parent.name == "app"


def test_shipped_catalogue_is_structurally_valid():
    document = load_catalog_document(REAL_CATALOG)
    assert document["version"] == "2026.10"
    assert "not a pricing file" in document["disclaimer"]
    assert len(document["services"]) >= 80


def test_shipped_templates_are_unique_complete_and_buildable():
    document = read_template_document(REAL_TEMPLATES)
    ids = [entry["id"] for entry in document["templates"]]
    assert len(ids) == len(set(ids)) >= 5
    for entry in document["templates"]:
        template = _build_template(entry)
        assert len(template.requirements.description) > 60
        assert template.tagline and template.name


# ---------------------------------------------------------------------------
# Catalogue failure modes
# ---------------------------------------------------------------------------


def test_missing_catalogue_file_is_a_clear_error_not_an_empty_registry(tmp_path):
    with pytest.raises(CatalogDataError, match="not found"):
        CloudCatalogService(tmp_path / "absent.json")


def test_malformed_catalogue_json_is_rejected(tmp_path):
    path = _write(tmp_path, "cloud.json", "{not json")
    with pytest.raises(CatalogDataError, match="not valid UTF-8 JSON"):
        load_catalog_document(path)


@pytest.mark.parametrize("missing_key", ["version", "disclaimer", "services"])
def test_catalogue_without_a_required_top_level_key_is_rejected(tmp_path, missing_key):
    document = _real_catalog()
    del document[missing_key]
    with pytest.raises(CatalogDataError, match=missing_key):
        load_catalog_document(_write(tmp_path, "cloud.json", document))


def test_catalogue_with_an_empty_services_map_is_rejected(tmp_path):
    document = _real_catalog()
    document["services"] = {}
    with pytest.raises(CatalogDataError, match="no 'services' entries"):
        load_catalog_document(_write(tmp_path, "cloud.json", document))


@pytest.mark.parametrize(
    ("field", "value", "expected_fragment"),
    [
        ("url", "http://insecure.example", "https link"),
        ("serverless_class", "magic", "serverless_class"),
        ("provider", "gcp", "'provider' must be"),
        ("name", "", "'name' is required"),
    ],
)
def test_incomplete_service_entries_are_reported_by_key(tmp_path, field, value, expected_fragment):
    document = copy.deepcopy(_real_catalog())
    document["services"]["aws.s3"][field] = value
    with pytest.raises(CatalogDataError) as excinfo:
        load_catalog_document(_write(tmp_path, "cloud.json", document))
    assert "aws.s3" in str(excinfo.value)
    assert expected_fragment in str(excinfo.value)


def test_a_catalogue_missing_a_mapped_service_fails_the_mapping_check(tmp_path):
    document = copy.deepcopy(_real_catalog())
    del document["services"]["azure.blob_storage"]
    path = _write(tmp_path, "cloud.json", document)
    with pytest.raises(CatalogDataError, match="azure.blob_storage"):
        CloudCatalogService(path)


# ---------------------------------------------------------------------------
# Template failure modes
# ---------------------------------------------------------------------------


def test_missing_template_file_is_a_clear_error(tmp_path):
    with pytest.raises(TemplateDataError, match="not found"):
        read_template_document(tmp_path / "absent.json")


def test_malformed_template_json_is_rejected(tmp_path):
    with pytest.raises(TemplateDataError, match="not valid UTF-8 JSON"):
        read_template_document(_write(tmp_path, "templates.json", "[oops"))


def test_empty_template_list_is_rejected(tmp_path):
    with pytest.raises(TemplateDataError, match="non-empty"):
        read_template_document(_write(tmp_path, "templates.json", {"templates": []}))


def test_duplicate_template_ids_are_rejected(tmp_path):
    document = _real_templates()
    document["templates"].append(copy.deepcopy(document["templates"][0]))
    with pytest.raises(TemplateDataError, match="defined more than once"):
        read_template_document(_write(tmp_path, "templates.json", document))


def test_template_without_a_description_is_rejected(tmp_path):
    document = _real_templates()
    del document["templates"][0]["description"]
    with pytest.raises(TemplateDataError, match="missing required fields: description"):
        read_template_document(_write(tmp_path, "templates.json", document))


def test_template_with_an_unknown_enum_value_is_rejected():
    entry = copy.deepcopy(_real_templates()["templates"][0])
    entry["traffic_pattern"] = "usually_quiet"
    with pytest.raises(TemplateDataError, match="requirements schema"):
        _build_template(entry)


def test_templates_are_loaded_from_the_real_file_through_the_public_loader():
    names = {template.id for template in templates_module.load_templates()}
    assert {"college-attendance", "online-examination", "ecommerce-application"} <= names
