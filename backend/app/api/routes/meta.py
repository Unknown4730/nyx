"""Application metadata: form vocabularies, sample templates, catalogue info.

The frontend renders its selects and template cards from this endpoint so the
two sides cannot drift: adding an enum value to the backend makes it appear in
the form automatically.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.rules.suitability_rules import BANDS, MISSING_WEIGHT_LIMIT, RULE_PACK_VERSION, WEIGHT_RATIONALE
from app.schemas.analysis import AiStatusPayload, AnalysisOptions
from app.schemas.requirements import ApplicationRequirements
from app.schemas.common import (
    SCHEMA_VERSION,
    ApplicationType,
    AvailabilityExpectation,
    BudgetPreference,
    CloudProvider,
    ComponentTier,
    DataStorageKind,
    DeploymentTarget,
    ComponentRuntime,
    DurationProfile,
    EffortLevel,
    LogicalComponentType,
    RecommendedPattern,
    Severity,
    SuitabilityOutcome,
    TrafficPattern,
)
from app.rules.cost_rates import COST_MODEL_VERSION, Rates
from app.rules.requirement_rules import (
    ACTIVE_DAYS_PER_MONTH,
    PEAK_RATIO_BY_TRAFFIC,
    REQUESTS_PER_SESSION,
    SESSIONS_PER_USER_BY_TYPE,
)
from app.services.cloud_catalog import get_catalog
from app.services.templates import catalogue_version, load_templates

router = APIRouter(tags=["meta"])


class OptionItem(BaseModel):
    value: str
    label: str


class EnumBundle(BaseModel):
    application_type: list[OptionItem] = Field(default_factory=list)
    traffic_pattern: list[OptionItem] = Field(default_factory=list)
    data_storage: list[OptionItem] = Field(default_factory=list)
    availability: list[OptionItem] = Field(default_factory=list)
    budget: list[OptionItem] = Field(default_factory=list)
    provider: list[OptionItem] = Field(default_factory=list)
    suitability_outcome: list[OptionItem] = Field(default_factory=list)
    deployment_target: list[OptionItem] = Field(default_factory=list)
    component_tier: list[OptionItem] = Field(default_factory=list)
    severity: list[OptionItem] = Field(default_factory=list)
    effort_level: list[OptionItem] = Field(default_factory=list)
    recommended_pattern: list[OptionItem] = Field(default_factory=list)
    runtime: list[OptionItem] = Field(default_factory=list)
    duration_profile: list[OptionItem] = Field(default_factory=list)
    logical_component_type: list[OptionItem] = Field(default_factory=list)


def _items(enum: type[BaseModel]) -> list[OptionItem]:
    return [OptionItem(value=str(member.value), label=str(member.value).replace("_", " ").title()) for member in enum]


@router.get("/meta", response_model=dict)
def meta() -> dict[str, object]:
    settings = get_settings()
    catalog = get_catalog()
    ai_status = settings.ai.public_status()
    rates = Rates()
    return {
        "product": {
            "name": settings.app_name,
            "title": settings.app_title,
            "tagline": settings.tagline,
            "version": settings.version,
            "schema_version": SCHEMA_VERSION,
            "rule_pack_version": RULE_PACK_VERSION,
            "catalog_version": catalog.version,
            "cost_model_version": COST_MODEL_VERSION,
            "templates_version": catalogue_version(),
        },
        "ai": ai_status,
        "enums": EnumBundle(
            application_type=_items(ApplicationType),
            traffic_pattern=_items(TrafficPattern),
            data_storage=_items(DataStorageKind),
            availability=_items(AvailabilityExpectation),
            budget=_items(BudgetPreference),
            provider=[item for item in _items(CloudProvider) if item.value != CloudProvider.UNDECIDED.value],
            suitability_outcome=_items(SuitabilityOutcome),
            deployment_target=_items(DeploymentTarget),
            component_tier=_items(ComponentTier),
            severity=_items(Severity),
            effort_level=_items(EffortLevel),
            recommended_pattern=_items(RecommendedPattern),
            runtime=_items(ComponentRuntime),
            duration_profile=_items(DurationProfile),
            logical_component_type=_items(LogicalComponentType),
        ).model_dump(mode="json"),
        "suitability": {
            "bands": [
                {"outcome": outcome.value, "min_score": threshold, "label": outcome.value.replace("_", " ")}
                for threshold, outcome in BANDS
            ],
            "weight_rationale": WEIGHT_RATIONALE,
            "missing_weight_limit": MISSING_WEIGHT_LIMIT,
            "rule_pack_version": RULE_PACK_VERSION,
        },
        "derivation": {
            "active_days_per_month": ACTIVE_DAYS_PER_MONTH,
            "requests_per_session": REQUESTS_PER_SESSION,
            "sessions_per_user_by_type": {
                key.value: value for key, value in SESSIONS_PER_USER_BY_TYPE.items()
            },
            "peak_ratio_by_traffic": {key.value: value for key, value in PEAK_RATIO_BY_TRAFFIC.items()},
        },
        "cost": {
            "unit": "RICU",
            "unit_name": "Relative Infrastructure Cost Unit",
            "definition": "1 RICU = the relative monthly cost of one small always-on compute unit (1 vCPU / 2 GB class).",
            "rates": rates.describe(),
            "model_version": COST_MODEL_VERSION,
        },
        "catalog": catalog.summary(),
        "templates": load_template_payloads(),
        "limits": input_limits(),
    }


def _bounds(model: type[BaseModel], field_name: str) -> tuple[int | None, int | None]:
    """Lower and upper bound of a model field, read from its pydantic constraints."""
    lower: int | None = None
    upper: int | None = None
    for constraint in model.model_fields[field_name].metadata:
        lower = getattr(constraint, "min_length", getattr(constraint, "ge", lower))
        upper = getattr(constraint, "max_length", getattr(constraint, "le", upper))
    return lower, upper


def input_limits() -> dict[str, object]:
    """Input limits the API enforces, read from the schema so the UI cannot drift from it."""
    name_min, name_max = _bounds(ApplicationRequirements, "name")
    description_min, description_max = _bounds(ApplicationRequirements, "description")
    _, notes_max = _bounds(ApplicationRequirements, "additional_requirements")
    ops_min, ops_max = _bounds(AnalysisOptions, "max_operations_per_view")
    return {
        "name_min_chars": name_min,
        "name_max_chars": name_max,
        "description_min_chars": description_min,
        "description_max_chars": description_max,
        "additional_requirements_max_chars": notes_max,
        "max_operations_per_view": {
            "min": ops_min,
            "max": ops_max,
            "default": AnalysisOptions.model_fields["max_operations_per_view"].default,
        },
    }


def load_template_payloads() -> list[dict[str, object]]:
    return [template.public_dict() for template in load_templates()]


@router.get("/ai/status", response_model=AiStatusPayload)
def ai_status() -> AiStatusPayload:
    snapshot = get_settings().ai.public_status()
    if snapshot["configured"]:
        return AiStatusPayload(
            status="success",
            message=f"OpenAI-compatible provider configured (model {snapshot['model']}). "
            "The model may only propose requirement values; all analysis stages stay rule-based.",
            model=str(snapshot["model"] or "") or None,
        )
    return AiStatusPayload(
        status="not_configured",
        message=str(snapshot.get("unavailable_reason") or "AI assist is not configured.")
        + " Deterministic analysis is fully available.",
    )
