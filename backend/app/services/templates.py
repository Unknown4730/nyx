"""Sample project templates.

A template is a *prefilled input*, nothing more: choosing one runs exactly the
same deterministic pipeline as a hand-typed description.  That is what keeps the
demonstration honest — the conclusions come from the rules, not from a file.
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


@lru_cache(maxsize=1)
def load_templates() -> tuple[Template, ...]:
    raw = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    templates: list[Template] = []
    for entry in raw["templates"]:
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
        requirements = ApplicationRequirements(
            name=entry["name"],
            description=entry["description"],
            expected_users=entry.get("expected_users"),
            traffic_pattern=_enum(TrafficPattern, entry.get("traffic_pattern")),
            application_type=_enum(ApplicationType, entry.get("application_type")) or ApplicationType.UNKNOWN,
            data_storage=[_enum(DataStorageKind, item) for item in entry.get("data_storage", []) if item],  # type: ignore[misc]
            availability=_enum(AvailabilityExpectation, entry.get("availability")),
            budget=_enum(BudgetPreference, entry.get("budget")),
            preferred_provider=_enum(CloudProvider, entry.get("preferred_provider")),
            additional_requirements=entry.get("additional_requirements"),
            template_id=entry["id"],
            provenance=provenance,  # type: ignore[arg-type]
        )
        templates.append(
            Template(
                id=entry["id"],
                name=entry["name"],
                tagline=entry["tagline"],
                icon=entry.get("icon", "Sparkles"),
                summary=entry.get("summary", ""),
                highlights=tuple(entry.get("highlights", [])),
                expected_outcome_hint=entry.get("expected_outcome_hint", ""),
                requirements=requirements,
            )
        )
    return tuple(templates)


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
    return str(json.loads(TEMPLATES_PATH.read_text(encoding="utf-8")).get("version", "unknown"))
