"""Architecture generation stage.

Builds two views from one set of logical components and one suitability verdict:

* **conventional** — a plausible as-is design: resident servers, self-managed
  rails, no security hardening assumed beyond what the user actually stated.
* **proposed** — the recommended design, where every component is realized
  according to its own scored recommendation (function, container, managed
  service, VM or retain-as-is).  This is what makes hybrid advice possible.

Both views are the same graph type, are validated by Pydantic, carry their own
trust boundaries and layout, and are the only source used by the canvas, the
mapping table, the security analyzer and the exported report.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rules.architecture_layout import layout_components
from app.schemas.architecture import (
    ArchitectureGraph,
    Component,
    ComponentTraits,
    Connection,
    MappingRow,
    SecurityEvidence,
    TrustBoundary,
)
from app.schemas.common import (
    ArchitectureStyle,
    BackupPolicy,
    CloudProvider,
    ComponentRuntime,
    ComponentTier,
    ConnectionKind,
    DataClassification,
    DeploymentTarget,
    DurationProfile,
    IamScope,
    LogicalComponentType,
    TransportSecurity,
)
from app.schemas.reports import ComponentSuitability, SuitabilityReport, WorkloadProfile
from app.schemas.architecture import ComponentPlan
from app.services.cloud_catalog import get_catalog

MAX_NODES_DEFAULT = 14

#: Only these realizations may be labeled "function" / "container" / "VM": everything
#: else is absorbed by a managed service by definition, so it is not scored as a
#: serverless-function candidate.
COMPUTE_TYPES = {
    LogicalComponentType.FUNCTION,
    LogicalComponentType.APP_SERVER,
    LogicalComponentType.WEB_SERVER,
    LogicalComponentType.CONTAINER_SERVICE,
    LogicalComponentType.WORKER,
    LogicalComponentType.BATCH_JOB,
    LogicalComponentType.REPORTING,
    LogicalComponentType.ML_INFERENCE,
    LogicalComponentType.VIRTUAL_MACHINE,
}

SERVERFUL_TYPES = COMPUTE_TYPES | {LogicalComponentType.LOAD_BALANCER}

BOUNDARY_DEFS: list[tuple[str, str, set[ComponentTier], str]] = [
    (
        "boundary-public",
        "Public edge",
        {ComponentTier.EDGE},
        "Anything reachable directly from the internet. Assume hostile input here.",
    ),
    (
        "boundary-application",
        "Application boundary",
        {ComponentTier.PRESENTATION, ComponentTier.APPLICATION, ComponentTier.PROCESSING},
        "Request handling and background execution. Reached only through the edge.",
    ),
    (
        "boundary-data",
        "Data boundary",
        {ComponentTier.DATA},
        "Stateful stores. Must never be reachable from the public edge.",
    ),
    (
        "boundary-security",
        "Identity & secrets",
        {ComponentTier.SECURITY},
        "Credential and token material with independent access control.",
    ),
    (
        "boundary-operations",
        "Operations",
        {ComponentTier.OPERATIONS},
        "Telemetry and delivery rails, writable by the other boundaries.",
    ),
]


@dataclass(frozen=True)
class Realization:
    type: LogicalComponentType
    label: str
    description: str
    traits: ComponentTraits
    security: SecurityEvidence
    properties: dict[str, object]
    notes: list[str]
    deployment_target: DeploymentTarget = DeploymentTarget.MANAGED_SERVICE


def _t(**kwargs: object) -> ComponentTraits:
    return ComponentTraits(**kwargs)  # type: ignore[arg-type]


def _s(**kwargs: object) -> SecurityEvidence:
    return SecurityEvidence(**kwargs)  # type: ignore[arg-type]


class ArchitectureEngine:
    """Turns (plans, suitability, workload) into validated architecture graphs."""

    def build(
        self,
        plans: list[ComponentPlan],
        suitability: SuitabilityReport,
        workload: WorkloadProfile,
        *,
        providers: list[CloudProvider],
        max_nodes: int = MAX_NODES_DEFAULT,
        sensitive: bool = False,
        persistent_connections: bool = False,
        object_event_driven: bool = False,
    ) -> list[ArchitectureGraph]:
        by_component = {item.component_id: item for item in suitability.components}
        conventional = self._build_view(
            ArchitectureStyle.CONVENTIONAL,
            plans,
            providers=providers,
            max_nodes=max_nodes,
        )
        proposed = self._build_view(
            _proposed_style(suitability),
            plans,
            providers=providers,
            max_nodes=max_nodes,
            by_component=by_component,
            outcome=suitability.outcome.value,
            pattern=suitability.recommended_pattern.value,
            sensitive=sensitive,
            persistent_connections=persistent_connections,
            object_event_driven=object_event_driven,
        )
        proposed.title = self._proposed_title(suitability)
        proposed.summary = self._proposed_summary(suitability, workload, proposed)
        conventional.summary = (
            "A plausible conventional baseline built from the same requirements: resident application servers "
            "behind a load balancer, self-managed rails, and a always-on database. It is a comparison point, not a "
            "recommendation."
        )
        return [conventional, proposed]

    @staticmethod
    def _proposed_title(suitability: SuitabilityReport) -> str:
        from app.schemas.common import RecommendedPattern

        if suitability.recommended_pattern in {RecommendedPattern.HYBRID, RecommendedPattern.MANAGED_CONTAINER}:
            return "Proposed hybrid cloud-native architecture"
        if suitability.outcome.value == "further_assessment_required":
            return "Proposed architecture (provisional — pending open questions)"
        return "Proposed serverless architecture"

    @staticmethod
    def _proposed_summary(suitability: SuitabilityReport, workload: WorkloadProfile, graph: ArchitectureGraph) -> str:
        functions = sum(1 for item in graph.components if item.type == LogicalComponentType.FUNCTION)
        resident = sum(
            1
            for item in graph.components
            if item.deployment_target in {DeploymentTarget.CONTAINER, DeploymentTarget.VIRTUAL_MACHINE}
        )
        parts = [
            f"{len(graph.components)} components, {functions} function-shaped and {resident} placed on a "
            f"resident runtime. Workload class: {workload.classification.replace('_', ' ')}."
        ]
        parts.append(suitability.rationale)
        return " ".join(parts)

    # ------------------------------------------------------------------- views

    def _build_view(
        self,
        style: ArchitectureStyle,
        plans: list[ComponentPlan],
        *,
        providers: list[CloudProvider],
        max_nodes: int,
        by_component: dict[str, ComponentSuitability] | None = None,
        outcome: str = "",
        pattern: str = "",
        sensitive: bool = False,
        persistent_connections: bool = False,
        object_event_driven: bool = False,
    ) -> ArchitectureGraph:
        proposed = style != ArchitectureStyle.CONVENTIONAL
        realizations: list[tuple[ComponentPlan, Realization]] = []
        for plan in plans:
            verdict = by_component.get(plan.id or plan.type.value) if by_component else None
            realization = (
                self._realize_proposed(plan, verdict, sensitive=sensitive, object_event_driven=object_event_driven)
                if proposed
                else self._realize_conventional(plan, sensitive=sensitive, persistent=persistent_connections)
            )
            if realization is None:
                continue
            if proposed:
                if verdict is not None and realization.type in COMPUTE_TYPES:
                    realization = _replace_target(realization, verdict.recommendation)
                else:
                    realization = _replace_target(realization, DeploymentTarget.MANAGED_SERVICE)
            else:
                realization = _replace_target(
                    realization,
                    DeploymentTarget.VIRTUAL_MACHINE
                    if realization.type in SERVERFUL_TYPES
                    else DeploymentTarget.RETAIN_AS_IS,
                )
            realizations.append((plan, realization))

        realizations, omitted = _cap_nodes(realizations, max_nodes)

        components: list[Component] = []
        for plan, realization in realizations:
            component_id = _component_id(plan, realization, proposed)
            mappings = {}
            catalog = get_catalog()
            for provider in providers:
                mapping = catalog.mapping_for(realization.type, provider)
                if mapping is not None:
                    mappings[provider.value] = mapping
            traits = realization.traits
            if not proposed and plan.traits.stateful:
                traits = traits.model_copy(update={"stateful": True})
            components.append(
                Component(
                    id=component_id,
                    label=realization.label,
                    type=realization.type,
                    tier=_tier(realization.type),
                    description=realization.description or plan.description,
                    deployment_target=realization.deployment_target,
                    traits=traits,
                    properties={**plan.properties, **realization.properties},
                    security=realization.security,
                    assumptions=list(plan.assumptions),
                    warnings=list(dict.fromkeys(plan.warnings + realization.notes)),
                    mappings=mappings,
                )
            )

        if omitted:
            components.append(
                Component(
                    id="ops-rails",
                    label=f"{len(omitted)} supporting component(s) consolidated",
                    type=LogicalComponentType.MONITORING,
                    tier=ComponentTier.OPERATIONS,
                    description=(
                        "Operational and secondary components grouped into one node to keep the diagram legible: "
                        + ", ".join(item[0].label or item[0].type.value for item in omitted)
                        + ". They remain part of the analysis and the report."
                    ),
                    deployment_target=DeploymentTarget.MANAGED_SERVICE,
                    traits=_t(runtime=ComponentRuntime.MANAGED, stateful=False, always_on=False),
                    properties={"Consolidated for legibility": ", ".join(item[0].id or item[0].type.value for item in omitted)},
                    warnings=["Shown as one node only to keep the view readable; the analysis covers each of them."],
                )
            )

        connections, inferred_links = _connect(
            components,
            proposed=proposed,
            persistent=persistent_connections,
            event_driven=object_event_driven,
        )
        boundaries = _boundaries(components)
        positions = layout_components(components)
        caveats: list[str] = []
        if omitted:
            caveats.append(
                f"{len(omitted)} lower-priority component(s) were consolidated into one node so the diagram stays "
                "readable; the analysis and report still include them."
            )
        if proposed and outcome == "further_assessment_required":
            caveats.append(
                "This proposed view is provisional: several deciding factors had no evidence, so treat it as a "
                "starting point for the open questions rather than a chosen design."
            )
        if proposed and "hybrid" in pattern:
            caveats.append(
                "Hybrid by intent: at least one component is deliberately not a function, and the reason is recorded "
                "on that node."
            )
        if inferred_links:
            caveats.append(
                "The description did not say how "
                + ", ".join(sorted(inferred_links))
                + " connects, so it is attached to the nearest plausible integration point. Verify before building."
            )
        caveats.append("Diagram is a conceptual blueprint. It is not deployed, provisioned or validated against any account.")

        graph = ArchitectureGraph(
            id="proposed" if proposed else "conventional",
            style=style,
            title="Proposed cloud-native architecture" if proposed else "Conventional architecture",
            components=components,
            connections=connections,
            trust_boundaries=boundaries,
            layout=positions,
            caveats=caveats,
        )
        return graph

    # ------------------------------------------------------------- realizations

    def _realize_conventional(self, plan: ComponentPlan, *, sensitive: bool, persistent: bool) -> Realization | None:
        """A believable as-is design: resident compute, self-managed rails."""
        base = plan.traits
        kind = plan.type
        if kind in {LogicalComponentType.CLIENT_WEB, LogicalComponentType.CLIENT_MOBILE}:
            return Realization(
                type=kind,
                label=plan.label or "Client application",
                description=plan.description,
                traits=_t(runtime=ComponentRuntime.STATIC, stateful=False),
                security=_s(publicly_reachable=True, transport_security=TransportSecurity.UNSPECIFIED,
                            data_classification=DataClassification.PUBLIC),
                properties={"Served from": "the same web tier (no edge cache)"},
                notes=[],
            )
        if kind == LogicalComponentType.CDN:
            return Realization(
                type=LogicalComponentType.WEB_SERVER,
                label="Web server (static assets + reverse proxy)",
                description=(
                    "Static assets are served by the application tier itself, so every visitor reaches the "
                    "origin and no caching happens at the edge."
                ),
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=False, always_on=True,
                          duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=True, transport_security=TransportSecurity.UNSPECIFIED,
                            data_classification=DataClassification.PUBLIC, iam_scope=IamScope.UNSPECIFIED),
                properties={"Scale unit": "one or two VMs", "TLS": "terminates here (not stated as enforced)"},
                notes=["No edge caching: origin load and bandwidth scale with every visitor."],
            )
        if kind == LogicalComponentType.API_GATEWAY:
            return Realization(
                type=LogicalComponentType.LOAD_BALANCER,
                label="Load balancer (entry point)",
                description="Layer-7 distribution to the application servers; routing and policy live in web-server config.",
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=False, always_on=True,
                          duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=True, transport_security=TransportSecurity.UNSPECIFIED,
                            data_classification=DataClassification.PUBLIC),
                properties={"Request limits": "provisioned capacity", "Policies": "configured in the web tier"},
                notes=["Authorization and throttling are enforced by application code rather than at the edge."],
            )
        if kind == LogicalComponentType.AUTH_IDENTITY:
            return Realization(
                type=LogicalComponentType.AUTH_IDENTITY,
                label="Identity handled inside the application",
                description=(
                    "Credentials and sessions are implemented in the application against its own user table, "
                    "which makes credential handling, password policy and session revocation an in-house duty."
                ),
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            authentication_scheme="application-managed sessions",
                            transport_security=TransportSecurity.UNSPECIFIED,
                            data_classification=DataClassification.RESTRICTED,
                            encryption_at_rest=None, iam_scope=IamScope.UNSPECIFIED),
                properties={"Session": "server-side", "MFA": "not stated"},
                notes=["Self-managed credential storage is a standing liability, not a one-off task."],
            )
        if kind == LogicalComponentType.APP_SERVER:
            return Realization(
                type=LogicalComponentType.APP_SERVER,
                label=plan.label or "Application servers (monolith)",
                description=(
                    "One resident runtime owning every synchronous use case. It is scaled by adding copies of "
                    "the whole application, so capacity is chosen for the peak and paid for around the clock."
                ),
                traits=_t(
                    runtime=ComponentRuntime.ALWAYS_ON,
                    stateful=base.stateful or persistent,
                    always_on=True,
                    persistent_connections=persistent,
                    duration=DurationProfile.INDEFINITE,
                    data_intensity=base.data_intensity,
                ),
                security=_s(
                    publicly_reachable=False,
                    requires_authentication=True,
                    transport_security=TransportSecurity.UNSPECIFIED,
                    data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                    iam_scope=IamScope.UNSPECIFIED,
                    secrets_handling="environment variables",
                    input_validation="unspecified",
                    audit_logging=None,
                ),
                properties={"Instances": "sized for peak", "Deploy": "whole application at a time"},
                notes=[],
            )
        if kind == LogicalComponentType.CONTAINER_SERVICE:
            return Realization(
                type=LogicalComponentType.APP_SERVER,
                label="Connection handler on the application tier",
                description="Long-lived sockets are held by a dedicated process on the same hosts, so restarts drop connections.",
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          persistent_connections=True, duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=True, requires_authentication=True,
                            transport_security=TransportSecurity.UNSPECIFIED),
                properties={"Restart behaviour": "clients must reconnect"},
                notes=["Deployments disconnect live clients unless handled explicitly."],
            )
        if kind == LogicalComponentType.QUEUE:
            return Realization(
                type=LogicalComponentType.VIRTUAL_MACHINE,
                label="Self-managed message broker host",
                description="A broker the team installs, patches, backs up and keeps available; queue durability is an in-house task.",
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True, custom_runtime=True,
                          duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            transport_security=TransportSecurity.UNSPECIFIED, iam_scope=IamScope.UNSPECIFIED,
                            data_classification=DataClassification.INTERNAL, backup_policy=BackupPolicy.UNSPECIFIED),
                properties={"Ops duty": "patching, clustering, disk headroom"},
                notes=[],
            )
        if kind in {LogicalComponentType.WORKER, LogicalComponentType.REPORTING, LogicalComponentType.ML_INFERENCE,
                    LogicalComponentType.BATCH_JOB}:
            return Realization(
                type=LogicalComponentType.VIRTUAL_MACHINE,
                label="Background worker host",
                description=(
                    "A standing VM polling for jobs. It is sized for worst-case backlog and idles between runs, "
                    "which is where the cost of the conventional design concentrates."
                ),
                traits=_t(
                    runtime=ComponentRuntime.ALWAYS_ON,
                    stateful=False,
                    always_on=True,
                    duration=base.duration if base.duration != DurationProfile.UNSPECIFIED else DurationProfile.MINUTES,
                    cpu_or_memory_intensive=base.cpu_or_memory_intensive,
                    gpu_required=base.gpu_required,
                    custom_runtime=base.custom_runtime,
                    needs_local_filesystem=True,
                ),
                security=_s(publicly_reachable=False, requires_authentication=True, iam_scope=IamScope.UNSPECIFIED,
                            secrets_handling="config file on the host",
                            data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL),
                properties={"Concurrency": "fixed pool", "Backlog": "grows when the host is saturated"},
                notes=["Idle capacity between runs is still billed."],
            )
        if kind == LogicalComponentType.SCHEDULER:
            return Realization(
                type=LogicalComponentType.SCHEDULER,
                label="cron on the application host",
                description="Periodic jobs run as cron entries on a server the team maintains, with no retry or dead-letter path.",
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=False, always_on=True,
                          duration=DurationProfile.FEW_SECONDS),
                security=_s(publicly_reachable=False, requires_authentication=True, iam_scope=IamScope.UNSPECIFIED,
                            data_classification=DataClassification.INTERNAL),
                properties={"Failure handling": "manual", "Drift": "depends on host clock"},
                notes=[],
            )
        if kind == LogicalComponentType.DATA_STREAM:
            return Realization(
                type=LogicalComponentType.VIRTUAL_MACHINE,
                label="Stream consumer host",
                description="A resident consumer process per partition with in-house offset management and replay storage.",
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          persistent_connections=True, duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=False, requires_authentication=True, transport_security=TransportSecurity.UNSPECIFIED),
                properties={"Replay": "retention window configured by the team"},
                notes=[],
            )
        if kind in {LogicalComponentType.RELATIONAL_DB, LogicalComponentType.DOCUMENT_DB, LogicalComponentType.KEY_VALUE_DB}:
            return Realization(
                type=kind,
                label=(plan.label or "Primary store") + " (self-managed instance)",
                description=(
                    "A database on a provisioned instance: sizing, maintenance windows, failover and backup "
                    "scripts are the team's responsibility. Capacity is chosen for the exam-sale peak, not the average."
                ),
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          duration=DurationProfile.INDEFINITE,
                          connection_pool_pressure=base.connection_pool_pressure),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            transport_security=TransportSecurity.UNSPECIFIED,
                            data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                            encryption_at_rest=None, iam_scope=IamScope.UNSPECIFIED,
                            backup_policy=BackupPolicy.MANUAL),
                properties={"Connections": "fixed by instance size", "Failover": "manual unless engineered"},
                notes=[],
            )
        if kind == LogicalComponentType.CACHE:
            return Realization(
                type=LogicalComponentType.CACHE,
                label="In-process cache / session memory",
                description="Cache and session data live in the application process, which is what makes the tier stateful.",
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=False, requires_authentication=False,
                            data_classification=DataClassification.INTERNAL, encryption_at_rest=None),
                properties={"Shared across instances": "no"},
                notes=["Prevents adding or removing servers without losing sessions."],
            )
        if kind == LogicalComponentType.OBJECT_STORAGE:
            return Realization(
                type=LogicalComponentType.BLOCK_STORAGE,
                label="Uploaded files on the server disk",
                description=(
                    "Uploads and generated documents are written to a directory on the application host, which "
                    "couples storage growth to that one machine."
                ),
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          needs_local_filesystem=True, duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=None, requires_authentication=True,
                            data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                            encryption_at_rest=None, iam_scope=IamScope.UNSPECIFIED, backup_policy=BackupPolicy.UNSPECIFIED),
                properties={"Growth": "bounded by the volume size", "Sharing": "not reachable from other hosts"},
                notes=["Disk growth eventually blocks the application, not just storage."],
            )
        if kind == LogicalComponentType.SEARCH_INDEX:
            return Realization(
                type=LogicalComponentType.SEARCH_INDEX,
                label="Search engine on the application host",
                description="A search process co-located with the application, indexed synchronously inside requests.",
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=False, requires_authentication=True, iam_scope=IamScope.UNSPECIFIED),
                properties={"Index write": "inline with user requests"},
                notes=[],
            )
        if kind == LogicalComponentType.DATA_WAREHOUSE:
            return None
        if kind == LogicalComponentType.NOTIFICATION:
            return Realization(
                type=LogicalComponentType.NOTIFICATION,
                label="SMTP relay from the application host",
                description="Notifications are sent synchronously inside the request with a provider key in the app config.",
                traits=_t(runtime=ComponentRuntime.REQUEST_RESPONSE, stateful=False, always_on=False,
                          duration=DurationProfile.FEW_SECONDS),
                security=_s(publicly_reachable=False, requires_authentication=True, secrets_handling="app config",
                            data_classification=DataClassification.INTERNAL),
                properties={"Retries": "none beyond the SMTP client"},
                notes=["A slow provider directly delays the user-visible response."],
            )
        if kind == LogicalComponentType.BACKUP:
            return Realization(
                type=LogicalComponentType.BACKUP,
                label="Ad-hoc file backup",
                description="No backup or recovery capability is identified in the described design beyond occasional manual copies.",
                traits=_t(runtime=ComponentRuntime.SCHEDULED_BATCH, stateful=True, always_on=False),
                security=_s(publicly_reachable=None, requires_authentication=None, backup_policy=BackupPolicy.NONE,
                            data_classification=DataClassification.UNSPECIFIED, encryption_at_rest=None),
                properties={"Restore tested": "no"},
                notes=[],
            )
        if kind in {LogicalComponentType.MONITORING, LogicalComponentType.LOGGING}:
            return Realization(
                type=LogicalComponentType.LOGGING,
                label="Log files on each host",
                description="Logs stay on the machines that produced them; there is no central query path or alerting rail.",
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=False, always_on=True,
                          duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=False, requires_authentication=True, audit_logging=False,
                            data_classification=DataClassification.INTERNAL),
                properties={"Retention": "until the disk fills", "Alerting": "manual"},
                notes=[],
            )
        if kind == LogicalComponentType.BLOCK_STORAGE:
            return Realization(
                type=kind,
                label=plan.label or "Shared volume",
                description=plan.description,
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          needs_local_filesystem=True, duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=None, requires_authentication=True, iam_scope=IamScope.UNSPECIFIED,
                            data_classification=DataClassification.INTERNAL, backup_policy=BackupPolicy.UNSPECIFIED),
                properties=dict(plan.properties),
                notes=list(plan.warnings),
            )
    # ------------------------------------------------------- proposed (serverless)

    def _realize_proposed(
        self,
        plan: ComponentPlan,
        verdict: ComponentSuitability | None,
        *,
        sensitive: bool,
        object_event_driven: bool,
    ) -> Realization | None:
        target = verdict.recommendation if verdict else DeploymentTarget.MANAGED_SERVICE
        kind = plan.type
        score = verdict.score if verdict else None

        if kind in {LogicalComponentType.CLIENT_WEB, LogicalComponentType.CLIENT_MOBILE}:
            return Realization(
                type=kind,
                label=plan.label or "Client application",
                description=plan.description,
                traits=_t(runtime=ComponentRuntime.STATIC, stateful=False),
                security=_s(publicly_reachable=True, transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.PUBLIC),
                properties={"Build": "static bundle published by CI", "Hosting": "object storage + edge network"},
                notes=[],
            )
        if kind == LogicalComponentType.CDN:
            return Realization(
                type=LogicalComponentType.CDN,
                label="Edge delivery with TLS enforced",
                description=(
                    "Client assets and cacheable responses are served from the provider edge, so most visitors "
                    "never reach compute. Only authenticated API traffic is proxied through."
                ),
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=False, always_on=False),
                security=_s(publicly_reachable=True, transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.PUBLIC, iam_scope=IamScope.SCOPED),
                properties={"TLS": "enforced, HTTP redirected", "Cache": "asset and public read paths"},
                notes=[],
            )
        if kind == LogicalComponentType.API_GATEWAY:
            return Realization(
                type=LogicalComponentType.API_GATEWAY,
                label="Managed API surface (routes, auth, throttling)",
                description=(
                    "Declarative routes with authorization at the edge, per-route throttling, request schema "
                    "validation and a versioned contract, so cross-cutting rules stop being duplicated in handlers."
                ),
                traits=_t(runtime=ComponentRuntime.REQUEST_RESPONSE, stateful=False, always_on=False,
                          duration=DurationProfile.SUB_SECOND),
                security=_s(publicly_reachable=True, requires_authentication=True,
                            authentication_scheme="token validation at the gateway",
                            transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.INTERNAL, iam_scope=IamScope.SCOPED,
                            input_validation="request schema validation enabled"),
                properties={"Authorization": "verified before any handler runs", "Timeout": "platform cap; long work is queued"},
                notes=[],
            )
        if kind == LogicalComponentType.AUTH_IDENTITY:
            return Realization(
                type=kind,
                label="Managed identity provider",
                description=(
                    "User pool, token issuance, password policy and role claims provided by a managed identity "
                    "service; the application never stores credentials or implements reset flows."
                ),
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False,
                          duration=DurationProfile.UNSPECIFIED),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            authentication_scheme="managed OIDC tokens", transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.RESTRICTED, encryption_at_rest=True,
                            iam_scope=IamScope.SCOPED, audit_logging=True),
                properties={"Tokens": "short-lived, verified at the gateway", "MFA": "policy configurable, verify per tenant"},
                notes=[],
            )
        if kind == LogicalComponentType.APP_SERVER:
            if target == DeploymentTarget.SERVERLESS_FUNCTION:
                return Realization(
                    type=LogicalComponentType.FUNCTION,
                    label="Function handlers per use case",
                    description=(
                        "Each use case becomes a small, stateless handler triggered through the API surface. "
                        "Instances start on demand, so capacity tracks the traffic curve instead of the worst case."
                    ),
                    traits=_t(
                        runtime=ComponentRuntime.REQUEST_RESPONSE,
                        stateful=False,
                        always_on=False,
                        duration=plan.traits.duration if plan.traits.duration != DurationProfile.UNSPECIFIED
                        else DurationProfile.SUB_SECOND,
                        estimated_duration_ms=plan.traits.estimated_duration_ms,
                        data_intensity=plan.traits.data_intensity,
                    ),
                    security=_s(publicly_reachable=False, requires_authentication=True,
                                authentication_scheme="gateway-verified token",
                                transport_security=TransportSecurity.TLS_ENFORCED,
                                data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                                iam_scope=IamScope.SCOPED, secrets_handling="managed secret store + workload identity",
                                input_validation="schema validation at the gateway",
                                encryption_at_rest=True, audit_logging=True),
                    properties={
                        "State": "externalised to cache/data store",
                        "Scale": "0 to platform concurrency limit",
                        "Suitability score": f"{score:.0f}/100" if score is not None else "n/a",
                    },
                    notes=(
                        []
                        if not plan.traits.stateful
                        else ["Session state moved to the cache/token so handlers stay stateless."]
                    ),
                )
            return Realization(
                type=LogicalComponentType.CONTAINER_SERVICE,
                label="Container service for the request path",
                description=(
                    "The synchronous tier stays on a container platform (scaling to zero when supported) because "
                    "its runtime or coupling constraints make a function rewrite the more expensive option."
                ),
                traits=_t(runtime=ComponentRuntime.REQUEST_RESPONSE, stateful=False, always_on=False,
                          duration=plan.traits.duration, custom_runtime=plan.traits.custom_runtime,
                          cpu_or_memory_intensive=plan.traits.cpu_or_memory_intensive),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                            iam_scope=IamScope.SCOPED, secrets_handling="managed secret store",
                            encryption_at_rest=True),
                properties={"Scaling": "per-request concurrency limits", "Suitability score": f"{score:.0f}/100" if score is not None else "n/a"},
                notes=[verdict.recommendation_reason] if verdict and verdict.recommendation_reason else [],
            )
        if kind == LogicalComponentType.CONTAINER_SERVICE:
            return Realization(
                type=kind,
                label="Resident real-time connection service",
                description=(
                    "A deliberately non-serverless node: it holds client sockets, subscribes to update events and "
                    "fans them out. Functions stay behind it for the logic."
                ),
                traits=_t(runtime=ComponentRuntime.ALWAYS_ON, stateful=True, always_on=True,
                          persistent_connections=True, duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=True, requires_authentication=True,
                            authentication_scheme="token checked at handshake",
                            transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.INTERNAL, iam_scope=IamScope.SCOPED),
                properties={"Why not a function": "connections outlive an invocation", "State": "connection registry only"},
                notes=["Hybrid by design: this component stays resident and everything around it is event-driven."],
            )
        if kind == LogicalComponentType.QUEUE:
            return Realization(
                type=kind,
                label="Managed queue with dead-letter path",
                description=(
                    "Fully managed buffering between the request path and processing, with retries, a visible "
                    "depth metric and a dead-letter destination so poison messages cannot loop forever."
                ),
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False, event_triggered=True),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.INTERNAL, iam_scope=IamScope.SCOPED),
                properties={"Delivery": "at-least-once (idempotent consumers)", "Max receive attempts": "set explicitly"},
                notes=[],
            )
        if kind in {LogicalComponentType.WORKER, LogicalComponentType.REPORTING, LogicalComponentType.ML_INFERENCE}:
            if target == DeploymentTarget.SERVERLESS_FUNCTION:
                return Realization(
                    type=LogicalComponentType.FUNCTION,
                    label=plan.label or "Async functions",
                    description=(
                        "Queue- and storage-event-triggered functions: each unit of work runs in its own "
                        "invocation, so a burst of submissions or uploads becomes parallel executions instead "
                        "of a longer queue."
                    ),
                    traits=_t(runtime=ComponentRuntime.EVENT_TRIGGERED, stateful=False, always_on=False,
                              event_triggered=True,
                              duration=plan.traits.duration if plan.traits.duration != DurationProfile.UNSPECIFIED
                              else DurationProfile.FEW_SECONDS,
                              estimated_duration_ms=plan.traits.estimated_duration_ms),
                    security=_s(publicly_reachable=False, requires_authentication=True,
                                transport_security=TransportSecurity.TLS_ENFORCED,
                                data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                                iam_scope=IamScope.SCOPED, secrets_handling="managed secret store",
                                encryption_at_rest=True, audit_logging=True),
                    properties={"Trigger": "queue / object-created event", "Concurrency": "platform-managed",
                                "Suitability score": f"{score:.0f}/100" if score is not None else "n/a"},
                    notes=[],
                )
            if target == DeploymentTarget.CONTAINER:
                return Realization(
                    type=LogicalComponentType.BATCH_JOB,
                    label=plan.label or "Job runtime (deliberately not a function)",
                    description=(
                        "This work is placed on a job/container runtime rather than a function. "
                        + (verdict.recommendation_reason if verdict else "Its duration or dependencies exceed function budgets.")
                        + " Results are reported back through the queue, so the user experience stays asynchronous."
                    ),
                    traits=_t(
                        runtime=ComponentRuntime.LONG_RUNNING,
                        stateful=False,
                        always_on=False,
                        duration=plan.traits.duration,
                        cpu_or_memory_intensive=plan.traits.cpu_or_memory_intensive,
                        gpu_required=plan.traits.gpu_required,
                        custom_runtime=plan.traits.custom_runtime,
                        needs_local_filesystem=plan.traits.needs_local_filesystem,
                        estimated_duration_ms=plan.traits.estimated_duration_ms,
                    ),
                    security=_s(publicly_reachable=False, requires_authentication=True,
                                transport_security=TransportSecurity.TLS_ENFORCED,
                                data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                                iam_scope=IamScope.SCOPED, secrets_handling="managed secret store",
                                encryption_at_rest=True),
                    properties={"Why here instead of a function": "duration / runtime constraints",
                                "Sizing": "per job, released when the job finishes",
                                "Suitability score": f"{score:.0f}/100" if score is not None else "n/a"},
                    notes=[
                        "Forcing this into a short-lived function would trade a working design for timeouts; "
                        "the surrounding orchestration still stays event-driven."
                    ],
                )
            return Realization(
                type=LogicalComponentType.CONTAINER_SERVICE,
                label=plan.label or "Containerized processing service",
                description=plan.description,
                traits=_t(runtime=ComponentRuntime.LONG_RUNNING, stateful=False, always_on=False,
                          cpu_or_memory_intensive=plan.traits.cpu_or_memory_intensive,
                          gpu_required=plan.traits.gpu_required, custom_runtime=plan.traits.custom_runtime,
                          duration=plan.traits.duration),
                security=_s(publicly_reachable=False, requires_authentication=True, iam_scope=IamScope.SCOPED,
                            transport_security=TransportSecurity.TLS_ENFORCED, encryption_at_rest=True,
                            secrets_handling="managed secret store",
                            data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL),
                properties={"Suitability score": f"{score:.0f}/100" if score is not None else "n/a"},
                notes=[verdict.recommendation_reason] if verdict else [],
            )
        if kind == LogicalComponentType.SCHEDULER:
            return Realization(
                type=LogicalComponentType.SCHEDULER,
                label="Managed schedule → function invocation",
                description="Cron-style triggers are declared on the platform and invoke handlers directly, so no host waits for the next minute.",
                traits=_t(runtime=ComponentRuntime.SCHEDULED_BATCH, stateful=False, always_on=False,
                          event_triggered=True, duration=DurationProfile.FEW_SECONDS),
                security=_s(publicly_reachable=False, requires_authentication=True, iam_scope=IamScope.SCOPED,
                            transport_security=TransportSecurity.TLS_ENFORCED, data_classification=DataClassification.INTERNAL),
                properties={"Failure": "retried by the platform; alert on consecutive failures",
                            "Idempotency": "required"},
                notes=[],
            )
        if kind == LogicalComponentType.DATA_STREAM:
            return Realization(
                type=kind,
                label="Managed stream ingestion",
                description=(
                    "A managed ingest path with retention and ordering per key; consumers are functions or a "
                    "small resident worker sized to the ingest rate rather than to peak provisioning."
                ),
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False,
                          persistent_connections=True, duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.INTERNAL, iam_scope=IamScope.SCOPED),
                properties={"Ordering": "per key", "Backpressure": "absorbed by retention"},
                notes=["Consumer side may still need a resident worker; that is a deliberate hybrid choice."],
            )
        if kind in {LogicalComponentType.RELATIONAL_DB, LogicalComponentType.DOCUMENT_DB, LogicalComponentType.KEY_VALUE_DB,
                    LogicalComponentType.CACHE, LogicalComponentType.SEARCH_INDEX, LogicalComponentType.TIME_SERIES_DB,
                    LogicalComponentType.DATA_WAREHOUSE}:
            return Realization(
                type=kind,
                label=(plan.label or "Data store") + " (managed, autoscaling)",
                description=(
                    "Kept as a stateful managed service — serverless compute does not make databases "
                    "stateless. Autoscaling or serverless capacity absorbs the peak; access stays private."
                ),
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False,
                          duration=DurationProfile.INDEFINITE,
                          connection_pool_pressure=plan.traits.connection_pool_pressure),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                            encryption_at_rest=True, iam_scope=IamScope.SCOPED,
                            backup_policy=BackupPolicy.AUTOMATED),
                properties={
                    "Public access": "none; private network only",
                    "Connection strategy": "pooler/proxy required at high concurrency"
                    if plan.traits.connection_pool_pressure
                    else "within typical connection budget",
                    "Backups": "automated snapshots with PITR where the service supports it",
                },
                notes=(
                    ["Function concurrency must be capped or fronted by a pooler, otherwise scale-out exhausts "
                     "database connections before it exhausts the platform."]
                    if plan.traits.connection_pool_pressure
                    else []
                ),
            )
        if kind == LogicalComponentType.OBJECT_STORAGE:
            return Realization(
                type=kind,
                label="Object storage (private) with event triggers",
                description=(
                    "Uploads go to a private bucket accessed through signed URLs; object-created events start "
                    "processing, so the request path never waits for a job."
                ),
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False,
                          event_triggered=object_event_driven),
                security=_s(publicly_reachable=False, requires_authentication=True,
                            transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.CONFIDENTIAL if sensitive else DataClassification.INTERNAL,
                            encryption_at_rest=True, iam_scope=IamScope.SCOPED, backup_policy=BackupPolicy.AUTOMATED),
                properties={"Public access": "blocked; signed URLs with expiry", "Lifecycle": "transition and expire rules",
                            "Events": "object-created → processing"},
                notes=[],
            )
        if kind == LogicalComponentType.BLOCK_STORAGE:
            return Realization(
                type=LogicalComponentType.BLOCK_STORAGE,
                label="File share attached to the container runtime",
                description=(
                    "The stated filesystem semantics are honoured by a network file share mounted on the "
                    "container/batch runtime only. Everything else uses object storage."
                ),
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=True,
                          needs_local_filesystem=True, duration=DurationProfile.INDEFINITE),
                security=_s(publicly_reachable=False, requires_authentication=True, iam_scope=IamScope.SCOPED,
                            transport_security=TransportSecurity.TLS_ENFORCED,
                            data_classification=DataClassification.INTERNAL, backup_policy=BackupPolicy.AUTOMATED),
                properties={"Scope": "only the components that truly need POSIX semantics"},
                notes=["Carrying a filesystem into a function-based design is the single most common migration mistake."],
            )
        if kind == LogicalComponentType.NOTIFICATION:
            return Realization(
                type=kind,
                label="Notification dispatch (async, managed channel)",
                description="Provider-backed delivery invoked from the queue consumer, with retries and a dead-letter path.",
                traits=_t(runtime=ComponentRuntime.EVENT_TRIGGERED, stateful=False, always_on=False,
                          event_triggered=True, duration=DurationProfile.FEW_SECONDS),
                security=_s(publicly_reachable=False, requires_authentication=True, secrets_handling="managed secret store",
                            iam_scope=IamScope.SCOPED, data_classification=DataClassification.INTERNAL,
                            transport_security=TransportSecurity.TLS_ENFORCED),
                properties={"Quotas": "provider limits recorded as an assumption"},
                notes=[],
            )
        if kind == LogicalComponentType.BACKUP:
            return Realization(
                type=kind,
                label="Automated backup & tested restore",
                description="Service-managed snapshots with retention and cross-region copies where required, plus a restore rehearsal.",
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=True, always_on=False),
                security=_s(publicly_reachable=False, requires_authentication=True, backup_policy=BackupPolicy.AUTOMATED,
                            encryption_at_rest=True, iam_scope=IamScope.SCOPED, data_classification=DataClassification.CONFIDENTIAL),
                properties={"Restore rehearsal": "schedule it; an untested backup is a hope", "Retention": "match the stated retention need"},
                notes=[],
            )
        if kind in {LogicalComponentType.MONITORING, LogicalComponentType.LOGGING}:
            return Realization(
                type=LogicalComponentType.MONITORING,
                label="Metrics, structured logs & alarms",
                description=(
                    "Platform metrics plus alarms on the paths a managed runtime hides: throttling, concurrent "
                    "execution limits, dead-letter depth, duration percentiles and cold-start share."
                ),
                traits=_t(runtime=ComponentRuntime.MANAGED, stateful=False, always_on=False),
                security=_s(publicly_reachable=False, requires_authentication=True, audit_logging=True,
                            data_classification=DataClassification.INTERNAL, iam_scope=IamScope.SCOPED),
                properties={"Dashboards": "per use case, not per server", "Log retention": "set explicitly"},
                notes=[],
            )
        return Realization(
            type=kind,
            label=plan.label or kind.value.replace("_", " ").title(),
            description=plan.description,
            traits=plan.traits,
            security=plan.security,
            properties=dict(plan.properties),
            notes=list(plan.warnings),
        )


# ---------------------------------------------------------------------------
# graph plumbing
# ---------------------------------------------------------------------------


def _replace_target(realization: Realization, target: DeploymentTarget) -> Realization:
    from dataclasses import replace

    return replace(realization, deployment_target=target)


def _tier(component_type: LogicalComponentType) -> ComponentTier:
    from app.services.component_identifier import TIER_BY_TYPE

    return TIER_BY_TYPE[component_type]


def _component_id(plan: ComponentPlan, realization: Realization, proposed: bool) -> str:
    base = plan.id or plan.type.value
    suffix = "fn" if proposed and realization.type == LogicalComponentType.FUNCTION else ""
    candidate = f"{base}{('-' + suffix) if suffix else ''}"
    return candidate.replace("_", "-").lower()


def _cap_nodes(
    realizations: list[tuple[ComponentPlan, Realization]], max_nodes: int
) -> tuple[list[tuple[ComponentPlan, Realization]], list[tuple[ComponentPlan, Realization]]]:
    if len(realizations) <= max_nodes:
        return realizations, []
    priority = {
        ComponentTier.EDGE: 0,
        ComponentTier.PRESENTATION: 1,
        ComponentTier.APPLICATION: 2,
        ComponentTier.PROCESSING: 3,
        ComponentTier.INTEGRATION: 4,
        ComponentTier.DATA: 5,
        ComponentTier.SECURITY: 6,
        ComponentTier.OPERATIONS: 9,
    }
    ranked = sorted(
        enumerate(realizations),
        key=lambda pair: (priority.get(_tier(pair[1][1].type), 5), pair[1][0].id or ""),
    )
    keep = sorted(pair[0] for pair in ranked[: max_nodes - 1])
    kept = [realizations[index] for index in keep]
    omitted = [item for index, item in enumerate(realizations) if index not in set(keep)]
    return kept, omitted


def _connect(
    components: list[Component],
    *,
    proposed: bool,
    persistent: bool,
    event_driven: bool,
) -> tuple[list[Connection], list[str]]:
    """Wire the view together.

    Returns the connections plus the ids of components that had to be attached to
    the nearest plausible integration point, so the caller can disclose that the
    edge is an inference rather than something the description stated.
    """
    by_type: dict[LogicalComponentType, list[Component]] = {}
    for component in components:
        by_type.setdefault(component.type, []).append(component)
    ids = {component.id for component in components}

    def first(*types: LogicalComponentType) -> str | None:
        for item in types:
            for component in by_type.get(item, []):
                return component.id
        return None

    connections: list[Connection] = []

    def link(
        source: str | None,
        target: str | None,
        kind: ConnectionKind,
        label: str,
        *,
        protocol: str | None = None,
        crosses: bool = False,
        optional: bool = False,
    ) -> None:
        if not source or not target or source not in ids or target not in ids or source == target:
            return
        connection_id = f"c-{source}-{target}-{kind.value}".replace("--", "-")[:58]
        if any(existing.id == connection_id for existing in connections):
            return
        connections.append(
            Connection(
                id=connection_id,
                source=source,
                target=target,
                kind=kind,
                label=label,
                protocol=protocol,
                crosses_trust_boundary=crosses,
                async_delivery=kind in {ConnectionKind.ASYNC_EVENT, ConnectionKind.STREAM, ConnectionKind.SCHEDULE},
                optional=optional,
            )
        )

    client = first(LogicalComponentType.CLIENT_WEB, LogicalComponentType.CLIENT_MOBILE)
    edge = first(LogicalComponentType.CDN, LogicalComponentType.WEB_SERVER, LogicalComponentType.LOAD_BALANCER)
    entry = first(LogicalComponentType.API_GATEWAY, LogicalComponentType.LOAD_BALANCER, LogicalComponentType.WEB_SERVER)
    identity = first(LogicalComponentType.AUTH_IDENTITY)
    compute = [
        component.id
        for component in components
        if component.type
        in {
            LogicalComponentType.FUNCTION,
            LogicalComponentType.APP_SERVER,
            LogicalComponentType.CONTAINER_SERVICE,
            LogicalComponentType.VIRTUAL_MACHINE,
        }
    ]
    primary = first(LogicalComponentType.RELATIONAL_DB)
    document = first(LogicalComponentType.DOCUMENT_DB, LogicalComponentType.KEY_VALUE_DB)
    cache = first(LogicalComponentType.CACHE)
    files = first(LogicalComponentType.OBJECT_STORAGE, LogicalComponentType.BLOCK_STORAGE)
    queue = first(LogicalComponentType.QUEUE, LogicalComponentType.PUBSUB)
    stream = first(LogicalComponentType.DATA_STREAM)
    jobs = first(LogicalComponentType.BATCH_JOB, LogicalComponentType.WORKER, LogicalComponentType.REPORTING)
    scheduler = first(LogicalComponentType.SCHEDULER)
    search = first(LogicalComponentType.SEARCH_INDEX)
    warehouse = first(LogicalComponentType.DATA_WAREHOUSE)
    notify = first(LogicalComponentType.NOTIFICATION)
    backup = first(LogicalComponentType.BACKUP)
    ops = first(LogicalComponentType.MONITORING, LogicalComponentType.LOGGING)

    link(client, edge, ConnectionKind.STATIC_ASSET, "loads assets", protocol="https", crosses=True)
    link(client, entry, ConnectionKind.SYNC_HTTP, "API calls", protocol="https", crosses=True)
    link(edge, entry, ConnectionKind.SYNC_HTTP, "proxied API traffic", protocol="https")
    link(entry, identity, ConnectionKind.SYNC_HTTP, "verifies token", protocol="oidc")
    for handler in compute:
        link(entry, handler, ConnectionKind.SYNC_HTTP, "invoke handler", protocol="https")
        link(handler, primary, ConnectionKind.DATA_WRITE, "reads/writes", protocol="sql")
        link(handler, cache, ConnectionKind.DATA_READ, "hot reads / sessions", protocol="resp", optional=True)
        link(handler, document, ConnectionKind.DATA_WRITE, "document reads/writes", optional=True)
        link(handler, queue, ConnectionKind.ASYNC_EVENT, "enqueue job", optional=True)
        link(handler, files, ConnectionKind.DATA_WRITE, "store artefact", optional=True)
        link(handler, search, ConnectionKind.DATA_WRITE, "query index", optional=True)
        link(handler, ops, ConnectionKind.MANAGEMENT, "metrics & logs", optional=True)

    link(queue, jobs, ConnectionKind.ASYNC_EVENT, "deliver work")
    link(stream, jobs, ConnectionKind.STREAM, "batched events", optional=True)
    link(files, jobs, ConnectionKind.ASYNC_EVENT, "object-created event", optional=True)
    link(jobs, primary, ConnectionKind.DATA_WRITE, "results", protocol="sql")
    link(jobs, files, ConnectionKind.DATA_WRITE, "artefacts")
    link(jobs, notify, ConnectionKind.ASYNC_EVENT, "dispatch", optional=True)
    link(queue, notify, ConnectionKind.ASYNC_EVENT, "dispatch", optional=True)
    link(scheduler, jobs, ConnectionKind.SCHEDULE, "trigger", optional=True)
    link(scheduler, compute[0] if compute else None, ConnectionKind.SCHEDULE, "timed invocation", optional=True)
    link(primary, warehouse, ConnectionKind.DATA_READ, "batch export", optional=True)
    link(primary, backup, ConnectionKind.DATA_WRITE, "snapshot", optional=True)
    link(files, backup, ConnectionKind.DATA_WRITE, "replicate", optional=True)
    if persistent:
        realtime = first(LogicalComponentType.CONTAINER_SERVICE)
        link(client, realtime, ConnectionKind.STREAM, "live updates", protocol="wss", crosses=True)
        link(realtime, queue, ConnectionKind.ASYNC_EVENT, "publish events", optional=True)
        link(jobs, realtime, ConnectionKind.ASYNC_EVENT, "push notification", optional=True)
    for component in components:
        if component.tier in {ComponentTier.DATA, ComponentTier.PROCESSING, ComponentTier.APPLICATION}:
            link(component.id, ops, ConnectionKind.MANAGEMENT, "telemetry", optional=True)

    # ---- last-mile: nothing in a diagram should float unattached -------------
    # An isolated node reads as a modelling mistake, so each auxiliary component
    # type gets its semantically correct host.  Anything still unattached is
    # linked to the entry point and reported as an inference in the view caveats.
    hub = entry or (compute[0] if compute else None)
    fallback: list[str] = []
    linked = {item.source for item in connections} | {item.target for item in connections}
    for component in components:
        if component.id in linked:
            continue
        kind = component.type
        if kind is LogicalComponentType.NOTIFICATION:
            link(hub, component.id, ConnectionKind.ASYNC_EVENT, "raises notification")
            link(component.id, client, ConnectionKind.ASYNC_EVENT, "delivers to user", crosses=True)
        elif kind is LogicalComponentType.DATA_STREAM:
            link(hub, component.id, ConnectionKind.STREAM, "publishes events")
            link(component.id, jobs or queue or primary, ConnectionKind.STREAM, "consumed by")
        elif kind is LogicalComponentType.SECRETS_MANAGER:
            link(hub, component.id, ConnectionKind.MANAGEMENT, "reads credentials", optional=True)
        elif kind in {LogicalComponentType.MONITORING, LogicalComponentType.LOGGING}:
            link(hub, component.id, ConnectionKind.MANAGEMENT, "telemetry")
        elif kind in {
            LogicalComponentType.CI_ARTIFACT_STORE,
            LogicalComponentType.SCHEDULER,
            LogicalComponentType.QUEUE,
            LogicalComponentType.PUBSUB,
        }:
            link(hub, component.id, ConnectionKind.ASYNC_EVENT, "publishes work")
        elif kind in {LogicalComponentType.BACKUP}:
            link(primary or files, component.id, ConnectionKind.DATA_WRITE, "snapshot")
        elif kind in {LogicalComponentType.OBJECT_STORAGE, LogicalComponentType.BLOCK_STORAGE}:
            link(hub, component.id, ConnectionKind.DATA_WRITE, "stores artefacts")
        elif kind in {
            LogicalComponentType.RELATIONAL_DB,
            LogicalComponentType.DOCUMENT_DB,
            LogicalComponentType.KEY_VALUE_DB,
            LogicalComponentType.CACHE,
            LogicalComponentType.SEARCH_INDEX,
            LogicalComponentType.DATA_WAREHOUSE,
            LogicalComponentType.TIME_SERIES_DB,
        }:
            link(hub, component.id, ConnectionKind.DATA_WRITE, "reads/writes", protocol="sql")
        else:
            link(hub, component.id, ConnectionKind.SYNC_HTTP, "called by the application tier")
            link(component.id, hub, ConnectionKind.SYNC_HTTP, "calls the application tier")
            fallback.append(component.id)
        linked = {item.source for item in connections} | {item.target for item in connections}
    return connections, fallback


def _boundaries(components: list[Component]) -> list[TrustBoundary]:
    boundaries: list[TrustBoundary] = []
    for boundary_id, label, tiers, note in BOUNDARY_DEFS:
        members = [component.id for component in components if component.tier in tiers]
        if not members:
            continue
        boundaries.append(TrustBoundary(id=boundary_id, label=label, component_ids=members, note=note))
    return boundaries


def build_mapping_rows(graph: ArchitectureGraph) -> list[MappingRow]:
    """Comparison rows: one per component, with the three provider realizations."""
    from app.services.cloud_catalog import MAPPINGS

    rows: list[MappingRow] = []
    for component in graph.components:
        spec = MAPPINGS.get(component.type)
        notes = _difference_notes(spec) if spec is not None else []
        if spec is not None and spec.equivalence != "near" and not notes:
            # A row that is not 1:1 must never be presented without saying why.
            notes = [
                f"Equivalence is {spec.equivalence}: the three products cover this role with different scope, "
                "so re-verify the fit before implementing."
            ]
        rows.append(
            MappingRow(
                component_id=component.id,
                component_label=component.label,
                logical_type=component.type,
                aws=component.mappings.get(CloudProvider.AWS.value),
                gcp=component.mappings.get(CloudProvider.GCP.value),
                azure=component.mappings.get(CloudProvider.AZURE.value),
                one_to_one=spec is not None and spec.equivalence == "near",
                notes=notes,
            )
        )
    return rows


def _difference_notes(spec: object) -> list[str]:
    differences = getattr(spec, "differences", None) or {}
    return [
        f"{provider.value.upper()}: {text}"
        for provider, text in sorted(differences.items(), key=lambda item: item[0].value)
    ]


def _proposed_style(suitability: SuitabilityReport) -> ArchitectureStyle:
    from app.schemas.common import RecommendedPattern

    if suitability.recommended_pattern in {RecommendedPattern.HYBRID, RecommendedPattern.MANAGED_CONTAINER}:
        return ArchitectureStyle.HYBRID
    return ArchitectureStyle.SERVERLESS
