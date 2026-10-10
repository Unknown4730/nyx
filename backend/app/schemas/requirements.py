"""Validated requirement representation and extracted workload signals.

`ApplicationRequirements` is what the user (or a template) asserts.
`RequirementSignals` is what the engine derived from the free-text description.
Every field on both models carries a `FieldBasis` so the UI can show whether a
value was supplied by the user, inferred by rules, suggested by the AI layer,
or simply unknown.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from .common import (
    AvailabilityExpectation,
    BudgetPreference,
    CloudProvider,
    DataStorageKind,
    FieldBasis,
    TrafficPattern,
    ApplicationType,
    StrictModel,
)

MAX_DESCRIPTION_CHARS = 4000
MAX_NOTES_CHARS = 2000


class FieldProvenance(StrictModel):
    basis: FieldBasis = FieldBasis.UNSPECIFIED
    note: str | None = None


class Assumption(StrictModel):
    """A recorded uncertainty or a derived planning assumption."""

    id: str
    statement: str
    basis: FieldBasis = FieldBasis.INFERRED
    impact: str = "medium"  # low | medium | high
    rule: str | None = None
    field: str | None = None


class OpenQuestion(StrictModel):
    """A missing detail the analysis could not responsibly guess."""

    id: str
    question: str
    field: str
    why_it_matters: str


class ApplicationRequirements(StrictModel):
    """User-declared facts about the application under review."""

    name: str = Field(min_length=2, max_length=90)
    description: str = Field(min_length=10, max_length=MAX_DESCRIPTION_CHARS)
    expected_users: int | None = Field(default=None, ge=1, le=500_000_000)
    traffic_pattern: TrafficPattern | None = None
    application_type: ApplicationType = ApplicationType.UNKNOWN
    data_storage: list[DataStorageKind] = Field(default_factory=list)
    availability: AvailabilityExpectation | None = None
    budget: BudgetPreference | None = None
    preferred_provider: CloudProvider | None = None
    additional_requirements: str | None = Field(default=None, max_length=MAX_NOTES_CHARS)
    template_id: str | None = None
    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _tidy_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("application name is too short")
        return cleaned

    @field_validator("description")
    @classmethod
    def _tidy_description(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 10:
            raise ValueError("description must contain at least 10 characters")
        return cleaned

    @field_validator("traffic_pattern", "availability", "budget", "preferred_provider", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Treat the many ways a form says "I don't know" as *not stated*.

        An empty select, "none", "n/a" or "unknown" must not be scored as if the
        user had asserted something; the engine needs to see a genuine gap.
        """
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
            if cleaned in {"", "none", "n/a", "na", "null", "unknown", "unspecified", "unspecified_", "tbd",
                           "not_sure", "no_preference", "any", "dont_know"}:
                return None
        return value

    @field_validator("application_type", mode="before")
    @classmethod
    def _unknown_type_sentinel(cls, value: object) -> object:
        """`application_type` has a real UNKNOWN member, so map the junk onto it."""
        if isinstance(value, str):
            cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
            if cleaned in {"", "none", "n/a", "na", "null", "tbd", "not_sure", "any"}:
                return ApplicationType.UNKNOWN.value
        return value

    @field_validator("additional_requirements")
    @classmethod
    def _tidy_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("data_storage")
    @classmethod
    def _dedupe_storage(cls, value: list[DataStorageKind]) -> list[DataStorageKind]:
        """Order is the canonical vocabulary order, so two equivalent inputs
        never produce two different stored documents."""
        return [kind for kind in DataStorageKind if kind in set(value)]

    @model_validator(mode="after")
    def _stamp_provenance(self) -> "ApplicationRequirements":
        """Record which values the caller asserted.

        Without this the UI could not tell "the user said 10 000 users" from "a
        rule inferred it", and the AI merge could not tell that a field was
        already spoken for.
        """
        provenance = dict(self.provenance)
        for field_name in self.model_fields_set:
            if field_name in {"provenance", "template_id"}:
                continue
            value = getattr(self, field_name)
            if value in (None, [], ""):
                continue
            provenance.setdefault(field_name, FieldProvenance(basis=FieldBasis.USER, note="Supplied in the request."))
        self.provenance = provenance
        return self

    def basis_for(self, field_name: str) -> FieldBasis:
        entry = self.provenance.get(field_name)
        return entry.basis if entry else FieldBasis.UNSPECIFIED

    def is_asserted(self, field_name: str) -> bool:
        """True when the value came from the user or a template, not a guess."""
        return self.basis_for(field_name) in {FieldBasis.USER, FieldBasis.TEMPLATE}


class RequirementSignals(StrictModel):
    """Machine-readable workload characteristics consumed by every rule.

    Fields are optional on purpose: `None` means "not established", and the
    suitability engine converts that into an explicit gap rather than a silent
    zero.

    `validate_assignment` matters: rules and the AI merge write fields through
    `set_field`, and an out-of-range value must fail there instead of silently
    reaching the scoring engine.
    """

    model_config = ConfigDict(
        extra="forbid", use_enum_values=False, str_strip_whitespace=True, validate_assignment=True
    )

    # Scale / shape
    expected_users: int | None = Field(default=None, ge=0)
    monthly_requests: int | None = Field(default=None, ge=0)
    peak_requests_per_minute: int | None = Field(default=None, ge=0)
    peak_concurrency: int | None = Field(default=None, ge=0)
    latency_budget_ms: int | None = Field(default=None, ge=1)
    business_hours_only: bool | None = None

    # Execution shape
    typical_response_ms: int | None = Field(default=None, ge=1)
    longest_operation_minutes: float | None = Field(default=None, ge=0)
    long_running_jobs: bool | None = None
    cpu_or_memory_intensive: bool | None = None
    gpu_required: bool | None = None
    custom_runtime_required: bool | None = None
    startup_latency_sensitive: bool | None = None
    cold_start_sensitive: bool | None = None

    # Concurrency / coupling model
    event_driven: bool | None = None
    scheduled_batch: bool | None = None
    streaming_ingestion: bool | None = None
    persistent_connections: bool | None = None
    stateful_sessions: bool | None = None
    shared_locking_required: bool | None = None
    transactional_writes: bool | None = None
    high_fanout_reads: bool | None = None

    # Data plane
    relational_data: bool | None = None
    document_data: bool | None = None
    key_value_data: bool | None = None
    object_storage_needed: bool | None = None
    filesystem_semantics_required: bool | None = None
    search_needed: bool | None = None
    cache_needed: bool | None = None
    messaging_needed: bool | None = None
    dataset_size_gb: float | None = Field(default=None, ge=0)
    upload_size_mb: float | None = Field(default=None, ge=0)
    generated_files: bool | None = None
    sensitive_data: bool | None = None
    compliance_regime: str | None = Field(default=None, max_length=120)
    requires_audit_trail: bool | None = None
    backup_expectation_days: float | None = Field(default=None, ge=0)

    # Platform expectations
    public_internet_facing: bool | None = None
    third_party_integrations: list[str] = Field(default_factory=list)
    external_api_dependencies: list[str] = Field(default_factory=list)
    notification_required: bool | None = None
    pdf_or_reporting: bool | None = None
    multi_tenant: bool | None = None
    existing_on_prem_assets: bool | None = None

    provenance: dict[str, FieldBasis] = Field(default_factory=dict)
    notes: dict[str, str] = Field(default_factory=dict)

    @field_validator("third_party_integrations", "external_api_dependencies")
    @classmethod
    def _clean_list(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            cleaned = " ".join(str(item).split())[:80]
            if cleaned and cleaned not in out:
                out.append(cleaned)
        return out[:12]

    def set_field(self, name: str, value: Any, basis: FieldBasis, note: str | None = None) -> None:
        """Assign a signal and remember how it was established."""
        if name not in type(self).model_fields:
            raise KeyError(f"unknown signal field: {name}")
        setattr(self, name, value)
        self.provenance[name] = basis
        if note:
            self.notes[name] = note[:300]

    def basis_for(self, name: str) -> FieldBasis:
        return self.provenance.get(name, FieldBasis.UNSPECIFIED)

    def is_established(self, name: str) -> bool:
        return getattr(self, name, None) is not None

    def unknown_fields(self, tracked: list[str]) -> list[str]:
        return [name for name in tracked if getattr(self, name, None) is None]


class ExtractionResult(StrictModel):
    """Output of the requirement-extraction stage.

    This is the object the rules engine consumes; it is deliberately a
    separate type from `ApplicationRequirements` so that the AI layer can only
    ever propose signals, never a finished architecture.
    """

    requirements: ApplicationRequirements
    signals: RequirementSignals
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cap_lists(self) -> "ExtractionResult":
        self.assumptions = self.assumptions[:40]
        self.open_questions = self.open_questions[:12]
        return self
