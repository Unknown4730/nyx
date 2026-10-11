"""Sample project templates.

A template is a *prefilled input*, nothing more: choosing one runs exactly the
same deterministic pipeline as a hand-typed description.  That is what keeps the
demonstration honest — the conclusions come from the rules, not from a file.

The template file is required runtime data.  A missing, unreadable or malformed
file raises `TemplateDataError` instead of returning an empty catalogue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.schemas.common import (
    ApplicationType,
    AvailabilityExpectation,
    BudgetPreference,
    CloudProvider,
    DataStorageKind,
    FieldBasis,
    TrafficPattern,
)
from app.schemas.requirements import ApplicationRequirements, FieldProvenance

TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "data" / "templates.json"

TEMPLATE_FIELD_LABELS: dict[str, str] = {
    "name": "name",
    "description": "description",
    "expected_users": "expected_users",
    "traffic_pattern": "traffic_pattern",
    "application_type": "application_type",
    "data_storage": "data_storage",
    "availability": "availability",
    "budget": "budget",
    "preferred_provider": "preferred_provider",
    "additional_requirements": "additional_requirements",
}

REQUIRED_TEMPLATE_KEYS = ("id", "name", "tagline", "description")


class TemplateDataError(RuntimeError):
    """The sample template file is missing, unreadable or structurally invalid."""


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    tagline: str
    icon: str
    summary: str
    highlights: tuple[str, ...]
    expected_outcome_hint: str
    requirements: ApplicationRequirements

    def public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "tagline": self.tagline,
            "icon": self.icon,
            "summary": self.summary,
            "highlights": list(self.highlights),
            "expected_outcome_hint": self.expected_outcome_hint,
            "form": {
                "name": self.requirements.name,
                "description": self.requirements.description,
                "expected_users": self.requirements.expected_users,
                "traffic_pattern": _value(self.requirements.traffic_pattern),
                "application_type": _value(self.requirements.application_type),
                "data_storage": [_value(item) for item in self.requirements.data_storage],
                "availability": _value(self.requirements.availability),
                "budget": _value(self.requirements.budget),
                "preferred_provider": _value(self.requirements.preferred_provider),
                "additional_requirements": self.requirements.additional_requirements,
            },
        }


def _value(item: object) -> str | None:
    if item is None:
        return None
    return getattr(item, "value", str(item))


def read_template_document(path: Path = TEMPLATES_PATH) -> dict[str, object]:
    """Read and structurally validate the template file (no schema coercion yet)."""
    if not path.is_file():
        raise TemplateDataError(
            f"Required template file not found at {path}. It is tracked in the repository under "
            "backend/app/data/; restore it from version control."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TemplateDataError(f"Template file {path} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("templates"), list) or not raw["templates"]:
        raise TemplateDataError(f"Template file {path} must contain a non-empty 'templates' list.")
    seen: set[str] = set()
    for index, entry in enumerate(raw["templates"]):
        if not isinstance(entry, dict):
            raise TemplateDataError(f"Template #{index} in {path} is not an object.")
        missing = [key for key in REQUIRED_TEMPLATE_KEYS if not str(entry.get(key, "")).strip()]
        if missing:
            raise TemplateDataError(f"Template #{index} in {path} is missing required fields: {', '.join(missing)}.")
        if entry["id"] in seen:
            raise TemplateDataError(f"Template id '{entry['id']}' is defined more than once in {path}.")
        seen.add(str(entry["id"]))
    return raw


def _build_template(entry: dict[str, object]) -> Template:
    provenance = {
        field_name: FieldProvenance(
            basis=FieldBasis.TEMPLATE,
            note=(
                "Supplied by the NYX sample template and treated as a user assertion; "
                "the analysis engine may still flag it as an assumption if it drives a score."
            ),
        )
        for field_name in TEMPLATE_FIELD_LABELS
    }
    try:
        requirements = ApplicationRequirements(
            name=str(entry["name"]),
            description=str(entry["description"]),
            expected_users=entry.get("expected_users"),  # type: ignore[arg-type]
            traffic_pattern=_enum(TrafficPattern, entry.get("traffic_pattern")),
            application_type=_enum(ApplicationType, entry.get("application_type")) or ApplicationType.UNKNOWN,
            data_storage=[_enum(DataStorageKind, item) for item in entry.get("data_storage", []) if item],  # type: ignore[misc]
            availability=_enum(AvailabilityExpectation, entry.get("availability")),
            budget=_enum(BudgetPreference, entry.get("budget")),
            preferred_provider=_enum(CloudProvider, entry.get("preferred_provider")),
            additional_requirements=entry.get("additional_requirements"),  # type: ignore[arg-type]
            template_id=str(entry["id"]),
            provenance=provenance,  # type: ignore[arg-type]
        )
    except (ValueError, TypeError) as exc:
        raise TemplateDataError(f"Template '{entry.get('id')}' does not satisfy the requirements schema: {exc}") from exc
    return Template(
        id=str(entry["id"]),
        name=str(entry["name"]),
        tagline=str(entry["tagline"]),
        icon=str(entry.get("icon", "Sparkles")),
        summary=str(entry.get("summary", "")),
        highlights=tuple(str(item) for item in entry.get("highlights", [])),  # type: ignore[union-attr]
        expected_outcome_hint=str(entry.get("expected_outcome_hint", "")),
        requirements=requirements,
    )


@lru_cache(maxsize=1)
def load_templates() -> tuple[Template, ...]:
    raw = read_template_document()
    return tuple(_build_template(entry) for entry in raw["templates"])  # type: ignore[index]


def _enum(cls, value: object):  # type: ignore[no-untyped-def]
    if value is None or value == "":
        return None
    return cls(str(value))


def template_by_id(template_id: str) -> Template | None:
    for template in load_templates():
        if template.id == template_id:
            return template
    return None


def requirements_for(template_id: str) -> ApplicationRequirements | None:
    template = template_by_id(template_id)
    return template.requirements.model_copy(deep=True) if template else None


def template_payloads() -> list[dict[str, object]]:
    return [template.public_dict() for template in load_templates()]


def catalogue_version() -> str:
    return str(read_template_document().get("version", "unknown"))
