"""Schema for the (optional) AI extraction proposal.

This is the entire contract between the language model and the rest of NYX.
The model may propose requirement classifications and workload signals only.
It cannot propose architectures, cloud services, security findings, cost
figures or migration steps — those are computed by deterministic rules.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import (
    AvailabilityExpectation,
    BudgetPreference,
    CloudProvider,
    DataStorageKind,
    LenientModel,
    TrafficPattern,
    ApplicationType,
)
from .requirements import RequirementSignals

#: Exactly these signal keys may be proposed by the model.
ALLOWED_SIGNAL_KEYS: tuple[str, ...] = tuple(
    name
    for name, info in RequirementSignals.model_fields.items()
    if name not in {"provenance", "notes"}
)

#: Keys that must be integers within a sane range, enforced before use.
INTEGER_KEYS = {
    "expected_users",
    "monthly_requests",
    "peak_requests_per_minute",
    "peak_concurrency",
    "typical_response_ms",
    "latency_budget_ms",
}
BOOL_KEYS = {
    "long_running_jobs",
    "cpu_or_memory_intensive",
    "gpu_required",
    "custom_runtime_required",
    "cold_start_sensitive",
    "startup_latency_sensitive",
    "event_driven",
    "scheduled_batch",
    "streaming_ingestion",
    "persistent_connections",
    "stateful_sessions",
    "shared_locking_required",
    "transactional_writes",
    "high_fanout_reads",
    "relational_data",
    "document_data",
    "key_value_data",
    "object_storage_needed",
    "filesystem_semantics_required",
    "search_needed",
    "cache_needed",
    "messaging_needed",
    "generated_files",
    "sensitive_data",
    "requires_audit_trail",
    "public_internet_facing",
    "notification_required",
    "pdf_or_reporting",
    "multi_tenant",
    "existing_on_prem_assets",
    "business_hours_only",
}
NUMBER_KEYS = {"longest_operation_minutes", "dataset_size_gb", "upload_size_mb", "backup_expectation_days"}

JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "application_type": {"type": "string", "enum": ApplicationType.values()},
        "traffic_pattern": {"type": "string", "enum": TrafficPattern.values()},
        "availability": {"type": "string", "enum": AvailabilityExpectation.values()},
        "budget": {"type": "string", "enum": BudgetPreference.values()},
        "preferred_provider": {"type": "string", "enum": [p.value for p in CloudProvider]},
        "data_storage": {"type": "array", "items": {"type": "string", "enum": DataStorageKind.values()}, "maxItems": 6},
        "signals": {
            "type": "object",
            "additionalProperties": True,
            "description": "Only the documented signal keys are read; everything else is discarded.",
        },
        "assumptions": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "open_questions": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
    "required": ["signals"],
}


class AiExtractionProposal(LenientModel):
    """Validated view of a model response."""

    application_type: ApplicationType | None = None
    # Free-text only on purpose: a numeric user count must arrive through
    # `signals.expected_users`, where the range checks and the "already
    # established" guard in the merge apply to it.
    user_count_note: str | None = Field(default=None, max_length=200)
    traffic_pattern: TrafficPattern | None = None
    availability: AvailabilityExpectation | None = None
    budget: BudgetPreference | None = None
    preferred_provider: CloudProvider | None = None
    data_storage: list[DataStorageKind] = Field(default_factory=list, max_length=6)
    signals: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    open_questions: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("assumptions", "open_questions", mode="before")
    @classmethod
    def _as_text(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value[:400]]
        if isinstance(value, list):
            return [str(item)[:400] for item in value if str(item).strip()][:10]
        return []

    @field_validator("data_storage", mode="before")
    @classmethod
    def _clean_storage(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        allowed = set(DataStorageKind.values())
        return [item for item in value if isinstance(item, str) and item in allowed][:6]

    @model_validator(mode="after")
    def _prune_signals(self) -> "AiExtractionProposal":
        cleaned: dict[str, Any] = {}
        for key, value in self.signals.items():
            if key not in ALLOWED_SIGNAL_KEYS:
                continue
            if key in BOOL_KEYS:
                if isinstance(value, bool):
                    cleaned[key] = value
                elif isinstance(value, str) and value.lower() in {"true", "false"}:
                    cleaned[key] = value.lower() == "true"
                continue
            if key in INTEGER_KEYS:
                try:
                    number = int(float(value))
                except (TypeError, ValueError):
                    continue
                if 0 <= number <= 500_000_000:
                    cleaned[key] = number
                continue
            if key in NUMBER_KEYS:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if 0 <= number <= 1_000_000_000:
                    cleaned[key] = round(number, 4)
                continue
            if isinstance(value, str) and len(value) <= 120:
                cleaned[key] = value
        self.signals = cleaned
        return self

    def field_count(self) -> int:
        return (
            sum(1 for name in ("application_type", "traffic_pattern", "availability", "budget", "preferred_provider")
                if getattr(self, name) is not None)
            + len(self.data_storage)
            + len(self.signals)
        )
