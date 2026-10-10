"""Component identification stage.

Each rule below turns requirement evidence into one *logical* component (a
responsibility, not a product).  A rule returns a plan only when it has
evidence — either asserted by the user/template or inferred from the text — and
records that evidence on the component so the UI can explain itself.

Realization as a server, a function or a managed service happens later, in the
architecture engine, once suitability has been scored.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.architecture import ComponentInventoryItem, ComponentPlan, ComponentTraits, SecurityEvidence
from app.schemas.common import (
    ApplicationType,
    BackupPolicy,
    ComponentRuntime,
    ComponentTier,
    DataClassification,
    DurationProfile,
    IamScope,
    LogicalComponentType,
    TransportSecurity,
)
from app.schemas.requirements import ApplicationRequirements, RequirementSignals

PUBLIC_TYPES = {
    ApplicationType.ECOMMERCE,
    ApplicationType.EXAMINATION_PLATFORM,
    ApplicationType.LEARNING_PLATFORM,
    ApplicationType.LOGISTICS_MARKETPLACE,
    ApplicationType.CONTENT_SITE,
    ApplicationType.STREAMING_MEDIA,
    ApplicationType.REALTIME_COLLABORATION,
    ApplicationType.MOBILE_BACKEND,
    ApplicationType.API_SERVICE,
    ApplicationType.WEB_APP,
}

RECORD_KEEPING_TYPES = {
    ApplicationType.ECOMMERCE,
    ApplicationType.EXAMINATION_PLATFORM,
    ApplicationType.LEARNING_PLATFORM,
    ApplicationType.LOGISTICS_MARKETPLACE,
    ApplicationType.WEB_APP,
    ApplicationType.CONTENT_SITE,
    ApplicationType.REALTIME_COLLABORATION,
    ApplicationType.INTERNAL_TOOL,
    ApplicationType.MOBILE_BACKEND,
    ApplicationType.API_SERVICE,
}

@dataclass
class IdentificationContext:
    requirements: ApplicationRequirements
    signals: RequirementSignals

    @property
    def is_public(self) -> bool:
        if self.signals.public_internet_facing is not None:
            return bool(self.signals.public_internet_facing)
        return self.requirements.application_type in PUBLIC_TYPES

    @property
    def sensitive(self) -> bool:
        return bool(self.signals.sensitive_data) or self.requirements.application_type in {
            ApplicationType.EXAMINATION_PLATFORM,
            ApplicationType.LEARNING_PLATFORM,
        }

    @property
    def classification(self) -> DataClassification:
        if self.signals.sensitive_data:
            return DataClassification.CONFIDENTIAL
        if self.signals.compliance_regime:
            return DataClassification.RESTRICTED
        if self.is_public:
            return DataClassification.INTERNAL
        return DataClassification.UNSPECIFIED

    @property
    def long_running(self) -> bool:
        return bool(self.signals.long_running_jobs) or (self.signals.longest_operation_minutes or 0) > 2

    @property
    def request_duration_profile(self) -> DurationProfile:
        """How long one *request* takes — the shape handlers inherit.

        Deliberately separate from `duration_profile`: a five-minute certificate
        batch must not make the request path look like a long-running component.
        """
        ms = self.signals.typical_response_ms
        if ms is None:
            return DurationProfile.UNSPECIFIED
        if ms <= 1000:
            return DurationProfile.SUB_SECOND
        if ms <= 3000:
            return DurationProfile.FEW_SECONDS
        return DurationProfile.MINUTES

    @property
    def duration_profile(self) -> DurationProfile:
        """How long the longest *operation* takes; used for background work."""
        ms = self.signals.typical_response_ms
        minutes = self.signals.longest_operation_minutes
        if minutes is not None:
            if minutes > 15:
                return DurationProfile.INDEFINITE
            if minutes > 2:
                return DurationProfile.MINUTES
            return DurationProfile.FEW_SECONDS
        if ms is None:
            return DurationProfile.UNSPECIFIED
        if ms <= 1000:
            return DurationProfile.SUB_SECOND
        if ms <= 3000:
            return DurationProfile.FEW_SECONDS
        return DurationProfile.MINUTES

    def spike_ratio(self) -> float:
        monthly = self.signals.monthly_requests
        peak_rpm = self.signals.peak_requests_per_minute
        if monthly and peak_rpm:
            average = monthly / (26 * 24 * 60)
            if average > 0:
                return round(peak_rpm / average, 2)
        return 1.35


def _traits(**kwargs: object) -> ComponentTraits:
    """Small readability helper for the component plan table above."""
    return ComponentTraits(**kwargs)  # type: ignore[arg-type]


def identify(requirements: ApplicationRequirements, signals: RequirementSignals) -> tuple[
    list[ComponentPlan], list[ComponentInventoryItem]
]:
    ctx = IdentificationContext(requirements=requirements, signals=signals)
    plans: list[ComponentPlan] = []
    inventory: list[ComponentInventoryItem] = []

    def add(
        plan: ComponentPlan,
        source: str,
        evidence: list[str],
        *,
        required: bool = True,
    ) -> None:
        plan.evidence = list(dict.fromkeys(plan.evidence + evidence))
        plans.append(plan)
        inventory.append(
            ComponentInventoryItem(
                id=plan.id or plan.type.value,
                label=plan.label or plan.type.value.replace("_", " ").title(),
                type=plan.type,
                tier=_tier_for(plan.type),
                description=plan.description or "",
                source=source,
                required=required,
                evidence=evidence,
            )
        )

    # ------------------------------------------------------------------ clients
    mobile = "mobile app" in requirements.description.lower() or "android" in requirements.description.lower()
    client_evidence = ["Client interface is part of the described system."]
    if mobile:
        client_evidence.append("Description mentions a mobile application.")
    client_type = LogicalComponentType.CLIENT_MOBILE if mobile else LogicalComponentType.CLIENT_WEB
    add(
        ComponentPlan(
            type=client_type,
            id="client",
            label="Client application" if mobile else "Web client",
            description=(
                "Browser or mobile front end that users interact with. Served as static assets and "
                "responsible for rendering, form validation and API calls."
            ),
            traits=_traits(runtime=ComponentRuntime.STATIC, stateful=False, always_on=False),
            security=SecurityEvidence(publicly_reachable=True, requires_authentication=False,
                                       transport_security=TransportSecurity.TLS_ENFORCED,
                                       data_classification=DataClassification.PUBLIC),
            properties={"Hosting": "static assets, no server runtime", "Interface": "HTML/JS or native shell"},
        ),
        "inferred",
        client_evidence,
    )

    # ------------------------------------------------------------------- edge
    if ctx.is_public:
        add(
            ComponentPlan(
                type=LogicalComponentType.CDN,
                id="edge",
                label="Edge delivery & TLS termination",
                description=(
                    "Content delivery and global entry point: caches client assets, terminates TLS and "
                    "absorbs read traffic before it reaches compute."
                ),
                traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=False, always_on=False),
                security=SecurityEvidence(publicly_reachable=True, transport_security=TransportSecurity.TLS_ENFORCED,
                                          data_classification=DataClassification.PUBLIC),
                properties={"Cacheable": "static and semi-static assets", "Origin": "API surface"},
            ),
            "inferred",
            ["Application is reachable by end users over the public internet."],
            required=False,
        )

    # ------------------------------------------------------------- api surface
    add(
        ComponentPlan(
            type=LogicalComponentType.API_GATEWAY,
            id="api",
            label="API surface",
            description=(
                "Synchronous HTTP entry point for the application's use cases: routing, request validation, "
                "rate limiting and authorization enforcement."
            ),
            traits=_traits(
                runtime=ComponentRuntime.REQUEST_RESPONSE,
                stateful=False,
                duration=ctx.request_duration_profile,
                estimated_duration_ms=signals.typical_response_ms,
            ),
            security=SecurityEvidence(
                publicly_reachable=True,
                requires_authentication=bool(ctx.signals.sensitive_data) or ctx.is_public,
                authentication_scheme="bearer token" if not mobile else "bearer token / OAuth",
                transport_security=TransportSecurity.UNSPECIFIED,
                data_classification=ctx.classification,
                input_validation="unspecified",
            ),
            properties={
                "Traffic shape": requirements.traffic_pattern.value.replace("_", " ")
                if requirements.traffic_pattern
                else "not stated",
                "Spike ratio": f"{ctx.spike_ratio():.2f}x average",
            },
        ),
        "inferred",
        ["Client-visible operations were described, which implies an API surface."],
    )

    # ---------------------------------------------------------------- identity
    auth_terms = ("login", "authenticate", "sign in", "sso", "jwt", "role", "permission", "registration")
    if any(term in requirements.description.lower() for term in auth_terms) or ctx.is_public:
        evidence = ["Authentication or user identity is implied by the described flows."]
        if ctx.is_public:
            evidence.append("Public users must be identified for per-user data isolation.")
        add(
            ComponentPlan(
                type=LogicalComponentType.AUTH_IDENTITY,
                id="identity",
                label="Identity & access",
                description=(
                    "User store, credential handling, token issuance and role assignment, kept outside the "
                    "application code so it can be audited independently."
                ),
                traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False),
                security=SecurityEvidence(
                    publicly_reachable=False,
                    requires_authentication=True,
                    authentication_scheme="managed identity provider",
                    transport_security=TransportSecurity.TLS_ENFORCED,
                    data_classification=DataClassification.RESTRICTED,
                    encryption_at_rest=True,
                    iam_scope=IamScope.SCOPED,
                ),
                properties={"Responsibility": "credentials, tokens, roles", "Never holds": "application business rules"},
            ),
            "inferred",
            evidence,
        )

    # ------------------------------------------------------ interactive logic
    add(
        ComponentPlan(
            type=LogicalComponentType.APP_SERVER,
            id="app_logic",
            label="Interactive application logic",
            description=(
                "The request-handling business logic: use-case orchestration, validation of domain rules, "
                "reads and writes against the primary store, and response composition."
            ),
            traits=_traits(
                runtime=ComponentRuntime.REQUEST_RESPONSE,
                stateful=bool(ctx.signals.stateful_sessions),
                always_on=True,
                duration=ctx.request_duration_profile,
                persistent_connections=False,
                estimated_duration_ms=ctx.signals.typical_response_ms,
                data_intensity="high" if ctx.signals.high_fanout_reads else "medium",
            ),
            security=SecurityEvidence(
                publicly_reachable=False,
                requires_authentication=True,
                transport_security=TransportSecurity.UNSPECIFIED,
                data_classification=ctx.classification,
                iam_scope=IamScope.UNSPECIFIED,
                secrets_handling="unspecified",
                input_validation="unspecified",
                audit_logging=ctx.signals.requires_audit_trail,
            ),
            properties={
                "Peak concurrency": f"{ctx.signals.peak_concurrency:,}" if ctx.signals.peak_concurrency else "not stated",
                "Session model": "stateful" if ctx.signals.stateful_sessions else "stateless or unstated",
            },
            warnings=[] if not ctx.signals.stateful_sessions else ["Session state must be externalised before this can scale out."],
        ),
        "inferred",
        ["Use-case handling is required for the described interactions."],
    )

    # ------------------------------------------------ realtime connection path
    if ctx.signals.persistent_connections:
        add(
            ComponentPlan(
                type=LogicalComponentType.CONTAINER_SERVICE,
                id="realtime",
                label="Real-time connection handler",
                description=(
                    "Holds long-lived client connections (WebSocket/SSE) and pushes updates. Kept separate "
                    "because the connection cannot live inside a single invocation."
                ),
                traits=_traits(
                    runtime=ComponentRuntime.ALWAYS_ON,
                    stateful=True,
                    always_on=True,
                    persistent_connections=True,
                    duration=DurationProfile.INDEFINITE,
                ),
                security=SecurityEvidence(publicly_reachable=True, requires_authentication=True,
                                          transport_security=TransportSecurity.UNSPECIFIED,
                                          data_classification=ctx.classification),
                properties={"Protocol": "long-lived sockets", "State": "connection registry only"},
                warnings=["Function platforms cannot hold this connection; it is deliberately a resident service."],
            ),
            "inferred",
            ["Persistent connection or live-update requirement was identified."],
        )

    # --------------------------------------------------------------- queues
    if ctx.signals.messaging_needed or ctx.long_running or ctx.signals.event_driven or ctx.signals.generated_files:
        evidence = []
        if ctx.signals.messaging_needed:
            evidence.append("Explicit asynchronous messaging or queueing described.")
        if ctx.long_running:
            evidence.append("Slow work must be taken off the request path.")
        if ctx.signals.generated_files:
            evidence.append("Generated artefacts are produced after the triggering request.")
        if not evidence:
            evidence.append("Event-driven behaviour identified; a durable buffer decouples producers from consumers.")
        add(
            ComponentPlan(
                type=LogicalComponentType.QUEUE,
                id="queue",
                label="Work queue / event buffer",
                description=(
                    "Durable buffer between the request path and background processing, with retries and a "
                    "dead-letter destination so failures are visible instead of silent."
                ),
                traits=_traits(runtime=ComponentRuntime.EVENT_TRIGGERED, stateful=True, always_on=False,
                               event_triggered=True),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=ctx.classification, iam_scope=IamScope.SCOPED),
                properties={"Delivery": "at-least-once; consumers must be idempotent"},
            ),
            "inferred",
            evidence,
        )

    # ------------------------------------------------ background processing
    if ctx.long_running or ctx.signals.generated_files or ctx.signals.cpu_or_memory_intensive or ctx.signals.gpu_required:
        evidence = []
        minutes = ctx.signals.longest_operation_minutes
        if minutes:
            evidence.append(f"Longest stated operation is {minutes:g} min.")
        if ctx.signals.gpu_required:
            evidence.append("GPU acceleration requested.")
        if ctx.signals.cpu_or_memory_intensive:
            evidence.append("CPU/memory-intensive processing identified.")
        if ctx.signals.generated_files:
            evidence.append("The application produces files (PDFs, exports, media).")
        if ctx.signals.custom_runtime_required:
            evidence.append("Custom runtime or native dependencies named.")
        add(
            ComponentPlan(
                type=LogicalComponentType.WORKER,
                id="processing",
                label="Background processing",
                description=(
                    "Consumes queued work: document generation, media processing, bulk exports and other "
                    "operations that must not block a user request."
                ),
                traits=_traits(
                    runtime=ComponentRuntime.LONG_RUNNING if minutes and minutes > 15 else ComponentRuntime.EVENT_TRIGGERED,
                    stateful=False,
                    always_on=bool(minutes and minutes > 15),
                    event_triggered=not bool(minutes and minutes > 15),
                    duration=ctx.duration_profile,
                    cpu_or_memory_intensive=bool(ctx.signals.cpu_or_memory_intensive),
                    gpu_required=bool(ctx.signals.gpu_required),
                    custom_runtime=bool(ctx.signals.custom_runtime_required),
                    needs_local_filesystem=bool(ctx.signals.custom_runtime_required),
                    estimated_duration_ms=int(minutes * 60_000) if minutes else None,
                ),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          iam_scope=IamScope.UNSPECIFIED,
                                          secrets_handling="unspecified",
                                          data_classification=ctx.classification),
                properties={
                    "Longest operation": f"{minutes:g} min" if minutes else "not stated",
                    "Trigger": "queue / event",
                },
                warnings=[
                    "Execution longer than the platform function budget must run as a job or container, not a function."
                ] if minutes and minutes > 15 else [],
            ),
            "inferred",
            evidence,
        )

    # --------------------------------------------------------- scheduled jobs
    if ctx.signals.scheduled_batch:
        add(
            ComponentPlan(
                type=LogicalComponentType.SCHEDULER,
                id="scheduled",
                label="Scheduled jobs",
                description=(
                    "Time-triggered work such as end-of-day summaries, retention clean-up and periodic "
                    "reconciliation, expressed as schedules rather than as a resident cron process."
                ),
                traits=_traits(runtime=ComponentRuntime.SCHEDULED_BATCH, stateful=False, always_on=False,
                               duration=DurationProfile.FEW_SECONDS, event_triggered=True),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=ctx.classification),
                properties={"Cadence": "stated schedule", "Idempotency": "required for retried runs"},
            ),
            "inferred",
            ["Scheduled or periodic processing described."],
        )

    # ---------------------------------------------------- stream ingestion
    if ctx.signals.streaming_ingestion:
        add(
            ComponentPlan(
                type=LogicalComponentType.DATA_STREAM,
                id="stream",
                label="Event stream ingestion",
                description=(
                    "Continuous ingest path for high-rate events (telemetry, tracking, clickstream) with "
                    "partition ordering and a replay window."
                ),
                traits=_traits(runtime=ComponentRuntime.STREAMING, stateful=True, always_on=True,
                               duration=DurationProfile.INDEFINITE, persistent_connections=True),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=ctx.classification),
                properties={"Ordering": "per partition key", "Backpressure": "required"},
                warnings=["Consumers must be resident; a per-invocation function cannot own a stream partition."],
            ),
            "inferred",
            ["Continuous stream or high-rate event ingestion identified."],
        )

    # ------------------------------------------------------------ data stores
    relational = bool(ctx.signals.relational_data or ctx.signals.transactional_writes) or (
        requirements.application_type in RECORD_KEEPING_TYPES
        and not ctx.signals.document_data
    )
    if relational:
        evidence = []
        if ctx.signals.relational_data:
            evidence.append("Relational/record-oriented data described.")
        if ctx.signals.transactional_writes:
            evidence.append("Transactional writes identified.")
        if not evidence:
            evidence.append("Record keeping is inherent to the identified application type (assumption).")
        add(
            ComponentPlan(
                type=LogicalComponentType.RELATIONAL_DB,
                id="primary_store",
                label="Primary transactional store",
                description=(
                    "System of record for entities, relationships and constraints. Enforces uniqueness and "
                    "transactional integrity for the described write paths."
                ),
                traits=_traits(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                               duration=DurationProfile.INDEFINITE,
                               connection_pool_pressure=bool(ctx.signals.peak_concurrency and ctx.signals.peak_concurrency > 2000)),
                security=SecurityEvidence(
                    publicly_reachable=False,
                    requires_authentication=True,
                    transport_security=TransportSecurity.UNSPECIFIED,
                    data_classification=ctx.classification,
                    encryption_at_rest=None,
                    iam_scope=IamScope.UNSPECIFIED,
                    backup_policy=BackupPolicy.UNSPECIFIED,
                ),
                properties={
                    "Pattern": "normalised, transactional",
                    "Peak concurrency": f"{ctx.signals.peak_concurrency:,}" if ctx.signals.peak_concurrency else "not stated",
                },
                warnings=(
                    ["Concurrency above the typical connection budget of a managed instance requires a pooler."]
                    if ctx.signals.peak_concurrency and ctx.signals.peak_concurrency > 2000
                    else []
                ),
            ),
            "inferred" if evidence[0].endswith("(assumption).") else "user_asserted",
            evidence,
        )

    if ctx.signals.document_data or ctx.signals.key_value_data:
        add(
            ComponentPlan(
                type=LogicalComponentType.DOCUMENT_DB,
                id="document_store",
                label="Document / key-value store",
                description=(
                    "Schema-flexible storage for responses, profiles and per-user state accessed by key, where "
                    "a normalised model would add joins without adding correctness."
                ),
                traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=True,
                               duration=DurationProfile.INDEFINITE),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=ctx.classification,
                                          backup_policy=BackupPolicy.UNSPECIFIED),
                properties={"Access": "by key or composite key", "Consistency": "document-level"},
            ),
            "user_asserted" if ctx.signals.document_data else "inferred",
            ["Schema-flexible or key/value data described."],
        )

    if ctx.signals.cache_needed or ctx.signals.stateful_sessions or ctx.signals.high_fanout_reads:
        evidence = []
        if ctx.signals.cache_needed:
            evidence.append("Caching requirement stated.")
        if ctx.signals.stateful_sessions:
            evidence.append("Session state must move out of the compute to scale it.")
        if ctx.signals.high_fanout_reads:
            evidence.append("Read fan-out identified (results, leaderboards, catalog browsing).")
        add(
            ComponentPlan(
                type=LogicalComponentType.CACHE,
                id="cache",
                label="Cache & shared state",
                description=(
                    "In-memory store for hot reads, counters, locks and session data so that compute stays "
                    "stateless and read amplification does not reach the primary store."
                ),
                traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=True,
                               duration=DurationProfile.INDEFINITE),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=DataClassification.INTERNAL,
                                          encryption_at_rest=None),
                properties={"Not a system of record": "true", "TTL": "required for session keys"},
            ),
            "inferred",
            evidence,
        )

    if ctx.signals.object_storage_needed or ctx.signals.generated_files or ctx.signals.upload_size_mb:
        evidence = []
        if ctx.signals.object_storage_needed:
            evidence.append("Files or uploads must be stored.")
        if ctx.signals.generated_files:
            evidence.append("Application generates artefacts (certificates, exports, media).")
        if ctx.signals.upload_size_mb:
            evidence.append(f"Individual file size stated as up to {ctx.signals.upload_size_mb:g} MB.")
        add(
            ComponentPlan(
                type=LogicalComponentType.OBJECT_STORAGE,
                id="files",
                label="Object storage for artefacts",
                description=(
                    "Durable store for uploads and generated documents, addressed by opaque keys, with "
                    "lifecycle rules and event notifications for downstream processing."
                ),
                traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False,
                               duration=DurationProfile.UNSPECIFIED),
                security=SecurityEvidence(publicly_reachable=None, requires_authentication=True,
                                          data_classification=ctx.classification,
                                          encryption_at_rest=None,
                                          iam_scope=IamScope.UNSPECIFIED),
                properties={"Event source": "object-created notifications", "Access": "signed URLs, not public buckets"},
            ),
            "user_asserted" if ctx.signals.object_storage_needed else "inferred",
            evidence,
        )

    if ctx.signals.filesystem_semantics_required:
        add(
            ComponentPlan(
                type=LogicalComponentType.BLOCK_STORAGE,
                id="filesystem",
                label="Filesystem volume (shared)",
                description=(
                    "POSIX-like shared volume required by the stated filesystem semantics. Flagged because "
                    "object storage is not an equivalent substitution."
                ),
                traits=_traits(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                               needs_local_filesystem=True, duration=DurationProfile.INDEFINITE),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=ctx.classification, iam_scope=IamScope.UNSPECIFIED),
                properties={"Constraint": "requires VNet-attached compute"},
                warnings=["No serverless-equivalent exists for shared filesystem semantics."],
            ),
            "user_asserted",
            ["Shared filesystem or drive semantics requested."],
        )

    if ctx.signals.search_needed:
        add(
            ComponentPlan(
                type=LogicalComponentType.SEARCH_INDEX,
                id="search",
                label="Search index",
                description=(
                    "Inverted index for text and faceted queries, fed by change events from the primary store "
                    "instead of being written inline with user requests."
                ),
                traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=True,
                               duration=DurationProfile.INDEFINITE),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=ctx.classification),
                properties={"Freshness": "eventual; index lag must be tolerated or explained"},
            ),
            "user_asserted" if ctx.signals.search_needed else "inferred",
            ["Text search or filtering described."],
        )

    if ctx.signals.pdf_or_reporting and (ctx.signals.dataset_size_gb or requirements.application_type in {
        ApplicationType.EXAMINATION_PLATFORM, ApplicationType.LEARNING_PLATFORM, ApplicationType.ECOMMERCE
    }):
        add(
            ComponentPlan(
                type=LogicalComponentType.DATA_WAREHOUSE,
                id="analytics",
                label="Reporting & analytics store",
                description=(
                    "Separate analytical copy for multi-dimensional reporting so that dashboard queries do "
                    "not compete with transactional workloads."
                ),
                traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False,
                               duration=DurationProfile.MINUTES, data_intensity="high"),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=ctx.classification, encryption_at_rest=None),
                properties={"Feed": "batch or CDC from primary store"},
            ),
            "inferred",
            ["Reporting workload identified alongside a record-keeping store."],
            required=False,
        )

    if ctx.signals.notification_required:
        add(
            ComponentPlan(
                type=LogicalComponentType.NOTIFICATION,
                id="notify",
                label="Notification delivery",
                description=(
                    "Outbound email/SMS/push delivery through a managed channel provider, invoked from the "
                    "async path so that a slow provider cannot delay a user-visible response."
                ),
                traits=_traits(runtime=ComponentRuntime.EVENT_TRIGGERED, stateful=False, always_on=False,
                               event_triggered=True, duration=DurationProfile.FEW_SECONDS),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=DataClassification.INTERNAL,
                                          secrets_handling="provider credentials"),
                properties={"Quotas": "provider sending limits apply"},
            ),
            "user_asserted",
            ["Outbound notification requirement stated."],
        )

    # ------------------------------------------------------ operational rails
    if relational or ctx.signals.relational_data or ctx.signals.object_storage_needed:
        add(
            ComponentPlan(
                type=LogicalComponentType.BACKUP,
                id="backup",
                label="Backup & recovery policy",
                description=(
                    "Snapshot and restore policy for the stateful stores, including a tested restore path and "
                    "a defined retention window."
                ),
                traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False),
                security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                          data_classification=ctx.classification,
                                          backup_policy=BackupPolicy.UNSPECIFIED, encryption_at_rest=None),
                properties={"Restore test": "required, not optional"},
            ),
            "inferred",
            ["Stateful data stores exist, so recovery capability must be specified."],
            required=False,
        )

    add(
        ComponentPlan(
            type=LogicalComponentType.MONITORING,
            id="observability",
            label="Metrics, logs & alerting",
            description=(
                "Structured logs, request traces, saturation metrics and alerts on the asynchronous paths, "
                "which is where a managed runtime hides its failure modes."
            ),
            traits=_traits(runtime=ComponentRuntime.MANAGED, stateful=False, always_on=False),
            security=SecurityEvidence(publicly_reachable=False, requires_authentication=True,
                                      data_classification=DataClassification.INTERNAL,
                                      audit_logging=bool(ctx.signals.requires_audit_trail)),
            properties={"Includes": "dead-letter depth, throttling, cold starts, duration percentiles"},
        ),
        "inferred",
        ["Operational visibility is required for any production service (engine default)."],
        required=False,
    )

    deduped = _deduplicate(plans)
    return deduped, [item for item in inventory if any(item.id == plan.id for plan in deduped)]


def _deduplicate(plans: list[ComponentPlan]) -> list[ComponentPlan]:
    seen: dict[str, ComponentPlan] = {}
    for plan in plans:
        key = plan.id or plan.type.value
        if key in seen:
            existing = seen[key]
            existing.evidence = list(dict.fromkeys(existing.evidence + plan.evidence))
            existing.warnings = list(dict.fromkeys(existing.warnings + plan.warnings))
            continue
        plan.id = key
        seen[key] = plan
    return list(seen.values())


def _tier_for(component_type: LogicalComponentType) -> ComponentTier:
    return TIER_BY_TYPE[component_type]


TIER_BY_TYPE: dict[LogicalComponentType, ComponentTier] = {
    LogicalComponentType.CLIENT_WEB: ComponentTier.EDGE,
    LogicalComponentType.CLIENT_MOBILE: ComponentTier.EDGE,
    LogicalComponentType.DNS: ComponentTier.EDGE,
    LogicalComponentType.CDN: ComponentTier.EDGE,
    LogicalComponentType.LOAD_BALANCER: ComponentTier.PRESENTATION,
    LogicalComponentType.API_GATEWAY: ComponentTier.PRESENTATION,
    LogicalComponentType.WEB_SERVER: ComponentTier.APPLICATION,
    LogicalComponentType.APP_SERVER: ComponentTier.APPLICATION,
    LogicalComponentType.FUNCTION: ComponentTier.APPLICATION,
    LogicalComponentType.CONTAINER_SERVICE: ComponentTier.APPLICATION,
    LogicalComponentType.VIRTUAL_MACHINE: ComponentTier.APPLICATION,
    LogicalComponentType.QUEUE: ComponentTier.INTEGRATION,
    LogicalComponentType.PUBSUB: ComponentTier.INTEGRATION,
    LogicalComponentType.SCHEDULER: ComponentTier.INTEGRATION,
    LogicalComponentType.DATA_STREAM: ComponentTier.INTEGRATION,
    LogicalComponentType.NOTIFICATION: ComponentTier.INTEGRATION,
    LogicalComponentType.WORKER: ComponentTier.PROCESSING,
    LogicalComponentType.BATCH_JOB: ComponentTier.PROCESSING,
    LogicalComponentType.REPORTING: ComponentTier.PROCESSING,
    LogicalComponentType.ML_INFERENCE: ComponentTier.PROCESSING,
    LogicalComponentType.RELATIONAL_DB: ComponentTier.DATA,
    LogicalComponentType.DOCUMENT_DB: ComponentTier.DATA,
    LogicalComponentType.KEY_VALUE_DB: ComponentTier.DATA,
    LogicalComponentType.CACHE: ComponentTier.DATA,
    LogicalComponentType.SEARCH_INDEX: ComponentTier.DATA,
    LogicalComponentType.OBJECT_STORAGE: ComponentTier.DATA,
    LogicalComponentType.BLOCK_STORAGE: ComponentTier.DATA,
    LogicalComponentType.TIME_SERIES_DB: ComponentTier.DATA,
    LogicalComponentType.DATA_WAREHOUSE: ComponentTier.DATA,
    LogicalComponentType.BACKUP: ComponentTier.DATA,
    LogicalComponentType.AUTH_IDENTITY: ComponentTier.SECURITY,
    LogicalComponentType.SECRETS_MANAGER: ComponentTier.SECURITY,
    LogicalComponentType.MONITORING: ComponentTier.OPERATIONS,
    LogicalComponentType.LOGGING: ComponentTier.OPERATIONS,
    LogicalComponentType.CI_ARTIFACT_STORE: ComponentTier.OPERATIONS,
}

assert set(TIER_BY_TYPE) == set(LogicalComponentType), "every logical type needs a tier"
