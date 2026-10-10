"""Workload classification stage.

Turns raw signals into a named workload class.  The class is used by the
architecture engine (which patterns to prefer) and by the cost model (which
utilisation shape to assume).  It is a documented lookup, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.schemas.common import ApplicationType, AvailabilityExpectation, TrafficPattern
from app.schemas.reports import WorkloadProfile
from app.schemas.requirements import ApplicationRequirements, RequirementSignals

REQUEST_SHAPE_BY_TRAFFIC: dict[TrafficPattern, str] = {
    TrafficPattern.SPIKY_EVENT: "high peak-to-average, event windows",
    TrafficPattern.BURSTY_SCHEDULED: "scheduled pulses with idle periods",
    TrafficPattern.DIURNAL: "daily cycle with quiet nights",
    TrafficPattern.UNPREDICTABLE: "irregular, hard to reserve against",
    TrafficPattern.STEADY: "flat utilisation around the clock",
    TrafficPattern.UNKNOWN: "not established",
}


@dataclass(frozen=True)
class ClassificationRule:
    rule_id: str
    classification: str
    headline: str
    matches: Callable[..., Any]  # (ctx) -> bool


def _signals_present(signals: RequirementSignals, *names: str) -> list[str]:
    return [name for name in names if signals.is_established(name)]


def classify(requirements: ApplicationRequirements, signals: RequirementSignals) -> WorkloadProfile:
    """Deterministic, precedence-ordered classification."""
    signals_list: list[str] = []
    for name in (
        "long_running_jobs",
        "gpu_required",
        "cpu_or_memory_intensive",
        "persistent_connections",
        "streaming_ingestion",
        "scheduled_batch",
        "event_driven",
        "stateful_sessions",
        "shared_locking_required",
        "transactional_writes",
        "high_fanout_reads",
        "object_storage_needed",
        "search_needed",
        "pdf_or_reporting",
        "notification_required",
    ):
        value = getattr(signals, name, None)
        if value is True:
            signals_list.append(f"{name.replace('_', ' ')}: yes")
        elif value is False:
            signals_list.append(f"{name.replace('_', ' ')}: no")

    app_type = requirements.application_type
    traffic = requirements.traffic_pattern or TrafficPattern.UNKNOWN
    request_shape = REQUEST_SHAPE_BY_TRAFFIC[traffic]

    classification, headline = _classify_shape(signals, app_type, signals_list)

    data_shape = "record-centric"
    if signals.relational_data and signals.object_storage_needed:
        data_shape = "record-centric with large file artefacts"
    elif signals.document_data or signals.key_value_data:
        data_shape = "schema-flexible documents and key/value state"
    elif signals.streaming_ingestion or signals.filesystem_semantics_required:
        data_shape = "continuous feed or filesystem semantics"
    elif not _signals_present(signals, "relational_data", "document_data", "object_storage_needed"):
        data_shape = "not established"

    execution_shape = "short interactive requests"
    if signals.long_running_jobs or (signals.longest_operation_minutes or 0) > 2:
        execution_shape = "mixed: interactive requests plus long-running jobs"
    if signals.persistent_connections:
        execution_shape = "resident connections with request handling alongside"
    if signals.gpu_required:
        execution_shape = "accelerated batch execution"

    return WorkloadProfile(
        classification=classification,
        headline=headline,
        signals=signals_list,
        request_shape=request_shape,
        data_shape=data_shape,
        execution_shape=execution_shape,
    )


def _classify_shape(
    signals: RequirementSignals, app_type: ApplicationType, evidence: list[str]
) -> tuple[str, str]:
    """First match wins; the order is the documented precedence."""
    if signals.gpu_required or (signals.longest_operation_minutes or 0) > 15:
        return (
            "heavy_batch_processing",
            "The workload is dominated by long, resource-heavy jobs rather than by user requests.",
        )
    if signals.streaming_ingestion and (signals.peak_concurrency or 0) >= 500:
        return (
            "continuous_stream_ingestion",
            "A continuously open ingest path carries most of the load; request handling is secondary.",
        )
    if signals.persistent_connections:
        return (
            "interactive_realtime",
            "Users hold open connections for live updates, which shapes the compute model more than traffic does.",
        )
    if signals.long_running_jobs:
        return (
            "mixed_request_and_batch",
            "Interactive request handling sits next to background jobs that run far longer than a request.",
        )
    if signals.scheduled_batch and not signals.event_driven:
        return (
            "scheduled_batch_only",
            "Work happens in scheduled windows, so most of the month the compute is idle.",
        )
    if signals.event_driven and (signals.upload_size_mb or signals.generated_files):
        return (
            "event_driven_file_processing",
            "Uploads and generated artefacts drive processing, which decouples naturally from the request path.",
        )
    if signals.transactional_writes or signals.shared_locking_required:
        return (
            "transactional_mixed",
            "Correctness depends on transactions or coordination between concurrent workers.",
        )
    if app_type in {ApplicationType.EXAMINATION_PLATFORM, ApplicationType.LEARNING_PLATFORM} and (
        signals.high_fanout_reads
    ):
        return (
            "windowed_high_read",
            "Short, intense usage windows with heavy read fan-out for results and dashboards.",
        )
    if traffic_is_spiky(signals, app_type):
        return (
            "spiky_request_response",
            "A conventional request/response application whose demand arrives in sharp, bounded peaks.",
        )
    if signals.high_fanout_reads:
        return (
            "read_heavy_crud",
            "Mostly reads with modest writes; caching determines the shape of the design.",
        )
    return (
        "steady_crud",
        "Even, predictable request/response load with ordinary CRUD behaviour.",
    )


def traffic_is_spiky(signals: RequirementSignals, app_type: ApplicationType) -> bool:
    return app_type in {
        ApplicationType.EXAMINATION_PLATFORM,
        ApplicationType.ECOMMERCE,
        ApplicationType.LOGISTICS_MARKETPLACE,
    }


def availability_note(expectation: AvailabilityExpectation | None) -> str:
    if expectation is None or expectation == AvailabilityExpectation.UNKNOWN:
        return "Availability expectation not stated; treated as an open question."
    return f"Availability expectation: {expectation.value.replace('_', ' ')}."
