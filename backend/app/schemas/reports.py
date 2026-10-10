"""Analysis output models: suitability, security, cost and migration.

Each report is self-describing: it carries its own methodology, evidence and
limitations so the frontend never has to invent an explanation, and so an
exported report contains exactly what the UI displayed.
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .common import (
    CostCategory,
    EffortLevel,
    FindingCertainty,
    RecommendedPattern,
    Severity,
    StrictModel,
    SuitabilityOutcome,
    DeploymentTarget,
)

# ---------------------------------------------------------------------------
# Workload classification
# ---------------------------------------------------------------------------


class WorkloadProfile(StrictModel):
    classification: str
    headline: str = ""
    signals: list[str] = Field(default_factory=list)
    request_shape: str = "unspecified"
    data_shape: str = "unspecified"
    execution_shape: str = "unspecified"


# ---------------------------------------------------------------------------
# Serverless suitability
# ---------------------------------------------------------------------------


class SuitabilityFactor(StrictModel):
    """One weighted factor in the documented scoring formula."""

    id: str
    name: str
    weight: float = Field(ge=0, le=1)
    impact: float = Field(ge=-1, le=1)
    contribution: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    explanation: str = ""
    direction: str = "neutral"  # positive | negative | neutral
    basis: str = "inferred"  # user_provided | inferred | default | missing


class ComponentSuitability(StrictModel):
    component_id: str
    component_label: str
    score: float = Field(ge=0, le=100)
    outcome: SuitabilityOutcome
    recommendation: DeploymentTarget
    recommendation_reason: str = ""
    factors: list[SuitabilityFactor] = Field(default_factory=list)
    reasons_for: list[str] = Field(default_factory=list)
    reasons_against: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    provisional: bool = False


class SuitabilityBand(StrictModel):
    outcome: SuitabilityOutcome
    min_score: float = Field(ge=0, le=100)
    description: str


class SuitabilityMethodology(StrictModel):
    formula: str
    band_source: str
    weight_source: str
    bands: list[SuitabilityBand] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SuitabilityReport(StrictModel):
    score: float = Field(ge=0, le=100)
    provisional_score: float | None = Field(default=None, ge=0, le=100)
    outcome: SuitabilityOutcome
    headline: str = ""
    rationale: str = ""
    recommended_pattern: RecommendedPattern
    factors: list[SuitabilityFactor] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    components: list[ComponentSuitability] = Field(default_factory=list)
    methodology: SuitabilityMethodology
    missing_inputs: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent_outcome(self) -> "SuitabilityReport":
        if self.outcome == SuitabilityOutcome.FURTHER_ASSESSMENT and not self.missing_inputs:
            # A "further assessment" verdict must always point at what is missing.
            self.missing_inputs = ["Component-level details required to finish scoring."]
        return self


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class SecurityFinding(StrictModel):
    id: str
    title: str
    severity: Severity
    category: str
    explanation: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str = ""
    certainty: FindingCertainty
    component_ids: list[str] = Field(default_factory=list)
    architecture_view: str | None = None
    references: list[str] = Field(default_factory=list)


class VerificationGap(StrictModel):
    id: str
    question: str
    why_it_matters: str
    component_ids: list[str] = Field(default_factory=list)
    suggested_check: str = ""


class SecurityReport(StrictModel):
    scope_statement: str
    audited_view: str
    findings: list[SecurityFinding] = Field(default_factory=list)
    # Findings recorded against the conventional view.  They are kept separate so
    # the UI can show "here is what the redesign removes" without pretending the
    # proposal still has them.
    baseline_findings: list[SecurityFinding] = Field(default_factory=list)
    verification_gaps: list[VerificationGap] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    by_certainty: dict[str, int] = Field(default_factory=dict)
    positives: list[str] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("counts", mode="before")
    @classmethod
    def _default_counts(cls, value: object) -> dict[str, int]:
        return value if isinstance(value, dict) else {}

    def findings_for(self, component_id: str) -> list[SecurityFinding]:
        return [item for item in self.findings if component_id in item.component_ids]

    @property
    def highest_severity(self) -> Severity:
        order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
        for level in order:
            if any(item.severity == level for item in self.findings):
                return level
        return Severity.INFO


# ---------------------------------------------------------------------------
# Relative cost
# ---------------------------------------------------------------------------


class CostLineItem(StrictModel):
    id: str
    label: str
    category: CostCategory
    quantity: float
    unit: str
    ricu: float = Field(ge=0)
    basis: str = ""


class CostScenario(StrictModel):
    id: str
    label: str
    description: str = ""
    fixed_ricu: float = Field(ge=0)
    variable_ricu: float = Field(ge=0)
    operational_ricu: float = Field(ge=0)
    total_ricu: float = Field(ge=0)
    line_items: list[CostLineItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reconcile_total(self) -> "CostScenario":
        recomputed = round(self.fixed_ricu + self.variable_ricu + self.operational_ricu, 2)
        if abs(recomputed - self.total_ricu) > 0.51:
            self.total_ricu = recomputed
        return self


class CostSensitivity(StrictModel):
    """How the comparison moves when a stated assumption changes."""

    name: str
    low_label: str
    high_label: str
    conventional_delta_pct: float
    proposed_delta_pct: float
    note: str = ""


class CostReport(StrictModel):
    unit: str = "RICU"
    unit_name: str = "Relative Infrastructure Cost Unit"
    period: str = "per month"
    disclaimer: str = ""
    scenarios: list[CostScenario] = Field(default_factory=list)
    comparison: dict[str, float] = Field(default_factory=dict)
    fixed_share: dict[str, float] = Field(default_factory=dict)
    sensitivity: list[CostSensitivity] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
    rate_table: list[dict[str, object]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    insufficient_inputs: list[str] = Field(default_factory=list)

    def scenario(self, scenario_id: str) -> CostScenario | None:
        for item in self.scenarios:
            if item.id == scenario_id:
                return item
        return None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class MigrationChange(StrictModel):
    component_id: str
    component_label: str
    change: str
    complexity: EffortLevel
    reason: str = ""
    dependencies: list[str] = Field(default_factory=list)
    compatibility_issues: list[str] = Field(default_factory=list)


class MigrationPhase(StrictModel):
    id: str
    index: int = Field(ge=1)
    title: str
    objective: str = ""
    activities: list[str] = Field(default_factory=list)
    components_touched: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    risk: Severity = Severity.LOW
    effort: EffortLevel = EffortLevel.MODERATE


class MigrationReport(StrictModel):
    overall_complexity: EffortLevel
    complexity_score: float = Field(ge=0, le=100)
    complexity_drivers: list[str] = Field(default_factory=list)
    components_requiring_modification: list[MigrationChange] = Field(default_factory=list)
    dependencies_to_review: list[str] = Field(default_factory=list)
    compatibility_issues: list[str] = Field(default_factory=list)
    validation_requirements: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    phases: list[MigrationPhase] = Field(default_factory=list)
    sequencing_rationale: str = ""
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ordered_phases(self) -> "MigrationReport":
        self.phases = sorted(self.phases, key=lambda phase: phase.index)
        for position, phase in enumerate(self.phases, start=1):
            phase.index = position
        return self

    @property
    def modified_component_count(self) -> int:
        return len(self.components_requiring_modification)


# ---------------------------------------------------------------------------
# Provider / AI transparency
# ---------------------------------------------------------------------------


class AiAttempt(StrictModel):
    status: str
    mode: str
    provider: str | None = None
    model: str | None = None
    attempts: int = 0
    latency_ms: int | None = None
    accepted_fields: list[str] = Field(default_factory=list)
    rejected_fields: list[str] = Field(default_factory=list)
    note: str = ""
