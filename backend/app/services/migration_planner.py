"""Migration complexity and roadmap stage.

Every statement in the output is traceable to a component difference between
the conventional view and the proposed view, or to a recorded signal.  The
planner never prints calendar estimates: NYX has no team size, no test-coverage
figure and no code to inspect, so time claims would be fiction (this is stated
in the report itself).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.architecture import ArchitectureGraph, LogicalComponentType
from app.schemas.common import EffortLevel, Severity, SuitabilityOutcome
from app.schemas.reports import (
    MigrationChange,
    MigrationPhase,
    MigrationReport,
    SecurityReport,
    SuitabilityReport,
)
from app.schemas.requirements import ApplicationRequirements, RequirementSignals

WEIGHTS: dict[EffortLevel, float] = {
    EffortLevel.LOW: 1.0,
    EffortLevel.MODERATE: 2.5,
    EffortLevel.HIGH: 4.0,
    EffortLevel.FURTHER_ASSESSMENT: 3.0,
}
MAX_WEIGHT_PER_CHANGE = 4.0


@dataclass(frozen=True)
class ChangeRule:
    """What has to happen to one logical responsibility when it is realized differently."""

    key: str
    change: str
    complexity: EffortLevel
    reason: str
    dependencies: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    activities: tuple[str, ...] = ()
    exit_criteria: tuple[str, ...] = ()
    phase: str = "decomposition"


CHANGE_RULES: dict[LogicalComponentType, list[ChangeRule]] = {
    LogicalComponentType.FUNCTION: [
        ChangeRule(
            key="decompose-handlers",
            change="Split the request-handling tier into per-use-case handlers with no shared in-process state",
            complexity=EffortLevel.HIGH,
            reason=(
                "Code that assumes a warm process (caches, singletons, connection objects, middleware order) has to "
                "be restructured before it can run as an independent invocation."
            ),
            dependencies=("cross-cutting middleware", "shared library versions", "request/response contracts"),
            issues=("execution time limited by the platform", "deployment package size", "cold-start latency on the hot path"),
            activities=("list every endpoint and its current middleware", "extract shared behaviour into gateway rules or layers",
                        "port one read-only endpoint first and compare behaviour"),
            exit_criteria=("one endpoint runs end-to-end on the new runtime behind a test route",
                           "handler tests cover the same assertions as the endpoint tests they replace"),
            phase="decomposition",
        ),
    ],
    LogicalComponentType.CONTAINER_SERVICE: [
        ChangeRule(
            key="containerise-runtime",
            change="Package the long-running runtime as an image with pinned dependencies and graceful shutdown",
            complexity=EffortLevel.MODERATE,
            reason="The work stays resident on purpose, so the effort is image hygiene and start-up/shutdown behaviour rather than decomposition.",
            dependencies=("base image choice", "native dependencies", "health check contract"),
            issues=("memory profile must be sized explicitly", "start-up time counts against latency on the first request"),
            activities=("write and pin the image build", "move configuration to environment + secret references",
                        "implement drain on SIGTERM"),
            exit_criteria=("image builds reproducibly in CI", "instance can be killed mid-request without losing work"),
            phase="decomposition",
        ),
    ],
    LogicalComponentType.BATCH_JOB: [
        ChangeRule(
            key="job-runtime",
            change="Move long work into an explicit job runtime with checkpointing and retry semantics",
            complexity=EffortLevel.HIGH,
            reason="Jobs longer than the function budget need a runtime that survives them, plus a way to resume rather than restart.",
            dependencies=("input staging in object storage", "result write-back", "queue depth alarms"),
            issues=("no partial-progress storage today", "workspace disk assumptions", "licensing of the processing library"),
            activities=("define the job contract (input, output, failure)", "add checkpoint/resume",
                        "cap retries and route to a dead-letter queue"),
            exit_criteria=("a job interrupted at 50% completes correctly after retry", "backlog depth is alerted"),
            phase="decomposition",
        ),
    ],
    LogicalComponentType.OBJECT_STORAGE: [
        ChangeRule(
            key="files-to-objects",
            change="Replace filesystem paths with object keys, signed URLs and lifecycle rules",
            complexity=EffortLevel.MODERATE,
            reason="Any stored path, in-place edit or directory walk becomes an object operation; this touches both code and existing records.",
            dependencies=("stored path columns", "export tooling", "backup scripts"),
            issues=("no rename or append semantics", "existing rows referencing local paths"),
            activities=("inventory every path reference", "add a key-mapping migration for existing records",
                        "convert generated documents to write-once objects"),
            exit_criteria=("no code path writes outside object storage", "historical objects are readable through the new key scheme"),
            phase="storage",
        ),
    ],
    LogicalComponentType.BLOCK_STORAGE: [
        ChangeRule(
            key="keep-fileshare",
            change="Keep the shared volume, but attach it only to the resident runtime",
            complexity=EffortLevel.MODERATE,
            reason="Filesystem semantics have no serverless equivalent, so the honest move is to shrink the blast radius rather than pretend the dependency vanished.",
            dependencies=("network/file share provisioning", "mount permissions"),
            issues=("requires private network attachment from the compute that mounts it",),
            activities=("confirm which components truly need POSIX semantics", "mount the share on the job runtime only"),
            exit_criteria=("only the intended components can reach the share",),
            phase="storage",
        ),
    ],
    LogicalComponentType.RELATIONAL_DB: [
        ChangeRule(
            key="managed-db",
            change="Move the system of record onto a managed engine with automated backup and pooling",
            complexity=EffortLevel.HIGH,
            reason="Data movement plus connection-pattern change; the schema is not the hard part, the cutover and connection budget are.",
            dependencies=("schema compatibility", "application timeouts and retries", "function concurrency limits"),
            issues=("connection ceiling vs function concurrency", "cutover window", "extension or engine version gaps"),
            activities=("reconcile row counts and constraints in a shadow copy", "put a pooler in front before enabling scale-out",
                        "define the rollback point for the cutover"),
            exit_criteria=("shadow reconciliation passes", "peak concurrency holds with the pooler in place"),
            phase="data",
        ),
    ],
    LogicalComponentType.DOCUMENT_DB: [
        ChangeRule(
            key="managed-nosql",
            change="Port document or key/value access to a managed store and re-key for the real access patterns",
            complexity=EffortLevel.MODERATE,
            reason="A document store rewards access-pattern-first key design; a lift-and-shift of relational queries produces slow reads.",
            dependencies=("query inventory", "index definitions"),
            issues=("no joins", "document size limits"),
            activities=("list each query and its key", "denormalise where reads need it"),
            exit_criteria=("every read path is a key lookup or a bounded query",),
            phase="data",
        ),
    ],
    LogicalComponentType.CACHE: [
        ChangeRule(
            key="externalise-cache",
            change="Externalise session and hot-read state into a managed cache with explicit TTLs",
            complexity=EffortLevel.MODERATE,
            reason="Until state leaves the process, the compute tier cannot be started and stopped per request.",
            dependencies=("session cookie handling", "login/logout invalidation"),
            issues=("in-process locks must become atomic cache operations",),
            activities=("list every in-process state object", "choose token-based or cache-backed sessions", "add TTL and eviction policy"),
            exit_criteria=("any instance can serve any request without losing a session",),
            phase="configuration",
        ),
    ],
    LogicalComponentType.QUEUE: [
        ChangeRule(
            key="managed-queue",
            change="Replace the self-hosted broker with a managed queue, dead-letter path and event-source mapping",
            complexity=EffortLevel.MODERATE,
            reason="Delivery semantics change from 'usually once' to at-least-once, so consumers must become idempotent.",
            dependencies=("message schema", "consumer idempotency", "retry and visibility settings"),
            issues=("duplicate delivery", "ordering assumptions"),
            activities=("add a deduplication key to every message", "configure max receives plus a dead-letter queue", "alarm on queue depth"),
            exit_criteria=("replaying a message twice produces the same result", "dead-lettered messages are actionable"),
            phase="async",
        ),
    ],
    LogicalComponentType.SCHEDULER: [
        ChangeRule(
            key="platform-schedule",
            change="Convert cron entries into platform schedules that invoke handlers directly",
            complexity=EffortLevel.LOW,
            reason="The schedule becomes configuration with platform-side retries instead of a script on one host.",
            dependencies=("time zone assumptions", "job idempotency"),
            issues=("missed-run behaviour differs from cron",),
            activities=("declare each schedule as code", "add a per-run identifier so overlapping runs are detected"),
            exit_criteria=("a deliberately missed run recovers without duplicate output",),
            phase="configuration",
        ),
    ],
    LogicalComponentType.AUTH_IDENTITY: [
        ChangeRule(
            key="managed-identity",
            change="Move credentials, password policy and token issuance into a managed identity provider",
            complexity=EffortLevel.HIGH,
            reason="Password hash portability and session invalidation semantics are the risky parts, not the login screen.",
            dependencies=("user migration strategy", "role/claim mapping", "client redirect URIs"),
            issues=("non-portable password hashes force a reset path", "session revocation changes"),
            activities=("decide bulk import vs just-in-time migration", "map roles to token claims", "test the reset flow before cutover"),
            exit_criteria=("no credentials are stored in application data after cutover",),
            phase="identity",
        ),
    ],
    LogicalComponentType.API_GATEWAY: [
        ChangeRule(
            key="gateway-policies",
            change="Express routing, authorization, throttling and request validation as gateway configuration",
            complexity=EffortLevel.MODERATE,
            reason="Cross-cutting checks move out of every handler into one declarative place, which changes how routes are tested.",
            dependencies=("route contracts", "client authentication headers", "CORS and error body shape"),
            issues=("integration timeout is shorter than an application server's", "payload size limits"),
            activities=("write the OpenAPI contract per route", "attach authorizers and request validation", "compare error responses with the old client expectations"),
            exit_criteria=("unauthenticated requests are rejected before any handler is invoked",),
            phase="decomposition",
        ),
    ],
    LogicalComponentType.CDN: [
        ChangeRule(
            key="edge-assets",
            change="Serve client assets from the edge with fingerprinted builds and TLS enforced",
            complexity=EffortLevel.LOW,
            reason="Static delivery moves out of the application entirely; the work is build output and cache policy.",
            dependencies=("build pipeline", "asset paths"),
            issues=("invalidation latency for hotfixes",),
            activities=("emit hashed asset names", "configure cache and redirect rules"),
            exit_criteria=("an asset-only release requires no compute deployment",),
            phase="configuration",
        ),
    ],
    LogicalComponentType.MONITORING: [
        ChangeRule(
            key="telemetry",
            change="Instrument structured logs, per-use-case metrics and alarms on throttling and dead-letter depth",
            complexity=EffortLevel.MODERATE,
            reason="A managed runtime hides saturation signals; without new alarms, the first incident is discovered by users.",
            dependencies=("log schema", "correlation id propagation"),
            issues=("log volume drives its own cost line",),
            activities=("add request correlation ids", "alarm on throttles, duration percentiles and queue depth", "set retention explicitly"),
            exit_criteria=("a synthetic fault is detected by an alarm before a user reports it",),
            phase="operations",
        ),
    ],
    LogicalComponentType.BACKUP: [
        ChangeRule(
            key="backup-policy",
            change="Enable automated snapshots with retention and rehearse a restore",
            complexity=EffortLevel.LOW,
            reason="Managed services make the mechanism cheap; the remaining work is agreeing retention and proving the restore.",
            dependencies=("retention requirement", "restore access permissions"),
            issues=("an untested backup proves nothing",),
            activities=("agree the recovery point and time", "perform one timed restore into a scratch environment"),
            exit_criteria=("a restore has been performed and documented",),
            phase="operations",
        ),
    ],
    LogicalComponentType.NOTIFICATION: [
        ChangeRule(
            key="async-notify",
            change="Move notification sending onto the async path with provider quotas recorded",
            complexity=EffortLevel.LOW,
            reason="Removes a synchronous third-party dependency from the user-visible request.",
            dependencies=("template content ownership", "provider credentials"),
            issues=("provider rate limits become the binding constraint at peak",),
            activities=("send from a queue consumer", "add retry with backoff and a suppression rule"),
            exit_criteria=("a provider outage does not delay a user response",),
            phase="async",
        ),
    ],
}

RETAINED_NOTE = "No change proposed for this component; it is listed so the roadmap accounts for it."


@dataclass
class PlannedChange:
    """One proposed component change plus the rule that produced it."""

    change: MigrationChange
    rule: ChangeRule | None = None


def _stem(component_id: str) -> str:
    for suffix in ("-fn", "-svc", "-store"):
        if component_id.endswith(suffix):
            return component_id[: -len(suffix)]
    return component_id


class MigrationPlanner:
    def plan(
        self,
        conventional: ArchitectureGraph,
        proposed: ArchitectureGraph,
        suitability: SuitabilityReport,
        security: SecurityReport,
        signals: RequirementSignals,
        requirements: ApplicationRequirements,
    ) -> MigrationReport:
        conventional_by_stem = {_stem(item.id): item for item in conventional.components}
        planned: list[PlannedChange] = []

        for component in proposed.components:
            counterpart = conventional_by_stem.get(_stem(component.id))
            rules = CHANGE_RULES.get(component.type, [])
            if not rules:
                planned.append(
                    PlannedChange(
                        change=MigrationChange(
                            component_id=component.id,
                            component_label=component.label,
                            change="Retain the component and re-point its configuration at the managed equivalent",
                            complexity=EffortLevel.LOW,
                            reason=RETAINED_NOTE,
                            dependencies=[],
                            compatibility_issues=[],
                        )
                    )
                )
                continue
            for rule in rules:
                issues = list(rule.issues)
                if component.type == LogicalComponentType.FUNCTION and signals.longest_operation_minutes and \
                        signals.longest_operation_minutes > 2:
                    issues.append(
                        f"Stated operations run up to {signals.longest_operation_minutes:g} min; the platform "
                        "invocation budget must be verified before this handler is scheduled as a function."
                    )
                if component.type == LogicalComponentType.RELATIONAL_DB and component.traits.connection_pool_pressure:
                    issues.append(
                        "Function concurrency can exhaust the database connection budget; a pooler is a "
                        "prerequisite, not an optimisation."
                    )
                planned.append(
                    PlannedChange(
                        change=MigrationChange(
                            component_id=component.id,
                            component_label=component.label,
                            change=rule.change,
                            complexity=rule.complexity,
                            reason=(
                                rule.reason
                                if counterpart is None
                                else f"{rule.reason} It replaces “{counterpart.label}” in the current design."
                            ),
                            dependencies=list(rule.dependencies),
                            compatibility_issues=issues,
                        ),
                        rule=rule,
                    )
                )

        # Workload-level items that are not tied to a single node.
        extra_issues: list[str] = []
        if signals.persistent_connections:
            extra_issues.append(
                "Persistent protocols cannot be hosted inside an invocation, so one resident service stays in the "
                "design; the roadmap must not treat it as leftover work."
            )
        if signals.custom_runtime_required:
            extra_issues.append(
                "Native or custom runtime dependencies constrain packaging (layers or images) and must be proven "
                "before decomposition starts."
            )
        if signals.gpu_required or any(component.traits.gpu_required for component in proposed.components):
            extra_issues.append(
                "Accelerator (GPU) capacity is not available on every serverless runtime and is quota- and "
                "region-bound; confirm capacity, cold-start cost and per-second billing before this component is "
                "placed, or keep it on a dedicated pool."
            )
        if signals.multi_tenant:
            extra_issues.append("Tenant isolation guarantees have to be re-expressed in the new permission model.")
        if signals.stateful_sessions:
            extra_issues.append("Existing server-side sessions must be re-issued or migrated, which is a user-visible cutover.")
        if signals.compliance_regime:
            extra_issues.append(f"Stated compliance regime ({signals.compliance_regime}) constrains region, retention and audit evidence.")

        changes = [item.change for item in planned]
        dependency_review = _dependencies(proposed, changes, signals)
        validation = _validation(suitability, signals, security, proposed)
        risks = _risks(suitability, signals, proposed)
        phases = _phases(planned, proposed, conventional, suitability, signals, security, requirements)

        raw = sum(WEIGHTS[change.complexity] for change in changes) + 0.5 * len(extra_issues)
        ceiling = MAX_WEIGHT_PER_CHANGE * max(len(changes), 1)
        score = round(min(100.0, raw / ceiling * 100.0), 1)

        if suitability.outcome == SuitabilityOutcome.FURTHER_ASSESSMENT:
            overall = EffortLevel.FURTHER_ASSESSMENT
        elif score < 28:
            overall = EffortLevel.LOW
        elif score < 55:
            overall = EffortLevel.MODERATE
        else:
            overall = EffortLevel.HIGH

        drivers = sorted(
            [f"{change.component_label}: {change.complexity.value} ({change.change[:60]}…)" for change in changes],
            key=lambda text: text,
        )[:6]
        drivers.insert(0, f"Aggregate weighted effort: {raw:.1f} of a possible {ceiling + 0.5 * len(extra_issues):.1f}.")

        return MigrationReport(
            overall_complexity=overall,
            complexity_score=score,
            complexity_drivers=drivers,
            components_requiring_modification=changes,
            dependencies_to_review=dependency_review,
            compatibility_issues=list(dict.fromkeys(extra_issues)),
            validation_requirements=validation,
            risks=risks,
            assumptions=[
                "The proposed architecture is implemented as modelled, in the same component boundaries.",
                "Existing behaviour is describable by tests or by a comparison harness; where it is not, the "
                "first phase includes writing them.",
            ] + [statement[:200] for statement in getattr(requirements, "provenance", {}) ][:0],
            phases=phases,
            sequencing_rationale=(
                "Configuration and storage changes come before code decomposition because they are reversible, "
                "independently testable, and they remove the dependencies (local paths, in-process sessions) that "
                "make handlers hard to split. Data migration sits before target implementation for the same reason: "
                "a new runtime reading the old database shape doubles the risk."
            ),
            caveats=[
                "NYX does not publish durations, sprint counts or person-days. Effort depends on team size, "
                "existing test coverage and code quality, none of which this analysis can observe.",
                "Complexity is derived from the recorded component changes and is relative to this rule pack version.",
            ]
            + (
                [
                    "This roadmap is conditional: the suitability verdict was provisional because "
                    f"{len(suitability.missing_inputs)} deciding input(s) had no evidence. Answer the open questions "
                    "first — if the answers change the shape of the system, these phases must be re-derived."
                ]
                if suitability.outcome == SuitabilityOutcome.FURTHER_ASSESSMENT
                else []
            ),
        )


def _dependencies(
    proposed: ArchitectureGraph, changes: list[MigrationChange], signals: RequirementSignals
) -> list[str]:
    items: list[str] = []
    for component in proposed.components:
        if component.tier.value == "data":
            items.append(f"{component.label}: schema, access pattern and connection budget")
        if component.type in {LogicalComponentType.QUEUE, LogicalComponentType.DATA_STREAM}:
            items.append(f"{component.label}: message schema, idempotency key and dead-letter destination")
        if component.type in {LogicalComponentType.AUTH_IDENTITY}:
            items.append(f"{component.label}: client redirect URIs, role claims and token lifetime")
    if signals.third_party_integrations:
        items.append(
            "Third-party integrations: " + ", ".join(signals.third_party_integrations)
            + " (rate limits and credentials must be re-issued per deployment)"
        )
    items.append("Shared libraries and middleware that every handler will duplicate or reference")
    items.append("Any client that pins timeouts to the current response behaviour")
    if signals.peak_concurrency and signals.peak_concurrency > 1500:
        items.append(f"Platform quota review at {signals.peak_concurrency:,} concurrent executions")
    return list(dict.fromkeys(items))[:14]


def _validation(
    suitability: SuitabilityReport, signals: RequirementSignals, security: SecurityReport, proposed: ArchitectureGraph
) -> list[str]:
    items = [
        "Behavioural parity check: run the same inputs through the old and new paths and diff the outputs.",
        "Load test at the stated peak x2, watching throttling errors rather than only response time.",
        "Idempotency test: deliver the same message twice and verify no duplicate side effect.",
        "Dead-letter test: force a poison message and confirm it lands somewhere visible.",
        "Restore test: recover a store from backup into a scratch environment, timed.",
    ]
    if signals.persistent_connections:
        items.append("Connection resilience test: restart the resident service and verify clients reconnect and resume.")
    if signals.long_running_jobs:
        items.append("Interrupted-job test: kill a job mid-run and confirm it resumes or fails cleanly.")
    if any(component.type == LogicalComponentType.FUNCTION for component in proposed.components):
        items.append(
            "Execution-duration test: run the longest real operation end to end on the function runtime and "
            "confirm it completes inside the platform invocation timeout, with retries that do not double-bill."
        )
    if signals.stateful_sessions or any(component.traits.stateful for component in proposed.components):
        items.append(
            "Statelessness test: send consecutive requests that must land on different instances and verify the "
            "outcome is identical (no sticky sessions, no local cache as a source of truth)."
        )
    if signals.peak_concurrency and signals.peak_concurrency > 1500:
        items.append("Database connection ceiling test at peak concurrency with the pooler enabled.")
    if suitability.outcome == SuitabilityOutcome.SUITABLE_WITH_MODIFICATIONS:
        items.append("Re-measure the suitability inputs after restructuring; the verdict depended on those changes.")
    if security.findings:
        items.append(
            f"Security review of the {len(security.findings)} open finding(s) plus evidence that each fix is in place."
        )
    elif security.baseline_findings:
        items.append(
            f"Verify each of the {len(security.baseline_findings)} finding(s) recorded against the current design is "
            "actually closed by the proposal, with evidence rather than intent."
        )
    if security.verification_gaps:
        items.append(f"Answer the {len(security.verification_gaps)} verification question(s) before go-live.")
    items.append("Cost alarms on the usage dimensions that dominate the proposed model (executions, GB-seconds, ingest).")
    return items


def _risks(suitability: SuitabilityReport, signals: RequirementSignals, proposed: ArchitectureGraph) -> list[str]:
    risks = [
        "Throttling or concurrency limits at peak: managed platforms enforce quotas that a self-managed server did not.",
        "Failure modes move into the asynchronous paths, which are the parts least likely to have tests today.",
        "Per-request cost grows with duration: the sensitivity table shows which model degrades first.",
    ]
    if signals.stateful_sessions:
        risks.append("Session migration is user-visible; a bad cutover logs people out or loses in-flight work.")
    if signals.relational_data:
        risks.append("Data cutover risk dominates: reconciliation errors here are not recoverable by rolling code back.")
    if signals.custom_runtime_required:
        risks.append("Packaging a custom runtime can fail late (size limits, missing OS libraries) after decomposition.")
    if any(component.type == LogicalComponentType.FUNCTION for component in proposed.components) and (
        signals.longest_operation_minutes or 0
    ) > 2:
        risks.append("A handler that occasionally exceeds the invocation budget turns a cost argument into an outage.")
    if suitability.outcome == SuitabilityOutcome.FURTHER_ASSESSMENT:
        risks.append("The verdict itself is provisional; unvalidated assumptions are the largest risk in this plan.")
    return risks


PHASE_TITLES: dict[str, tuple[int, str, str]] = {
    "inventory": (1, "Inventory and preparation", "Establish a shared, verified picture before anything changes."),
    "configuration": (2, "Configuration and storage changes", "Remove the dependencies that block decomposition."),
    "storage": (3, "Storage and artefact changes", "Break the coupling between content and a single host."),
    "data": (4, "Data migration and reconciliation", "Move the system of record with a proven rollback."),
    "identity": (5, "Identity and access cutover", "Replace in-house credential handling with managed identity."),
    "async": (6, "Asynchronous and event wiring", "Move slow work off the request path behind a durable buffer."),
    "decomposition": (7, "Component decomposition", "Turn the monolith's use cases into independent handlers."),
    "operations": (8, "Observability, backup and recovery", "Make the new failure modes visible before users are."),
    "validation": (9, "Testing and validation", "Prove behavioural parity, resilience at peak and restore capability."),
    "deployment": (10, "Deployment preparation", "Ship behind a controlled path with a rehearsed rollback."),
}


def _phases(
    planned: list[PlannedChange],
    proposed: ArchitectureGraph,
    conventional: ArchitectureGraph,
    suitability: SuitabilityReport,
    signals: RequirementSignals,
    security: SecurityReport,
    requirements: ApplicationRequirements,
) -> list[MigrationPhase]:
    by_phase: dict[str, list[PlannedChange]] = {}
    for item in planned:
        if item.rule is None:
            continue
        by_phase.setdefault(item.rule.phase, []).append(item)

    phases: list[MigrationPhase] = []

    def add(
        key: str,
        activities: list[str],
        touched: list[str],
        exit_criteria: list[str],
        risk: Severity = Severity.LOW,
        effort: EffortLevel = EffortLevel.MODERATE,
    ) -> None:
        activities = [entry for entry in dict.fromkeys(activities) if entry]
        if not activities:
            return
        order, title, objective = PHASE_TITLES[key]
        phases.append(
            MigrationPhase(
                id=f"phase-{key}",
                index=order,
                title=title,
                objective=objective,
                activities=activities,
                components_touched=touched,
                exit_criteria=list(dict.fromkeys(criterion for criterion in exit_criteria if criterion)),
                risk=risk,
                effort=effort,
            )
        )

    inventory_activities = [
        "Produce the component inventory from this analysis and confirm every entry against what actually exists.",
        "Record baseline metrics: request rate, p50/p95 duration, error rate, saturation and job backlog.",
        "Map which components are reachable from the internet and which are not.",
    ]
    if signals.expected_users is None:
        inventory_activities.append(
            "Establish a real traffic baseline: no user count was stated, so every quantity in this analysis is derived."
        )
    if signals.peak_requests_per_minute:
        inventory_activities.append(
            f"Confirm the derived peak ({signals.peak_requests_per_minute:,} req/min) against a measured dashboard."
        )
    if requirements.availability is None:
        inventory_activities.append("Agree the availability promise with the service owner; it is currently unstated.")
    if suitability.missing_inputs:
        inventory_activities.append(
            "Answer the open suitability questions first: " + "; ".join(suitability.missing_inputs[:4])
        )
    add(
        "inventory",
        inventory_activities,
        [],
        ["Inventory signed off by the people who operate the current system",
         "Baseline metrics captured across at least one full peak period"],
        Severity.LOW,
        EffortLevel.LOW,
    )

    for key in ("configuration", "storage", "data", "identity", "async", "decomposition", "operations"):
        bucket = by_phase.get(key, [])
        if not bucket and key != "operations":
            continue
        activities: list[str] = [item.rule.activities[0] if item.rule and item.rule.activities else "" for item in bucket]
        exit_criteria: list[str] = [criterion for item in bucket if item.rule for criterion in item.rule.exit_criteria]
        if key == "decomposition" and bucket:
            activities.append("Keep the old path deployed and route a small share of traffic to the new handlers.")
        if key == "operations":
            activities.append("Define alarm thresholds from the baseline captured in the inventory phase.")
            exit_criteria.extend(["Alarms fire during a controlled test", "A restore has been rehearsed and documented"])
        risk = Severity.MEDIUM if key in {"data", "identity"} else Severity.LOW
        effort = EffortLevel.MODERATE
        if key in {"data", "identity", "decomposition"}:
            effort = EffortLevel.HIGH
        if key in {"data", "identity", "decomposition"}:
            risk = Severity.HIGH
        add(
            key,
            activities,
            [item.change.component_id for item in bucket],
            exit_criteria,
            risk,
            effort,
        )

    validation_activities = _validation(suitability, signals, security, proposed)
    add(
        "validation",
        validation_activities,
        [component.id for component in proposed.components],
        ["Every validation item has a recorded result",
         "All high-severity findings are closed or explicitly accepted by the owner"],
        Severity.HIGH,
        EffortLevel.MODERATE,
    )

    add(
        "deployment",
        [
            "Put the function, gateway, queue and IAM definitions under version control with a review step.",
            "Implement a canary or per-route traffic shift with an automatic rollback trigger.",
            "Publish the runbook: dead-letter location, quota increase procedure, restore procedure.",
            "Set budget alarms on the usage dimensions that dominate the proposed cost model.",
        ],
        [],
        ["A rollback is performed successfully in a rehearsal",
         "The service owner can operate the new system from the runbook alone"],
        Severity.MEDIUM,
        EffortLevel.MODERATE,
    )

    ordered: list[MigrationPhase] = []
    for position, phase in enumerate(sorted(phases, key=lambda item: (item.index, item.id)), start=1):
        phase.index = position
        ordered.append(phase)
    return ordered


__all__ = ["MigrationPlanner", "CHANGE_RULES", "PlannedChange"]
