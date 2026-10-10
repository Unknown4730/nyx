"""Top-level request/response contracts for the NYX analysis pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .architecture import (
    ArchitectureGraph,
    ComponentInventoryItem,
    MappingRow,
)
from .common import (
    SCHEMA_VERSION,
    AiAttemptStatus,
    CloudProvider,
    EngineMode,
    ProjectKind,
    StrictModel,
)
from .reports import (
    AiAttempt,
    CostReport,
    MigrationReport,
    SecurityReport,
    SuitabilityReport,
    WorkloadProfile,
)
from .requirements import (
    ApplicationRequirements,
    Assumption,
    OpenQuestion,
    RequirementSignals,
)

MAX_ERROR_ITEMS = 8


class AnalysisOptions(StrictModel):
    """Knobs that change *how* the analysis is produced, not what is true."""

    use_ai: bool = True
    providers: list[CloudProvider] = Field(
        default_factory=lambda: [CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE]
    )
    default_provider: CloudProvider | None = None
    max_operations_per_view: int = Field(default=14, ge=6, le=24)

    @field_validator("providers")
    @classmethod
    def _dedupe(cls, value: list[CloudProvider]) -> list[CloudProvider]:
        out: list[CloudProvider] = []
        for item in value:
            if item not in out and item != CloudProvider.UNDECIDED:
                out.append(item)
        if not out:
            raise ValueError("at least one real provider must be selected")
        return out


class AnalysisExportRequest(StrictModel):
    """`POST /api/analyze/export` body: an analysis request plus the wanted format."""

    requirements: ApplicationRequirements
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    format: str = "json"

    @field_validator("format")
    @classmethod
    def _normalise_format(cls, value: str) -> str:
        cleaned = (value or "json").strip().lower()
        if cleaned in {"md", "markdown", "report"}:
            return "markdown"
        if cleaned in {"json", ""}:
            return "json"
        raise ValueError("format must be 'json' or 'markdown'")


class AnalysisRequest(StrictModel):
    """Body of `POST /api/analyze`."""

    requirements: ApplicationRequirements
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)

    @model_validator(mode="after")
    def _propagate_preferred_provider(self) -> "AnalysisRequest":
        # A user preference selects the *default view*, it never removes the
        # other providers from the comparison.
        if self.options.default_provider is None and self.requirements.preferred_provider:
            preferred = self.requirements.preferred_provider
            if preferred in self.options.providers:
                self.options.default_provider = preferred
            else:
                self.options.default_provider = CloudProvider.AWS
        if self.options.default_provider is None:
            self.options.default_provider = self.options.providers[0]
        return self


class Limitation(StrictModel):
    """A disclosure the application must keep visible to the user."""

    code: str
    statement: str
    severity: Literal["info", "warning"] = "info"


class AnalysisResult(StrictModel):
    """The complete, versioned analysis artefact.

    This exact object is what the canvas renders, what the tables show, what the
    report prints and what gets persisted in SQLite.
    """

    schema_version: str = SCHEMA_VERSION
    analysis_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    engine_mode: EngineMode
    title: str
    application: ApplicationRequirements
    signals: RequirementSignals
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    workload: WorkloadProfile
    component_inventory: list[ComponentInventoryItem] = Field(default_factory=list)
    architectures: list[ArchitectureGraph] = Field(default_factory=list)
    primary_view: str = "proposed"
    mapping_table: list[MappingRow] = Field(default_factory=list)
    suitability: SuitabilityReport
    security: SecurityReport
    cost: CostReport
    migration: MigrationReport
    ai: AiAttempt
    providers: list[CloudProvider] = Field(default_factory=list)
    default_provider: CloudProvider = CloudProvider.AWS
    limitations: list[Limitation] = Field(default_factory=list)
    rule_pack_version: str = "2026.10"
    catalog_version: str = "2026.10"
    duration_ms: int = 0

    def architecture(self, view_id: str) -> ArchitectureGraph | None:
        for graph in self.architectures:
            if graph.id == view_id:
                return graph
        return None

    @property
    def available_views(self) -> list[str]:
        return [graph.id for graph in self.architectures]

    def to_json_dict(self) -> dict[str, Any]:
        """Canonical JSON used for persistence, export and rendering."""
        return self.model_dump(mode="json")

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> "AnalysisResult":
        return cls.model_validate(payload)


class ProjectSummary(StrictModel):
    id: str
    name: str
    kind: ProjectKind = ProjectKind.USER
    engine_mode: EngineMode
    application_type: str = "unknown"
    preferred_provider: str | None = None
    suitability_score: float
    suitability_outcome: str
    expected_users: int | None = None
    component_count: int = 0
    finding_count: int = 0
    created_at: datetime
    updated_at: datetime
    excerpt: str = ""

    @field_validator("excerpt")
    @classmethod
    def _clip(cls, value: str) -> str:
        return value[:180]


class ProjectDetail(StrictModel):
    id: str
    name: str
    kind: ProjectKind = ProjectKind.USER
    created_at: datetime
    updated_at: datetime
    requirements: ApplicationRequirements
    result: AnalysisResult


class ProjectCreateRequest(StrictModel):
    """Save an analysis.  The client may send either raw requirements or a full
    result; when a result is supplied the server re-validates it and *re-runs*
    nothing blindly — mismatches are rejected.
    """

    name: str | None = Field(default=None, max_length=90)
    requirements: ApplicationRequirements
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    result: dict[str, Any] | None = None
    client_id: str | None = Field(default=None, max_length=80)

    @field_validator("client_id")
    @classmethod
    def _safe_client_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned and not all(char.isalnum() or char in "-_" for char in cleaned):
            raise ValueError("client_id may only contain letters, digits, dash and underscore")
        return cleaned or None


class ProjectUpdateRequest(StrictModel):
    name: str | None = Field(default=None, min_length=2, max_length=90)
    notes: str | None = Field(default=None, max_length=2000)
    reanalyze: bool = False
    requirements: ApplicationRequirements | None = None


class HealthResponse(StrictModel):
    status: Literal["ok", "degraded"]
    service: str
    title: str
    tagline: str
    version: str
    schema_version: str = SCHEMA_VERSION
    engine_mode: str = EngineMode.DETERMINISTIC.value
    ai: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApiError(StrictModel):
    code: str
    message: str
    details: list[str] = Field(default_factory=list)
    retryable: bool = False


class ErrorResponse(StrictModel):
    error: ApiError


class AiStatusPayload(StrictModel):
    status: AiAttemptStatus
    message: str
    model: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
