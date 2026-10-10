"""Requirement extraction: user input + lexical rules (+ optional AI) → signals.

The extractor never invents architecture.  It produces an
`ExtractionResult` (validated requirements, workload signals, assumptions and
open questions) which every downstream deterministic stage consumes.
"""

from __future__ import annotations

import re
from typing import Any

from app.rules import requirement_rules as rules
from app.schemas.ai import AiExtractionProposal
from app.schemas.common import (
    AvailabilityExpectation,
    BudgetPreference,
    CloudProvider,
    DataStorageKind,
    FieldBasis,
    TrafficPattern,
    ApplicationType,
)
from app.schemas.requirements import (
    ApplicationRequirements,
    Assumption,
    ExtractionResult,
    FieldProvenance,
    OpenQuestion,
    RequirementSignals,
)

DATASET_HINT_RE = re.compile(
    r"(database|dataset|data (?:volume|size|warehouse)|total (?:data|storage)|archive|retention of)"
)

# Fields whose absence changes the analysis materially.
CRITICAL_UNCERTAINTIES: list[tuple[str, str, str]] = [
    (
        "expected_users",
        "How many users does the application need to serve at peak?",
        "Scale decides the elasticity argument, the database connection budget and every cost line item.",
    ),
    (
        "traffic_pattern",
        "Is the traffic flat, daily-cyclical, or concentrated into peaks and events?",
        "Traffic variability is the highest-weighted factor in the suitability score.",
    ),
    (
        "availability",
        "What availability is promised to users (for example 99.5% or 99.99%)?",
        "Strict SLOs change which managed services and quotas are acceptable.",
    ),
    (
        "longest_operation_minutes",
        "How long does the longest single operation or job take?",
        "Managed function platforms cap execution time, which decides what can be a function at all.",
    ),
    (
        "latency_budget_ms",
        "Is there a response-time target users will notice (for example under 300 ms)?",
        "Cold-start tolerance depends on it, as does the choice of provisioned concurrency.",
    ),
    (
        "sensitive_data",
        "Does the system store personal, financial or academic records?",
        "Data classification drives encryption, identity and access findings in the security analysis.",
    ),
]


# Longest single execution that a mainstream function runtime will complete.  It
# is a documented provider limit (AWS Lambda 15 min), not a tuned constant.
FUNCTION_CEILING_MINUTES = 15.0


class RequirementExtractionService:
    """Deterministic extractor with an optional AI proposal merged on top."""

    def extract(self, requirements: ApplicationRequirements) -> ExtractionResult:
        # Work on a copy: extraction enriches the requirement document with derived
        # values, and the caller's object (a validated request, or a stored project)
        # must never be mutated in place.
        requirements = requirements.model_copy(deep=True)
        signals = RequirementSignals()
        matched: list[str] = []
        notes: list[str] = []

        # ---- 1. Facts asserted by the user or the template -------------------
        if requirements.expected_users is not None:
            signals.set_field(
                "expected_users",
                requirements.expected_users,
                requirements.basis_for("expected_users"),
                "Taken from the form field, not inferred.",
            )
            matched.append("form.expected_users")
        for kind in requirements.data_storage:
            self._apply_storage_kind(signals, kind, requirements.basis_for("data_storage"), matched)

        # ---- 2. Free-text lexical rules --------------------------------------
        text = " ".join(filter(None, [requirements.description, requirements.additional_requirements]))
        outcome = rules.evaluate_text(text, signals)
        for name, value in outcome.signal_updates.items():
            if name == "availability_hint":
                continue
            if name == "traffic_pattern":
                continue
            if not signals.is_established(name):
                signals.set_field(name, value, FieldBasis.INFERRED, "Matched lexical rule " + outcome_hits_for(outcome, name))
        matched.extend(outcome.matched_rules)

        if requirements.traffic_pattern is None:
            detected = rules.detect_traffic_pattern(text)
            if detected is not None:
                requirements.traffic_pattern = detected
                requirements.provenance["traffic_pattern"] = FieldProvenance(
                    basis=FieldBasis.INFERRED, note="Inferred from wording in the description."
                )
        if requirements.application_type in {None, ApplicationType.UNKNOWN}:
            detected_type = rules.detect_application_type(text)
            if detected_type is not None:
                requirements.application_type = detected_type
                requirements.provenance["application_type"] = FieldProvenance(
                    basis=FieldBasis.INFERRED, note="Inferred from the wording of the description."
                )
        if requirements.availability is None:
            detected_availability = rules.detect_availability(text)
            if detected_availability is not None:
                requirements.availability = detected_availability
                requirements.provenance["availability"] = FieldProvenance(
                    basis=FieldBasis.INFERRED, note="Inferred from an availability statement in the description."
                )
        if requirements.budget is None:
            detected_budget = rules.detect_budget(text)
            if detected_budget is not None:
                requirements.budget = detected_budget
                requirements.provenance["budget"] = FieldProvenance(
                    basis=FieldBasis.INFERRED, note="Inferred from cost wording in the description."
                )
        if not requirements.data_storage:
            detected_storage = rules.detect_storage_kinds(text)
            if detected_storage:
                requirements.data_storage = detected_storage
                requirements.provenance["data_storage"] = FieldProvenance(
                    basis=FieldBasis.INFERRED, note="Inferred from the data wording in the description."
                )
                for kind in detected_storage:
                    self._apply_storage_kind(signals, kind, FieldBasis.INFERRED, matched)

        # The dataset-size rule is only trusted when the text talks about stored
        # data volume rather than one big upload.
        if signals.dataset_size_gb is not None and not DATASET_HINT_RE.search(text.lower()):
            upload_mb = signals.upload_size_mb
            if upload_mb is not None and abs(signals.dataset_size_gb * 1024 - upload_mb) < 1:
                signals.dataset_size_gb = None
                signals.provenance.pop("dataset_size_gb", None)
                notes.append("A size figure was found but only describes individual files, not total data volume.")

        # ---- 3. Derived planning figures (documented formulas) --------------
        self._derive_capacity(signals, requirements, matched)

        # ---- 3b. Consistency pass between related signals -------------------
        # A stated operation length that exceeds the function-runtime ceiling *is*
        # a long-running job; leaving the two signals disagreeing would let the
        # suitability engine score an obviously-resident workload as a function.
        longest = signals.longest_operation_minutes
        if longest is not None and longest > FUNCTION_CEILING_MINUTES and not signals.is_established("long_running_jobs"):
            signals.set_field(
                "long_running_jobs",
                True,
                FieldBasis.INFERRED,
                f"Stated longest operation of {longest:g} minutes exceeds the ~{FUNCTION_CEILING_MINUTES:g} minute "
                "function ceiling, so this work is treated as long-running.",
            )
            matched.append("consistency.long_running_jobs")
        if signals.gpu_required and not signals.is_established("cpu_or_memory_intensive"):
            signals.set_field(
                "cpu_or_memory_intensive",
                True,
                FieldBasis.INFERRED,
                "GPU work is by definition outside the general-purpose function profile.",
            )
            matched.append("consistency.cpu_intensive_from_gpu")
        if signals.persistent_connections and signals.stateful_sessions is None:
            signals.set_field(
                "stateful_sessions",
                True,
                FieldBasis.INFERRED,
                "Connections that stay open hold session state on that instance.",
            )
            matched.append("consistency.stateful_from_sockets")

        # ---- 3c. Surface the derived figures the form left blank -----------
        # The report and the form both read `application`, so a number the rules
        # derived has to appear there too — with its basis, never silently.
        if requirements.expected_users is None and signals.expected_users:
            requirements.expected_users = signals.expected_users
            requirements.provenance["expected_users"] = FieldProvenance(
                basis=FieldBasis.INFERRED,
                note="Derived from the description by the requirement rules, not typed into the form.",
            )
            matched.append("backfill.expected_users")

        # ---- 4. Assumptions + open questions --------------------------------
        assumptions = self._assumptions(signals, requirements)
        open_questions = self._open_questions(signals, requirements)
        return ExtractionResult(
            requirements=requirements,
            signals=signals,
            assumptions=assumptions,
            open_questions=open_questions,
            extraction_notes=notes,
            matched_rules=sorted(set(matched)),
        )

    # ------------------------------------------------------------------ helpers

    def _apply_storage_kind(
        self,
        signals: RequirementSignals,
        kind: DataStorageKind,
        basis: FieldBasis,
        matched: list[str],
    ) -> None:
        mapping = {
            DataStorageKind.RELATIONAL: "relational_data",
            DataStorageKind.DOCUMENT: "document_data",
            DataStorageKind.KEY_VALUE: "key_value_data",
            DataStorageKind.OBJECT_STORAGE: "object_storage_needed",
            DataStorageKind.FILE_SHARE: "filesystem_semantics_required",
            DataStorageKind.CACHE_SESSION: "cache_needed",
            DataStorageKind.SEARCH_INDEX: "search_needed",
            DataStorageKind.ANALYTICAL_WAREHOUSE: "pdf_or_reporting",
            DataStorageKind.TIME_SERIES: "streaming_ingestion",
            DataStorageKind.QUEUE_OR_LOG: "messaging_needed",
        }
        field_name = mapping.get(kind)
        if field_name and not signals.is_established(field_name):
            signals.set_field(field_name, True, basis, f"Selected storage profile: {kind.value.replace('_', ' ')}.")
            matched.append(f"storage.{kind.value}")

    def _derive_capacity(
        self,
        signals: RequirementSignals,
        requirements: ApplicationRequirements,
        matched: list[str],
    ) -> None:
        """Fill capacity figures with explicit formulas, labelled as assumptions."""
        users = signals.expected_users
        pattern = requirements.traffic_pattern or TrafficPattern.UNKNOWN
        peak_ratio = rules.PEAK_RATIO_BY_TRAFFIC[pattern]

        sessions = rules.SESSIONS_PER_USER_BY_TYPE.get(
            requirements.application_type, rules.SESSIONS_PER_USER_BY_TYPE[ApplicationType.UNKNOWN]
        )
        if users:
            derived = int(users * sessions * rules.ACTIVE_DAYS_PER_MONTH * rules.REQUESTS_PER_SESSION)
            if signals.monthly_requests is None:
                signals.set_field(
                    "monthly_requests",
                    derived,
                    FieldBasis.DEFAULT,
                    f"Estimated as {users:,} users x {sessions:g} sessions/day x "
                    f"{rules.ACTIVE_DAYS_PER_MONTH} active days x {rules.REQUESTS_PER_SESSION} requests/session.",
                )
                matched.append("derive.monthly_requests")
            elif derived > signals.monthly_requests * 2:
                # A stated volume always wins; we only record the discrepancy so the
                # reader can see the user-count cross-check.
                signals.notes["monthly_requests"] = (
                    (signals.notes.get("monthly_requests") or "")
                    + f" Cross-check: {users:,} users x {sessions:g} sessions/day would imply about {derived:,} "
                    "requests/month, well above the stated figure — verify which one is request volume."
                ).strip()
                matched.append("derive.monthly_requests.crosscheck")

        if signals.typical_response_ms is None:
            defaults = {
                ApplicationType.EXAMINATION_PLATFORM: 220,
                ApplicationType.LEARNING_PLATFORM: 180,
                ApplicationType.ECOMMERCE: 140,
                ApplicationType.LOGISTICS_MARKETPLACE: 150,
                ApplicationType.BATCH_PROCESSING: 900,
                ApplicationType.DATA_PIPELINE: 900,
                ApplicationType.REALTIME_COLLABORATION: 90,
                ApplicationType.STREAMING_MEDIA: 200,
                ApplicationType.IOT_INGESTION: 40,
                ApplicationType.CONTENT_SITE: 90,
                ApplicationType.API_SERVICE: 80,
                ApplicationType.MOBILE_BACKEND: 150,
                ApplicationType.INTERNAL_TOOL: 250,
            }
            value = defaults.get(requirements.application_type, 350)
            signals.set_field(
                "typical_response_ms",
                value,
                FieldBasis.DEFAULT,
                "Default response-time estimate for the detected application type "
                f"({requirements.application_type.value.replace('_', ' ')}), used for duration-sensitive rules.",
            )
            matched.append("derive.typical_response_ms")

        if signals.monthly_requests and not signals.is_established("peak_requests_per_minute"):
            average_per_minute = signals.monthly_requests / (rules.ACTIVE_DAYS_PER_MONTH * 60 * 60)
            signals.set_field(
                "peak_requests_per_minute",
                max(1, int(round(average_per_minute * peak_ratio))),
                FieldBasis.DEFAULT,
                f"Average {average_per_minute:.1f} req/min x peak factor {peak_ratio:g} for the "
                f"{pattern.value.replace('_', ' ')} pattern.",
            )
            matched.append("derive.peak_rpm")

        # Little's law: in-flight work = arrival rate x service time.  This is what
        # actually competes for database connections and platform concurrency limits.
        if signals.monthly_requests and signals.peak_requests_per_minute and signals.typical_response_ms:
            in_flight = (signals.peak_requests_per_minute / 60.0) * (signals.typical_response_ms / 1000.0)
            active_share = rules.CONCURRENCY_SHARE_BY_TRAFFIC[pattern]
            signals.set_field(
                "peak_concurrency",
                max(1, int(round(in_flight))),
                FieldBasis.DEFAULT,
                f"Little's law: {signals.peak_requests_per_minute:,} peak req/min ÷ 60 x "
                f"{signals.typical_response_ms} ms = {in_flight:.1f} in-flight requests. Separately, "
                f"~{active_share:.0%} of {users:,} users ({int(users * active_share):,}) would be *active* at peak, "
                "which is an engagement figure, not concurrent connections.",
            )
            matched.append("derive.peak_concurrency.littles_law")
        elif users and signals.peak_concurrency is None:
            share = rules.CONCURRENCY_SHARE_BY_TRAFFIC[pattern]
            signals.set_field(
                "peak_concurrency",
                max(1, int(round(users * share))),
                FieldBasis.DEFAULT,
                f"Assumed {share:.0%} of users active simultaneously under a "
                f"{pattern.value.replace('_', ' ')} pattern (no request volume stated to derive from).",
            )
            matched.append("derive.peak_concurrency.share")

    def _assumptions(
        self, signals: RequirementSignals, requirements: ApplicationRequirements
    ) -> list[Assumption]:
        assumptions: list[Assumption] = []
        index = 0

        def add(statement: str, basis: FieldBasis, impact: str, field: str | None, rule: str | None = None) -> None:
            nonlocal index
            index += 1
            assumptions.append(
                Assumption(
                    id=f"ASM-{index:02d}",
                    statement=statement,
                    basis=basis,
                    impact=impact,
                    field=field,
                    rule=rule,
                )
            )

        for name, basis in sorted(signals.provenance.items()):
            if name in {"provenance", "notes"}:
                continue
            if basis == FieldBasis.DEFAULT:
                note = signals.notes.get(name, "")
                add(
                    f"`{name}` was not stated; the engine used {type(signals).model_fields[name].default!r} "
                    f"→ {getattr(signals, name)!r}. {note}".strip(),
                    FieldBasis.DEFAULT,
                    "medium",
                    name,
                )
            elif basis == FieldBasis.INFERRED:
                note = signals.notes.get(name, "")
                add(
                    f"`{name}` inferred as {getattr(signals, name)!r} from the description. {note}".strip(),
                    FieldBasis.INFERRED,
                    "medium" if name not in {"longest_operation_minutes", "expected_users", "gpu_required"} else "high",
                    name,
                )
            elif basis == FieldBasis.AI:
                add(
                    f"`{name}` = {getattr(signals, name)!r} was proposed by the AI layer and accepted after schema validation.",
                    FieldBasis.AI,
                    "medium",
                    name,
                )

        for field_name in ("traffic_pattern", "availability", "application_type", "budget", "data_storage"):
            provenance = requirements.provenance.get(field_name)
            if provenance and provenance.basis == FieldBasis.INFERRED:
                value = getattr(requirements, field_name)
                add(
                    f"Requirement `{field_name}` set to {_render(value)} because the description implied it.",
                    FieldBasis.INFERRED,
                    "high" if field_name in {"traffic_pattern", "availability"} else "medium",
                    field_name,
                )

        if requirements.expected_users is None and signals.expected_users is None:
            add(
                "No user count was supplied, so request volume and cost quantities stay unknown "
                "instead of being guessed.",
                FieldBasis.UNSPECIFIED,
                "high",
                "expected_users",
            )
        return assumptions

    def _open_questions(
        self, signals: RequirementSignals, requirements: ApplicationRequirements
    ) -> list[OpenQuestion]:
        questions: list[OpenQuestion] = []
        for name, question, why in CRITICAL_UNCERTAINTIES:
            if name.startswith("_"):
                continue
            established = (
                getattr(signals, name, None) is not None
                if hasattr(signals, name)
                else getattr(requirements, name, None) is not None
            )
            if name in {"traffic_pattern", "availability"}:
                established = getattr(requirements, name, None) not in {None, TrafficPattern.UNKNOWN,
                                                                        AvailabilityExpectation.UNKNOWN}
            if not established:
                questions.append(
                    OpenQuestion(id=f"Q-{len(questions) + 1:02d}", question=question, field=name, why_it_matters=why)
                )
        return questions[:6]

    def merge_ai_proposal(
        self, extraction: ExtractionResult, proposal: AiExtractionProposal
    ) -> tuple[ExtractionResult, list[str], list[str]]:
        """Merge validated AI suggestions.

        Rules keep priority for facts the user typed.  The AI may only fill
        gaps; anything that fails validation is dropped and reported, never
        silently trusted.
        """
        accepted: list[str] = []
        rejected: list[str] = []
        requirements = extraction.requirements
        signals = extraction.signals

        for field_name in ("application_type", "traffic_pattern", "availability", "budget", "preferred_provider"):
            value = getattr(proposal, field_name)
            if value is None:
                continue
            current = getattr(requirements, field_name)
            already_asserted = requirements.basis_for(field_name) in {FieldBasis.USER, FieldBasis.TEMPLATE}
            if already_asserted and current not in {None, ApplicationType.UNKNOWN, TrafficPattern.UNKNOWN,
                                                    AvailabilityExpectation.UNKNOWN, BudgetPreference.UNKNOWN}:
                rejected.append(f"{field_name} (user value kept)")
                continue
            setattr(requirements, field_name, value)
            requirements.provenance[field_name] = FieldProvenance(
                basis=FieldBasis.AI, note="Proposed by the AI layer, accepted because the field was empty."
            )
            accepted.append(field_name)

        if proposal.data_storage and not requirements.is_asserted("data_storage"):
            requirements.data_storage = list(proposal.data_storage)
            requirements.provenance["data_storage"] = FieldProvenance(basis=FieldBasis.AI)
            for kind in proposal.data_storage:
                self._apply_storage_kind(signals, kind, FieldBasis.AI, accepted)
            accepted.append("data_storage")

        for name, value in proposal.signals.items():
            if not signals.is_established(name):
                try:
                    signals.set_field(name, value, FieldBasis.AI, "Proposed by the AI layer.")
                    accepted.append(name)
                except (KeyError, ValueError, TypeError) as exc:
                    rejected.append(f"{name} ({type(exc).__name__})")
            else:
                rejected.append(f"{name} (already established)")

        for statement in proposal.assumptions:
            extraction.assumptions.append(
                Assumption(
                    id=f"ASM-AI-{len(extraction.assumptions) + 1:02d}",
                    statement=statement,
                    basis=FieldBasis.AI,
                    impact="medium",
                    rule="ai-provided-rationale",
                )
            )
        for question in proposal.open_questions:
            extraction.open_questions.append(
                OpenQuestion(
                    id=f"Q-AI-{len(extraction.open_questions) + 1:02d}",
                    question=question,
                    field="ai_raised",
                    why_it_matters="Raised by the AI layer while reading the description; not answerable from the inputs.",
                )
            )
        extraction.matched_rules = sorted(set(extraction.matched_rules) | {"ai.merge"})
        if accepted:
            extraction.extraction_notes.append(
                "AI-assisted mode filled: " + ", ".join(sorted(set(accepted))) + "."
            )
        if rejected:
            extraction.extraction_notes.append(
                "AI suggestions not used: " + ", ".join(sorted(set(rejected))) + "."
            )
        return extraction, accepted, rejected


def outcome_hits_for(outcome: "rules.ExtractionOutcome", name: str) -> str:
    for hit in outcome.hits:
        if hit.field == name:
            return hit.rule_id
    return "rule"


def _render(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    if isinstance(value, list):
        return ", ".join(_render(item) for item in value)
    return str(value)


def available_providers() -> list[CloudProvider]:
    return [CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE]


_service: RequirementExtractionService | None = None


def get_extraction_service() -> RequirementExtractionService:
    global _service
    if _service is None:
        _service = RequirementExtractionService()
    return _service


def extract_requirements(requirements: ApplicationRequirements) -> ExtractionResult:
    return get_extraction_service().extract(requirements)


__all__ = [
    "RequirementExtractionService",
    "extract_requirements",
    "get_extraction_service",
    "SignalDerivation",
]


class SignalDerivation:
    """Named access to the capacity constants used by the extractor (tests/docs)."""

    sessions_per_user = rules.SESSIONS_PER_USER_BY_TYPE
    requests_per_session = rules.REQUESTS_PER_SESSION
    active_days_per_month = rules.ACTIVE_DAYS_PER_MONTH
    peak_ratio = {key.value: value for key, value in rules.PEAK_RATIO_BY_TRAFFIC.items()}
    concurrency_share = {key.value: value for key, value in rules.CONCURRENCY_SHARE_BY_TRAFFIC.items()}
    budget_preferences = BudgetPreference
