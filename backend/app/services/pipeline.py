"""The analysis pipeline: the only place where stages are wired together.

Stage order mirrors the documented pipeline:

    requirements → extraction → (optional AI proposal, validated)
    → workload classification → component identification → suitability
    → architecture generation → cloud mapping → security → cost
    → migration → assembled result

Every stage is a separate module with its own tests; this file only orchestrates
and assembles disclosures.  Nothing here calls the network except through the AI
provider abstraction, and nothing here is required for the deterministic path.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from app.schemas.analysis import AnalysisRequest, AnalysisResult, Limitation
from app.schemas.common import (
    SCHEMA_VERSION,
    AiAttemptStatus,
    ApplicationType,
    CloudProvider,
    EngineMode,
)
from app.schemas.reports import AiAttempt
from datetime import datetime, timezone
from app.services.ai_provider import (
    CompletionOutcome,
    NullProvider,
    SYSTEM_PROMPT,
    build_provider,
    build_user_prompt,
)
from app.services.architecture_engine import ArchitectureEngine, build_mapping_rows
from app.services.component_identifier import identify
from app.services.cost_estimator import CostEstimator
from app.services.migration_planner import MigrationPlanner
from app.services.requirement_extractor import RequirementExtractionService
from app.services.security_analyzer import SecurityAnalyzer
from app.services.serverless_suitability import SuitabilityService
from app.services.workload_classifier import classify

logger = logging.getLogger("nyx.pipeline")

RULE_PACK_VERSION = "2026.10"


class AnalysisPipeline:
    def __init__(self, ai_provider: object | None = None) -> None:
        self.extraction = RequirementExtractionService()
        self.suitability = SuitabilityService()
        self.architecture = ArchitectureEngine()
        self.security = SecurityAnalyzer()
        self.cost = CostEstimator()
        self.migration = MigrationPlanner()
        self._ai_provider = ai_provider

    # ------------------------------------------------------------------- entry

    def ai_provider(self) -> object:
        if self._ai_provider is None:
            self._ai_provider = build_provider()
        return self._ai_provider

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        started = time.perf_counter()
        requirements = request.requirements.model_copy(deep=True)

        extraction = self.extraction.extract(requirements)
        ai_outcome = self._attempt_ai(request, extraction.signals)
        accepted: list[str] = []
        rejected: list[str] = []
        if ai_outcome.succeeded and ai_outcome.proposal is not None:
            try:
                _, accepted, rejected = self.extraction.merge_ai_proposal(extraction, ai_outcome.proposal)
            except Exception as exc:  # never let an AI merge break the analysis
                logger.warning("AI merge failed, continuing with deterministic extraction: %s", exc)
                ai_outcome.note = f"{ai_outcome.note} Merge rejected locally: {type(exc).__name__}."
                ai_outcome.status = AiAttemptStatus.FAILED_VALIDATION
        engine_mode = EngineMode.AI_ASSISTED if (ai_outcome.succeeded and accepted) else EngineMode.DETERMINISTIC

        requirements = extraction.requirements
        signals = extraction.signals
        workload = classify(requirements, signals)
        plans, inventory = identify(requirements, signals)
        suitability = self.suitability.assess(requirements, signals, plans)

        providers = request.options.providers
        graphs = self.architecture.build(
            plans,
            suitability,
            workload,
            providers=providers,
            max_nodes=request.options.max_operations_per_view,
            sensitive=bool(signals.sensitive_data)
            or requirements.application_type
            in {ApplicationType.EXAMINATION_PLATFORM, ApplicationType.LEARNING_PLATFORM},
            persistent_connections=bool(signals.persistent_connections),
            object_event_driven=bool(signals.event_driven and signals.object_storage_needed),
        )
        conventional = next(graph for graph in graphs if graph.id == "conventional")
        proposed = next(graph for graph in graphs if graph.id == "proposed")
        mapping_rows = build_mapping_rows(proposed)

        security_report = self.security.analyze(
            proposed,
            conventional,
            sensitive_data_expected=bool(signals.sensitive_data),
            multi_tenant=bool(signals.multi_tenant),
            audit_required=bool(signals.requires_audit_trail) if signals.requires_audit_trail is not None else None,
            coordination_required=bool(signals.shared_locking_required),
            cold_start_sensitive=bool(signals.cold_start_sensitive or signals.startup_latency_sensitive),
            latency_budget_ms=signals.latency_budget_ms,
        )
        cost_report = self.cost.estimate(requirements, signals)
        migration_report = self.migration.plan(
            conventional, proposed, suitability, security_report, signals, requirements
        )

        result = AnalysisResult(
            schema_version=SCHEMA_VERSION,
            analysis_id=new_analysis_id(),
            created_at=_now(),
            engine_mode=engine_mode,
            title=requirements.name,
            application=requirements,
            signals=signals,
            assumptions=extraction.assumptions,
            open_questions=extraction.open_questions,
            workload=workload,
            component_inventory=inventory,
            architectures=graphs,
            primary_view="proposed",
            mapping_table=mapping_rows,
            suitability=suitability,
            security=security_report,
            cost=cost_report,
            migration=migration_report,
            providers=list(providers),
            default_provider=request.options.default_provider or CloudProvider.AWS,
            ai=AiAttempt(
                status=ai_outcome.status.value,
                mode=engine_mode.value,
                provider=ai_outcome.provider,
                model=ai_outcome.model,
                attempts=ai_outcome.attempts,
                latency_ms=ai_outcome.latency_ms,
                accepted_fields=sorted(set(accepted)),
                rejected_fields=sorted(set(rejected + ai_outcome.rejected_fields)),
                note=ai_outcome.note,
            ),
            limitations=self._limitations(engine_mode, ai_outcome, extraction.open_questions, cost_report, signals),
            rule_pack_version=RULE_PACK_VERSION,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        logger.info(
            "analysis %s completed in %dms mode=%s score=%.1f outcome=%s nodes=%d",
            result.analysis_id,
            result.duration_ms,
            engine_mode.value,
            suitability.score,
            suitability.outcome.value,
            len(proposed.components),
        )
        return result

    # ------------------------------------------------------------------- AI layer

    def _attempt_ai(self, request: AnalysisRequest, signals: object) -> CompletionOutcome:
        provider = self.ai_provider()
        if not request.options.use_ai:
            return CompletionOutcome(
                status=AiAttemptStatus.DISABLED_BY_REQUEST,
                note="AI assist was switched off for this run; the deterministic rules engine produced the result.",
                provider=getattr(provider, "name", "none"),
            )
        if isinstance(provider, NullProvider) or not getattr(provider, "available", lambda: False)():
            return CompletionOutcome(
                status=AiAttemptStatus.NOT_CONFIGURED,
                note=(
                    "No AI endpoint and key are configured, so NYX used its deterministic rules engine. "
                    "Everything below is produced by local rules — nothing was simulated or filled in with guesses."
                ),
                provider=getattr(provider, "name", "none"),
            )
        requirements = request.requirements
        known = {
            "application_type": _value(requirements.application_type),
            "traffic_pattern": _value(requirements.traffic_pattern),
            "availability": _value(requirements.availability),
            "budget": _value(requirements.budget),
            "preferred_provider": _value(requirements.preferred_provider),
            "expected_users": requirements.expected_users,
            "data_storage": [_value(item) for item in requirements.data_storage],
            "additional_requirements": requirements.additional_requirements,
        }
        user_prompt = build_user_prompt(requirements, known)
        try:
            outcome = provider.complete_json(system=SYSTEM_PROMPT, user=user_prompt)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - defensive: provider must not break the request
            logger.exception("AI provider raised unexpectedly")
            return CompletionOutcome(
                status=AiAttemptStatus.FAILED_PROVIDER,
                note=f"AI provider raised {type(exc).__name__}; the deterministic engine continued the analysis.",
                provider=getattr(provider, "name", "none"),
            )
        if outcome.succeeded:
            outcome.note = (
                (outcome.note or "") + " Only requirement classification came from the model; the architecture, "
                "suitability, security, cost and migration stages are rule-based."
            ).strip()
        return outcome

    # -------------------------------------------------------------- disclosures

    @staticmethod
    def _limitations(
        engine_mode: EngineMode,
        ai_outcome: CompletionOutcome,
        open_questions: list[object],
        cost_report: object,
        signals: object,
    ) -> list[Limitation]:
        items = [
            Limitation(
                code="LIM-SCOPE",
                statement=(
                    "Generated architectures are conceptual blueprints. NYX does not provision, deploy or modify "
                    "any cloud account, and a provider switch changes labels only."
                ),
                severity="warning",
            ),
            Limitation(
                code="LIM-HEURISTIC",
                statement=(
                    f"Suitability scores come from the versioned local rule pack ({RULE_PACK_VERSION}). They are "
                    "explainable heuristics, not an industry benchmark or a certification."
                ),
            ),
            Limitation(
                code="LIM-COST",
                statement=(
                    "Cost figures are Relative Infrastructure Cost Units (RICU): a dimensionless index defined "
                    "inside NYX, not currency, not a provider price list and not a savings guarantee."
                ),
            ),
            Limitation(
                code="LIM-SECURITY",
                statement=(
                    "The security review is architecture-level only. It is not a penetration test, a "
                    "vulnerability scan or a compliance audit, and it can only reason about what was described."
                ),
            ),
            Limitation(
                code="LIM-CATALOG",
                statement=(
                    "Cloud service identities come from a local catalogue snapshot. Limits, quotas, region "
                    "availability and product names must be re-verified before implementation decisions."
                ),
            ),
            Limitation(
                code="LIM-MIGRATION",
                statement=(
                    "The roadmap deliberately omits durations and person-days: team size, test coverage and code "
                    "quality are outside this analysis, so any time figure would be invented."
                ),
            ),
        ]
        if engine_mode == EngineMode.DETERMINISTIC:
            items.append(
                Limitation(
                    code="LIM-AI",
                    statement=(
                        f"This analysis was produced in deterministic mode "
                        f"(AI status: {ai_outcome.status.value}). No language model contributed to it."
                        + (f" Provider note: {ai_outcome.note}" if ai_outcome.note else "")
                    ),
                )
            )
        else:
            items.append(
                Limitation(
                    code="LIM-AI",
                    statement=(
                        "The language model only classified requirements; every accepted value passed schema "
                        "validation, and all architecture, suitability, security, cost and migration output is "
                        "produced by deterministic rules."
                    ),
                )
            )
        if open_questions:
            items.append(
                Limitation(
                    code="LIM-INPUTS",
                    statement=(
                        f"{len(open_questions)} critical requirement(s) were not established from the input, so the "
                        "affected factors were scored as unknown rather than guessed. See the open questions."
                    ),
                    severity="warning",
                )
            )
        insufficient = getattr(cost_report, "insufficient_inputs", []) or []
        if insufficient:
            items.append(
                Limitation(
                    code="LIM-COST-INPUT",
                    statement="Cost comparison is incomplete: " + " ".join(insufficient),
                    severity="warning",
                )
            )
        if getattr(signals, "compliance_regime", None):
            items.append(
                Limitation(
                    code="LIM-COMPLIANCE",
                    statement=(
                        f"A compliance regime ({signals.compliance_regime}) was mentioned. NYX records it as a "
                        "design constraint but performs no compliance assessment."
                    ),
                    severity="warning",
                )
            )
        return items


def new_analysis_id() -> str:
    return f"nyx-{uuid4().hex[:10]}"


def _value(item: object) -> object:
    if item is None:
        return None
    return getattr(item, "value", str(item))


def _now() -> datetime:
    return datetime.now(timezone.utc)


_default_pipeline: AnalysisPipeline | None = None


def get_pipeline() -> AnalysisPipeline:
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = AnalysisPipeline()
    return _default_pipeline


def run_analysis(requirements: object, *, use_ai: bool = True) -> AnalysisResult:
    """Convenience entry point used by seeding and tests."""
    from app.schemas.analysis import AnalysisOptions

    request = AnalysisRequest(
        requirements=requirements,  # type: ignore[arg-type]
        options=AnalysisOptions(use_ai=use_ai),
    )
    return get_pipeline().run(request)


__all__ = ["AnalysisPipeline", "get_pipeline", "run_analysis", "RULE_PACK_VERSION"]
