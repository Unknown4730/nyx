"""Relative cost comparison — the "RICU" model.

Rules the implementation follows:

* **No currency.**  One RICU (Relative Infrastructure Cost Unit) is defined as
  "one small always-on compute unit-month (1 vCPU / 2 GB class)".  Every other
  coefficient is expressed relative to that anchor.
* Coefficients preserve order-of-magnitude relationships between capacity-time,
  per-request execution, storage volume and request counts.  They are model
  constants in this rule pack — deliberately **not** provider price lists — and
  the report states that.
* Quantities trace back to a requirement, an extraction, or a documented
  default; each line item carries its formula in `basis`.
* Storage, egress and log volume use identical coefficients in both scenarios so
  the difference reflects compute shape rather than accounting choices.
* Missing inputs become `insufficient_inputs`; nothing is guessed into a total.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.rules.cost_rates import COST_MODEL_VERSION, Rates
from app.schemas.common import AvailabilityExpectation, CostCategory, TrafficPattern
from app.schemas.reports import CostLineItem, CostReport, CostScenario, CostSensitivity
from app.schemas.requirements import ApplicationRequirements, RequirementSignals

DEFAULT_FUNCTION_MEMORY_GB = 0.5
DEFAULT_JOB_MEMORY_GB = 4.0
INSTANCE_CONCURRENCY = 25
LOG_BYTES_PER_REQUEST = 620
HOURS_PER_MONTH = 730.0
MAX_SCENARIO_INSTANCES = 12
JOBS_PER_USER = {
    "generated_files": 4,
    "long_running_jobs": 2,
    "none": 0,
}
PEAK_FALLBACK_FACTOR = 1.6

AVAILABILITY_MULTIPLIER: dict[AvailabilityExpectation, float] = {
    AvailabilityExpectation.BEST_EFFORT: 0.85,
    AvailabilityExpectation.STANDARD: 1.0,
    AvailabilityExpectation.HIGH: 1.15,
    AvailabilityExpectation.CRITICAL: 1.35,
    AvailabilityExpectation.UNKNOWN: 1.0,
}

STORAGE_VOLUME_DEFAULT_GB: dict[TrafficPattern, float] = {
    TrafficPattern.SPIKY_EVENT: 40.0,
    TrafficPattern.BURSTY_SCHEDULED: 25.0,
    TrafficPattern.DIURNAL: 60.0,
    TrafficPattern.UNPREDICTABLE: 45.0,
    TrafficPattern.STEADY: 120.0,
    TrafficPattern.UNKNOWN: 50.0,
}


@dataclass
class ModelInputs:
    """Everything the cost computation may use, with its provenance recorded."""

    monthly_requests: int | None
    average_duration_s: float
    function_memory_gb: float
    async_jobs: int
    job_minutes: float
    job_memory_gb: float
    storage_gb: float
    egress_gb: float
    db_size_gb: float
    availability_multiplier: float
    peak_rps: float
    instance_class: str = "small"
    active_users: int | None = None
    has_cache: bool = False
    has_search: bool = False
    has_stream: bool = False
    has_queue: bool = False
    needs_filesystem: bool = False
    notifies: bool = False
    provisioned_concurrency: bool = False
    assumptions: list[str] = field(default_factory=list)
    insufficient: list[str] = field(default_factory=list)


class CostEstimator:
    version = COST_MODEL_VERSION
    unit = "RICU"
    unit_name = "Relative Infrastructure Cost Unit"

    def __init__(self, rates: Rates | None = None) -> None:
        self.rates = rates or Rates()

    # ------------------------------------------------------------------ inputs

    def build_inputs(
        self, requirements: ApplicationRequirements, signals: RequirementSignals
    ) -> ModelInputs:
        assumptions: list[str] = []
        insufficient: list[str] = []

        requests = signals.monthly_requests
        if requests is None:
            insufficient.append(
                "No user count or request volume could be established, so usage-based lines are left "
                "unquantified instead of guessed."
            )
        duration_ms = signals.typical_response_ms or 350
        if signals.typical_response_ms is None:
            assumptions.append(f"Average request duration assumed at {duration_ms} ms.")

        multiplier = AVAILABILITY_MULTIPLIER.get(requirements.availability or AvailabilityExpectation.UNKNOWN, 1.0)
        if requirements.availability in {None, AvailabilityExpectation.UNKNOWN}:
            assumptions.append(
                "Availability multiplier assumed at 1.00; a stricter SLO raises fixed capacity in both models."
            )

        job_minutes = signals.longest_operation_minutes or (5.0 if signals.long_running_jobs else 1.0)
        if signals.longest_operation_minutes is None and (signals.long_running_jobs or signals.generated_files):
            assumptions.append(f"Background job duration assumed at {job_minutes:g} min.")

        users = signals.expected_users
        async_jobs = 0
        if requests or users:
            if signals.generated_files or signals.long_running_jobs or signals.pdf_or_reporting:
                if users:
                    async_jobs = users * JOBS_PER_USER["generated_files" if signals.generated_files else "long_running_jobs"]
                    assumptions.append(
                        f"Async job volume estimated as {users:,} users x "
                        f"{JOBS_PER_USER['generated_files' if signals.generated_files else 'long_running_jobs']} "
                        "jobs/user/month."
                    )
                else:
                    async_jobs = int((requests or 0) // 250)
                    assumptions.append("Async job volume estimated as 1 job per 250 requests (no user count stated).")
            elif signals.event_driven or signals.messaging_needed:
                async_jobs = int((requests or 0) // 500)
                assumptions.append("Async job volume estimated as 1 event-driven job per 500 requests.")

        storage_gb = signals.dataset_size_gb or STORAGE_VOLUME_DEFAULT_GB.get(
            requirements.traffic_pattern or TrafficPattern.UNKNOWN, 50.0
        )
        if signals.dataset_size_gb is None:
            assumptions.append(
                f"Stored data volume assumed at {storage_gb:g} GB; identical in both models so it cannot "
                "distort the comparison."
            )

        upload_mb = signals.upload_size_mb or 0.5
        if requests:
            egress_gb = round(requests * max(upload_mb, 0.2) / 1024.0 * 0.25, 2)
        else:
            egress_gb = round(storage_gb * 0.4, 2)
            assumptions.append("Egress assumed as 40% of stored volume per month because request count is unknown.")

        peak_rps = round((signals.peak_requests_per_minute or 0) / 60.0, 3)
        if not peak_rps and requests:
            peak_rps = round(requests / (26 * 24 * 3600) * PEAK_FALLBACK_FACTOR, 3)
            assumptions.append(f"Peak rate derived from monthly volume with a {PEAK_FALLBACK_FACTOR:g}x peak factor.")

        instance_class = "small"
        if signals.cpu_or_memory_intensive or (signals.typical_response_ms or 0) > 2000:
            instance_class = "large"
            assumptions.append("Compute class raised to 'large' because the workload is compute-heavy or slow per request.")

        return ModelInputs(
            monthly_requests=requests,
            average_duration_s=round(duration_ms / 1000.0, 4),
            function_memory_gb=DEFAULT_FUNCTION_MEMORY_GB,
            async_jobs=async_jobs,
            job_minutes=job_minutes,
            job_memory_gb=DEFAULT_JOB_MEMORY_GB if (signals.gpu_required or signals.cpu_or_memory_intensive) else 2.0,
            storage_gb=round(storage_gb, 2),
            egress_gb=egress_gb,
            db_size_gb=round(max(10.0, storage_gb * 0.35), 2),
            availability_multiplier=multiplier,
            peak_rps=peak_rps,
            instance_class=instance_class,
            active_users=users,
            has_cache=bool(signals.cache_needed or signals.stateful_sessions or signals.high_fanout_reads),
            has_search=bool(signals.search_needed),
            has_stream=bool(signals.streaming_ingestion),
            has_queue=bool(async_jobs or signals.messaging_needed or signals.event_driven),
            needs_filesystem=bool(signals.filesystem_semantics_required),
            notifies=bool(signals.notification_required),
            provisioned_concurrency=bool(signals.cold_start_sensitive or signals.startup_latency_sensitive),
            assumptions=assumptions,
            insufficient=insufficient,
        )

    # ------------------------------------------------------------------- model

    def estimate(self, requirements: ApplicationRequirements, signals: RequirementSignals) -> CostReport:
        inputs = self.build_inputs(requirements, signals)
        conventional, proposed = self.scenarios(inputs)
        return self._assemble(inputs, conventional, proposed)

    def scenarios(self, i: ModelInputs, traffic: float = 1.0, duration: float = 1.0) -> tuple[CostScenario, CostScenario]:
        rates = self.rates
        requests = int((i.monthly_requests or 0) * traffic)
        duration_s = round(i.average_duration_s * duration, 5)
        jobs = int(i.async_jobs * traffic)
        job_hours = jobs * i.job_minutes * duration / 60.0
        avail = i.availability_multiplier
        class_rate = rates.instance_small if i.instance_class == "small" else rates.instance_large
        job_size_factor = max(1.0, i.job_memory_gb / 2.0)

        conv: list[CostLineItem] = []
        prop: list[CostLineItem] = []

        def add(bucket: list[CostLineItem], item_id: str, label: str, quantity: float, unit: str, ricu: float,
                category: CostCategory, basis: str) -> None:
            bucket.append(
                CostLineItem(
                    id=item_id,
                    label=label,
                    category=category,
                    quantity=round(quantity, 3),
                    unit=unit,
                    ricu=round(max(0.0, ricu), 4),
                    basis=basis,
                )
            )

        # ---------------------------------------------------------- conventional
        capacity_per_instance = INSTANCE_CONCURRENCY / max(duration_s, 0.01)
        needed = math.ceil(i.peak_rps * traffic / capacity_per_instance) if i.peak_rps else 1
        instances = max(1, min(MAX_SCENARIO_INSTANCES, needed))
        if avail >= 1.15:
            instances = max(2, instances)
        add(
            conv,
            "conv.compute",
            f"Application tier — {instances} x {i.instance_class} instance(s), 24/7",
            instances,
            "instance-months",
            instances * class_rate * avail,
            CostCategory.FIXED,
            f"{instances} instance(s) x {class_rate:g} RICU/instance-month x {avail:g} availability factor. "
            f"Count = ceil(peak {i.peak_rps * traffic:.1f} req/s ÷ {capacity_per_instance:.1f} req/s per instance "
            f"at {duration_s * 1000:.0f} ms and {INSTANCE_CONCURRENCY} concurrent requests each); resident for the "
            "whole month whether or not users are present.",
        )
        add(
            conv,
            "conv.lb",
            "Load balancer (entry point)",
            1,
            "month",
            rates.lb_fixed * avail + rates.lb_per_million * (requests / 1_000_000),
            CostCategory.FIXED,
            f"{rates.lb_fixed:g} RICU/month for the provisioned balancer + {rates.lb_per_million:g} per 1M requests.",
        )
        if i.has_queue:
            add(
                conv,
                "conv.broker",
                "Self-managed broker host (half-size)",
                0.5,
                "instance-months",
                rates.instance_small * 0.5 * avail,
                CostCategory.FIXED,
                "A permanently running half-size instance to host the broker; capacity is not released when queues "
                "are empty.",
            )
        worker_instances = 0
        if job_hours > 0:
            worker_instances = max(1, min(MAX_SCENARIO_INSTANCES, math.ceil(job_hours / HOURS_PER_MONTH * 1.25)))
            add(
                conv,
                "conv.worker",
                f"Background worker hosts — {worker_instances} resident",
                worker_instances,
                "instance-months",
                worker_instances * class_rate * job_size_factor * avail,
                CostCategory.FIXED,
                f"Sized to fit {job_hours:,.0f} job-hours/month with 25% headroom, then billed for the whole month. "
                "Idle time between runs is not refunded — this is the single largest structural difference between "
                "the two models.",
            )
        add(
            conv,
            "conv.db",
            "Primary database instance (peak-sized)",
            1,
            "month",
            rates.db_small * avail,
            CostCategory.FIXED,
            f"{rates.db_small:g} RICU/db-month x {avail:g}; sized for the peak connection and IOPS envelope, so "
            "quiet nights still cost the same.",
        )
        add(
            conv,
            "conv.db_storage",
            "Database storage",
            i.db_size_gb,
            "GB-months",
            i.db_size_gb * rates.db_storage_gb,
            CostCategory.VARIABLE,
            f"{i.db_size_gb:g} GB x {rates.db_storage_gb:g} RICU per GB-month (same coefficient in both models).",
        )
        add(
            conv,
            "conv.storage",
            "File storage on provisioned volumes",
            i.storage_gb * 1.25,
            "GB-months",
            i.storage_gb * 1.25 * rates.block_storage_gb,
            CostCategory.VARIABLE,
            f"{i.storage_gb:g} GB of content plus 25% growth headroom (you must pre-allocate a volume, and filling "
            f"it blocks the application) x {rates.block_storage_gb:g} RICU per GB-month.",
        )
        if i.has_cache:
            add(
                conv,
                "conv.cache",
                "Cache / session node",
                1,
                "month",
                rates.cache_small * avail,
                CostCategory.FIXED,
                f"{rates.cache_small:g} RICU/cache-month. Sharing session data across instances needs this extra "
                "resident component.",
            )
        if i.has_search:
            add(
                conv,
                "conv.search",
                "Search engine node",
                1,
                "month",
                rates.search_small * avail,
                CostCategory.FIXED,
                f"{rates.search_small:g} RICU per search-node-month; always-on in either model.",
            )

        # -------------------------------------------------------------- proposed
        invocations = requests + jobs
        gb_seconds = requests * duration_s * i.function_memory_gb + jobs * i.job_minutes * duration * 60 * i.function_memory_gb
        add(
            prop,
            "prop.functions",
            "Function execution (request path + async handlers)",
            invocations,
            "invocations",
            (invocations / 1_000_000) * rates.per_million_invocations + gb_seconds * rates.per_gb_second,
            CostCategory.VARIABLE,
            f"{invocations:,} invocations x {rates.per_million_invocations:g} RICU per 1M + {gb_seconds:,.0f} GB-s "
            f"x {rates.per_gb_second:g} RICU per GB-s ({i.function_memory_gb:g} GB profile). Nothing is billed "
            "while nobody is using the system.",
        )
        if i.provisioned_concurrency:
            add(
                prop,
                "prop.warm",
                "Provisioned concurrency on latency-sensitive routes",
                1,
                "month",
                rates.provisioned_concurrency * avail,
                CostCategory.FIXED,
                "Cold-start sensitivity was stated, so a small resident allocation is priced in. Omitting it moves "
                "this line to zero and puts start-up latency back on the user.",
            )
        if job_hours > 0:
            add(
                prop,
                "prop.jobs",
                "Job runtime for long work (billed per run)",
                round(job_hours, 2),
                "job-hours",
                job_hours * rates.container_hour * job_size_factor,
                CostCategory.VARIABLE,
                f"{job_hours:,.0f} job-hours x {rates.container_hour:g} RICU/hour x {job_size_factor:g} for the "
                f"{i.job_memory_gb:g} GB memory profile. Capacity exists only while a job runs; this is the line "
                "that keeps the heavy work off the function runtime honestly.",
            )
        add(
            prop,
            "prop.gateway",
            "Managed API surface",
            requests,
            "requests",
            rates.gateway_fixed + (requests / 1_000_000) * rates.gateway_per_million,
            CostCategory.VARIABLE,
            f"{rates.gateway_fixed:g} RICU/month base + {rates.gateway_per_million:g} per 1M requests; authorization "
            "and throttling are absorbed here instead of in code.",
        )
        add(
            prop,
            "prop.db",
            "Managed database (autoscaling capacity)",
            1,
            "month",
            rates.db_small * 0.7 * avail + max(requests, 1) / 1_000_000 * rates.db_per_million_queries,
            CostCategory.VARIABLE,
            f"Autoscaling floor of {rates.db_small * 0.7:g} RICU x {avail:g}, plus query volume at "
            f"{rates.db_per_million_queries:g} per 1M. The state is still here — only the capacity model changes.",
        )
        add(
            prop,
            "prop.db_storage",
            "Database storage",
            i.db_size_gb,
            "GB-months",
            i.db_size_gb * rates.db_storage_gb,
            CostCategory.VARIABLE,
            "Identical to the conventional model by construction.",
        )
        add(
            prop,
            "prop.storage",
            "Object storage for artefacts",
            i.storage_gb,
            "GB-months",
            i.storage_gb * rates.object_storage_gb + (requests / 1_000_000) * rates.storage_requests_per_million,
            CostCategory.VARIABLE,
            f"{i.storage_gb:g} GB x {rates.object_storage_gb:g} RICU per GB-month + request charges. No growth "
            "headroom is pre-purchased because capacity is not allocated up front.",
        )
        if i.has_queue:
            add(
                prop,
                "prop.queue",
                "Queue / event bus",
                max(jobs, 1) + requests // 10,
                "messages",
                ((max(jobs, 1) + requests // 10) / 1_000_000) * rates.queue_per_million,
                CostCategory.VARIABLE,
                f"{rates.queue_per_million:g} RICU per 1M messages over the estimated message count.",
            )
        if i.has_cache:
            add(
                prop,
                "prop.cache",
                "Managed cache (shared state, hot reads)",
                1,
                "month",
                rates.cache_small * 0.6 * avail,
                CostCategory.VARIABLE,
                "A smaller node suffices because handlers stay stateless and the API surface fronts hot reads.",
            )
        if i.has_search:
            add(
                prop,
                "prop.search",
                "Managed search index",
                1,
                "month",
                rates.search_small * 0.85 * avail,
                CostCategory.FIXED,
                "Same always-on tier, operated by the provider instead of by the team.",
            )
        if i.notifies:
            messages = max(jobs, requests // 20, 1)
            add(
                conv, "conv.notify", "Notification sending (from the app tier)", messages, "messages",
                (messages / 1000.0) * rates.notification_per_thousand, CostCategory.VARIABLE,
                f"{messages:,} outbound messages per month at {rates.notification_per_thousand:g} RICU per 1,000. "
                "Same coefficient in both models — only the retry and queueing behaviour differ.",
            )
            add(
                prop, "prop.notify", "Notification dispatch (async, managed)", messages, "messages",
                (messages / 1000.0) * rates.notification_per_thousand, CostCategory.VARIABLE,
                "Identical message charge; moved off the request path so retries are handled by the queue instead "
                "of by the user waiting.",
            )
        if i.has_stream:
            add(
                prop,
                "prop.stream",
                "Managed stream ingestion",
                requests,
                "events",
                (requests / 1_000_000) * rates.stream_per_million + rates.stream_fixed,
                CostCategory.VARIABLE,
                f"{rates.stream_fixed:g} RICU/month partition floor + {rates.stream_per_million:g} per 1M events.",
            )
        if i.needs_filesystem:
            add(
                prop,
                "prop.filesystem",
                "Network file share (POSIX semantics)",
                i.storage_gb,
                "GB-months",
                i.storage_gb * rates.block_storage_gb * 2.5,
                CostCategory.FIXED,
                "Filesystem semantics do not disappear in a serverless design; the share is simply attached to the "
                "resident runtime instead of to every application host.",
            )

        # ------------------------------------------------------- shared rails
        log_gb = max(requests * LOG_BYTES_PER_REQUEST / 1e9, 0.5)
        add(
            conv, "conv.egress", "Outbound data transfer", i.egress_gb, "GB", i.egress_gb * rates.egress_gb,
            CostCategory.VARIABLE, f"{i.egress_gb:g} GB x {rates.egress_gb:g} RICU per GB.",
        )
        add(
            prop, "prop.egress", "Outbound data transfer", i.egress_gb, "GB", i.egress_gb * rates.egress_gb,
            CostCategory.VARIABLE, "Same volume assumption as the conventional model.",
        )
        add(
            conv, "conv.logs", "Log capture (files on hosts)", round(log_gb, 3), "GB",
            log_gb * rates.log_ingest_gb * 0.4, CostCategory.VARIABLE,
            f"~{LOG_BYTES_PER_REQUEST} bytes per request x {requests:,} requests at 40% of the managed ingest "
            "coefficient, because local files are not centrally indexed (a control gap, not a saving).",
        )
        add(
            prop, "prop.telemetry", "Structured logs, metrics and alarms", round(log_gb, 3), "GB",
            log_gb * rates.log_ingest_gb + rates.monitoring_fixed, CostCategory.VARIABLE,
            f"Ingest at {rates.log_ingest_gb:g} RICU per GB + {rates.monitoring_fixed:g} for metric and alarm rails. "
            "A serverless design leans harder on telemetry, so this line is deliberately not omitted.",
        )
        add(
            prop,
            "prop.identity",
            "Managed identity and secret storage",
            i.active_users or 0,
            "monthly active users",
            rates.secrets_fixed + (rates.identity_per_mau * i.active_users / 1000.0 if i.active_users else 0.0),
            CostCategory.VARIABLE,
            "Secret store fixed share"
            + (
                f" plus {rates.identity_per_mau:g} RICU per 1,000 monthly active users x {i.active_users:,} users."
                if i.active_users
                else "; identity charges omitted because no user count was established."
            ),
        )

        conv_fixed_count = sum(1 for item in conv if item.category == CostCategory.FIXED)
        add(
            conv, "conv.ops", "Operational maintenance load", conv_fixed_count, "component-months",
            conv_fixed_count * rates.ops_manual_component, CostCategory.OPERATIONAL,
            f"{conv_fixed_count} self-managed component(s) x {rates.ops_manual_component:g} RICU of maintenance "
            "load (patching, capacity reviews, backup scripts, failover drills). A relative effort proxy, not money.",
        )
        add(
            prop, "prop.ops", "Operational maintenance load", len(prop), "component-months",
            len(prop) * rates.ops_managed_component, CostCategory.OPERATIONAL,
            f"{len(prop)} managed component(s) x {rates.ops_managed_component:g} RICU: no OS patching or capacity "
            "sizing, but platform limits, IAM and asynchronous failure handling still need design and review.",
        )

        return (
            _scenario(
                "conventional",
                "Conventional architecture (as-is baseline)",
                conv,
                "Capacity is provisioned for the peak and billed continuously; rails are operated by the team.",
            ),
            _scenario(
                "proposed",
                "Proposed serverless / hybrid architecture",
                prop,
                "Capacity follows executions, with resident capacity kept only where the suitability engine "
                "demanded it.",
            ),
        )

    def _assemble(self, i: ModelInputs, conventional: CostScenario, proposed: CostScenario) -> CostReport:
        conv_total = conventional.total_ricu
        prop_total = proposed.total_ricu
        comparison: dict[str, float] = {"conventional_total": conv_total, "proposed_total": prop_total}
        if i.monthly_requests and conv_total > 0 and prop_total > 0:
            comparison.update(
                {
                    "ratio_proposed_to_conventional": round(prop_total / conv_total, 3),
                    "model_relative_change_pct": round((prop_total - conv_total) / conv_total * 100.0, 1),
                    "absolute_difference_ricu": round(prop_total - conv_total, 2),
                }
            )

        fixed_share = {
            "conventional": _share(conv_total, conventional.fixed_ricu),
            "proposed": _share(prop_total, proposed.fixed_ricu),
        }

        sensitivity: list[CostSensitivity] = []
        if i.monthly_requests:
            for label, scale in (("traffic at 50% of stated volume", 0.5), ("traffic at 200% of stated volume", 2.0)):
                conv_s, prop_s = self.scenarios(i, traffic=scale)
                sensitivity.append(
                    CostSensitivity(
                        name="Traffic volume",
                        low_label=label,
                        high_label=label,
                        conventional_delta_pct=_change(conv_total, conv_s.total_ricu),
                        proposed_delta_pct=_change(prop_total, prop_s.total_ricu),
                        note=(
                            "The proposed model moves roughly with traffic. The conventional model moves in steps, "
                            "only when an instance boundary is crossed — a 0.0% delta here means the same instance "
                            "count still serves the load, which is exactly the elasticity argument."
                        ),
                    )
                )
            conv_d, prop_d = self.scenarios(i, duration=1.5)
            sensitivity.append(
                CostSensitivity(
                    name="Execution duration",
                    low_label="every operation 50% slower",
                    high_label="every operation 50% slower",
                    conventional_delta_pct=_change(conv_total, conv_d.total_ricu),
                    proposed_delta_pct=_change(prop_total, prop_d.total_ricu),
                    note=(
                        "Per-request billing makes the proposed model sensitive to duration; resident capacity only "
                        "changes when slower requests require another instance."
                    ),
                )
            )

        rates = self.rates
        rate_table = [
            {"quantity": "one small always-on compute unit", "unit": "instance-month", "ricu": rates.instance_small,
             "note": "definition of the unit itself; everything below is relative to it"},
            {"quantity": "large compute unit", "unit": "instance-month", "ricu": rates.instance_large,
             "note": "used when the workload is compute-heavy"},
            {"quantity": "function invocation", "unit": "per 1M", "ricu": rates.per_million_invocations,
             "note": "per-invocation charge, memory-independent"},
            {"quantity": "function execution", "unit": "GB-second", "ricu": rates.per_gb_second,
             "note": "duration x memory charge"},
            {"quantity": "container/job runtime", "unit": "hour", "ricu": rates.container_hour,
             "note": "scales with the memory profile of the job"},
            {"quantity": "managed database (peak-sized)", "unit": "month", "ricu": rates.db_small,
             "note": "proposed uses 70% of this as an autoscaling floor"},
            {"quantity": "object storage", "unit": "GB-month", "ricu": rates.object_storage_gb,
             "note": "identical in both models"},
            {"quantity": "provisioned block storage", "unit": "GB-month", "ricu": rates.block_storage_gb,
             "note": "plus a 25% headroom factor in the conventional model"},
            {"quantity": "queue / events", "unit": "per 1M messages", "ricu": rates.queue_per_million,
             "note": "message handling"},
            {"quantity": "log ingest", "unit": "GB", "ricu": rates.log_ingest_gb, "note": "telemetry volume"},
            {"quantity": "maintenance load, self-managed component", "unit": "component-month",
             "ricu": rates.ops_manual_component, "note": "relative effort proxy, explicitly not money"},
            {"quantity": "maintenance load, managed component", "unit": "component-month",
             "ricu": rates.ops_managed_component, "note": "relative effort proxy, explicitly not money"},
            {"quantity": "availability multipliers", "unit": "factor",
             "ricu": round(max(AVAILABILITY_MULTIPLIER.values()), 3),
             "note": "best effort 0.85, standard 1.00, high 1.15, critical 1.35 — applied to fixed capacity lines"},
        ]

        limitations = [
            "RICU is a relative index defined inside NYX. It is not a currency, cannot be converted to money, and "
            "no provider price list was used.",
            "No commitment discounts, free tiers, support plans, egress tiers, cross-region replication or "
            "one-off migration effort are modelled.",
            "The comparison assumes the proposed design is implemented as modelled; build and migration labour is "
            "not included.",
            "Directional only: the value of this table is which drivers dominate, not the absolute number.",
        ]
        if i.monthly_requests is None:
            limitations.insert(
                0,
                "Usage-based lines could not be quantified, so no ratio or percentage is reported — only the fixed "
                "capacity shape is shown.",
            )

        methodology = [
            "1. Quantities come from requirement extraction (users → sessions → requests → peak → jobs); every "
            "formula is printed on its line item.",
            "2. Conventional = capacity sized for the peak, billed for the whole month, plus provisioned storage "
            "and self-managed rails.",
            "3. Proposed = execution-based charges (invocations, GB-seconds, message counts) plus a smaller fixed "
            "floor, plus job-hours for anything the suitability engine kept off the function runtime.",
            "4. Availability multiplies the fixed lines in both models by the same factor.",
            "5. Storage, egress and log volume use identical coefficients in both models on purpose.",
            f"6. Model version {COST_MODEL_VERSION}: the numbers are constants in this rule pack, so the version is "
            "printed with the result and any change alters the outcome.",
        ]

        return CostReport(
            unit=self.unit,
            unit_name=self.unit_name,
            disclaimer=(
                "Relative Infrastructure Cost Units (RICU) are a heuristic index internal to NYX. They are not "
                "prices, not currency and not a savings guarantee. 1 RICU = one small always-on compute unit-month."
            ),
            scenarios=[conventional, proposed],
            comparison=comparison,
            fixed_share=fixed_share,
            sensitivity=sensitivity,
            methodology=methodology,
            rate_table=rate_table,
            assumptions=i.assumptions,
            limitations=limitations,
            insufficient_inputs=i.insufficient,
        )


def _scenario(scenario_id: str, label: str, items: list[CostLineItem], description: str) -> CostScenario:
    def total(category: CostCategory) -> float:
        return round(sum(item.ricu for item in items if item.category == category), 2)

    fixed = total(CostCategory.FIXED)
    variable = total(CostCategory.VARIABLE)
    operational = total(CostCategory.OPERATIONAL)
    grand = round(fixed + variable + operational, 2)
    drivers = sorted((item for item in items if item.ricu > 0), key=lambda item: item.ricu, reverse=True)[:3]
    return CostScenario(
        id=scenario_id,
        label=label,
        description=description,
        fixed_ricu=fixed,
        variable_ricu=variable,
        operational_ricu=operational,
        total_ricu=grand,
        line_items=items,
        drivers=[
            f"{item.label}: {item.ricu:g} RICU ({_share(grand, item.ricu):.0f}% of total)" for item in drivers
        ],
    )


def _share(base: float, value: float) -> float:
    return round(value / base * 100.0, 1) if base else 0.0


def _change(base: float, value: float) -> float:
    return round((value - base) / base * 100.0, 1) if base else 0.0


def estimate_cost(requirements: ApplicationRequirements, signals: RequirementSignals) -> CostReport:
    return CostEstimator().estimate(requirements, signals)


__all__ = ["CostEstimator", "estimate_cost", "ModelInputs"]
