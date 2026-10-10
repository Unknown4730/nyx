"""Architecture-level security analysis.

Scope, stated in the report itself: this inspects the *model* NYX built from the
user's description.  It is not a penetration test, not a vulnerability scan and
not a security certification.  Three properties matter for every result:

* a finding is emitted only when graph evidence supports it (`evidence` lists it),
* `certainty` separates "confirmed in the supplied model" from "inferred risk"
  from "information missing — verify",
* missing information becomes a *verification gap*, never a fabricated vulnerability.

Rules run against both views.  Anything present in the conventional view and
absent from the proposed one is reported as an improvement instead of a finding.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.architecture import ArchitectureGraph
from app.schemas.common import (
    BackupPolicy,
    DataClassification,
    FindingCertainty,
    IamScope,
    LogicalComponentType,
    Severity,
    TransportSecurity,
)
from app.schemas.reports import SecurityFinding, SecurityReport, VerificationGap

STATEFUL_TYPES = {
    LogicalComponentType.RELATIONAL_DB,
    LogicalComponentType.DOCUMENT_DB,
    LogicalComponentType.KEY_VALUE_DB,
    LogicalComponentType.CACHE,
    LogicalComponentType.OBJECT_STORAGE,
    LogicalComponentType.BLOCK_STORAGE,
    LogicalComponentType.SEARCH_INDEX,
    LogicalComponentType.TIME_SERIES_DB,
    LogicalComponentType.DATA_WAREHOUSE,
}
CREDENTIAL_BEARING = {
    LogicalComponentType.APP_SERVER,
    LogicalComponentType.FUNCTION,
    LogicalComponentType.WORKER,
    LogicalComponentType.BATCH_JOB,
    LogicalComponentType.CONTAINER_SERVICE,
    LogicalComponentType.VIRTUAL_MACHINE,
    LogicalComponentType.NOTIFICATION,
    LogicalComponentType.WEB_SERVER,
}
PROTECTED = {DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED}
SENSITIVE_LOG_TYPES = {
    LogicalComponentType.MONITORING,
    LogicalComponentType.LOGGING,
}


@dataclass
class RuleOutcome:
    findings: list[SecurityFinding]
    gaps: list[VerificationGap]


class SecurityAnalyzer:
    """Deterministic rule set over one architecture view."""

    scope_statement = (
        "Architecture-level review of the modelled components and their recorded properties. "
        "It is not a penetration test, a vulnerability scan or a certification, and it cannot see "
        "configuration that was not described."
    )

    def __init__(self) -> None:
        self._counter = 0

    def analyze(
        self,
        proposed: ArchitectureGraph,
        conventional: ArchitectureGraph | None = None,
        *,
        sensitive_data_expected: bool = False,
        multi_tenant: bool = False,
        audit_required: bool | None = None,
        coordination_required: bool = False,
        cold_start_sensitive: bool = False,
        latency_budget_ms: int | None = None,
    ) -> SecurityReport:
        self._counter = 0
        extras = {
            "coordination_required": coordination_required,
            "cold_start_sensitive": cold_start_sensitive,
            "latency_budget_ms": latency_budget_ms,
        }
        proposed_outcome = self._run(proposed, sensitive_data_expected, multi_tenant, audit_required, extras)
        conventional_findings: list[SecurityFinding] = []
        conventional_gaps: list[VerificationGap] = []
        if conventional is not None:
            conventional_outcome = self._run(
                conventional, sensitive_data_expected, multi_tenant, audit_required, {}
            )
            conventional_findings = conventional_outcome.findings
            conventional_gaps = conventional_outcome.gaps

        positives = _improvements(conventional_findings, proposed_outcome.findings)

        findings = proposed_outcome.findings
        gaps = [*proposed_outcome.gaps, *conventional_gaps]
        # `counts` describes the audited (proposed) view; the conventional view is
        # reported separately so the UI can show "N issues the redesign removes".
        counts: dict[str, int] = {level.value: 0 for level in Severity}
        for finding in findings:
            counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
        by_certainty: dict[str, int] = {level.value: 0 for level in FindingCertainty}
        for finding in findings + conventional_findings:
            by_certainty[finding.certainty.value] = by_certainty.get(finding.certainty.value, 0) + 1

        return SecurityReport(
            scope_statement=self.scope_statement,
            audited_view=proposed.id,
            findings=findings,
            baseline_findings=conventional_findings,
            verification_gaps=gaps,
            counts=counts,
            by_certainty=by_certainty,
            positives=positives,
            methodology=[
                "Rules read only recorded component evidence (exposure, authentication, transport security, "
                "data classification, encryption, IAM scope, backup policy, secrets handling, audit logging).",
                "A finding requires evidence present in the graph; otherwise the item is reported as a "
                "verification gap asking the reviewer to confirm it.",
                "Findings are graded so that severity tracks what the model actually shows: a confirmed public "
                "database is high, an unstated TLS policy is medium, an unspecified rotation policy is a question.",
                f"{len(conventional_findings)} finding(s) were recorded against the conventional view; those are the "
                "issues the proposed design is intended to remove.",
            ],
            limitations=[
                "Cannot detect implementation defects, dependency vulnerabilities or misconfigured resources "
                "that were not described.",
                "Cannot verify provider-side defaults; each provider's managed defaults are assumed, not proven.",
                "Severity is relative to this model only and is not a CVSS or audit rating.",
            ],
        )

    # ------------------------------------------------------------------ per view

    def _run(
        self,
        graph: ArchitectureGraph,
        sensitive_expected: bool,
        multi_tenant: bool,
        audit_required: bool | None,
        extras: dict[str, object] | None = None,
    ) -> RuleOutcome:
        extras = extras or {}
        findings: list[SecurityFinding] = []
        gaps: list[VerificationGap] = []
        components = graph.components

        def add(
            code: str,
            title: str,
            severity: Severity,
            category: str,
            explanation: str,
            evidence: list[str],
            recommendation: str,
            certainty: FindingCertainty,
            members: list[str],
        ) -> None:
            self._counter += 1
            findings.append(
                SecurityFinding(
                    id=f"SEC-{self._counter:03d}",
                    title=title,
                    severity=severity,
                    category=category,
                    explanation=explanation,
                    evidence=evidence,
                    recommendation=recommendation,
                    certainty=certainty,
                    component_ids=members,
                    architecture_view=graph.id,
                    references=[
                        "NYX security rule "
                        + code
                        + " (docs/PROJECT_REPORT.md — Security analysis method)"
                    ],
                )
            )

        def gap(code: str, question: str, why: str, members: list[str], check: str) -> None:
            if any(existing.question == question for existing in gaps):
                return
            self._counter += 1
            gaps.append(
                VerificationGap(
                    id=f"GAP-{self._counter:03d}",
                    question=question,
                    why_it_matters=why,
                    component_ids=members,
                    suggested_check=check,
                )
            )

        # 1. Explicit public exposure of a stateful store.
        exposed_stores = [
            item
            for item in components
            if item.type in STATEFUL_TYPES and item.security.publicly_reachable is True
        ]
        if exposed_stores:
            add(
                "SEC-PUBLIC-STORE",
                "Stateful store is reachable from the public internet",
                Severity.CRITICAL,
                "exposure",
                "A data-bearing component is modelled as publicly reachable, which bypasses every "
                "control that sits behind the application tier.",
                [f"{item.label}: publicly_reachable = true" for item in exposed_stores],
                "Remove direct public reachability: place access behind the API surface or a private "
                "network, and verify with the provider's public-access flag plus a policy that denies it.",
                FindingCertainty.CONFIRMED_IN_MODEL,
                [item.id for item in exposed_stores],
            )

        # 2. Publicly reachable component without authentication.
        unauthenticated = [
            item
            for item in components
            if item.security.publicly_reachable is True
            and item.security.requires_authentication is False
            and item.type
            not in {
                LogicalComponentType.CLIENT_WEB,
                LogicalComponentType.CLIENT_MOBILE,
                LogicalComponentType.DNS,
            }
        ]
        if unauthenticated:
            add(
                "SEC-NO-AUTH",
                "Publicly reachable component with no authentication requirement",
                Severity.HIGH,
                "authentication",
                "The model shows an internet-facing component that does not require authentication while "
                "serving more than static client code.",
                [f"{item.label}: publicly_reachable = true, requires_authentication = false" for item in unauthenticated],
                "Require authentication at the edge (gateway/CDN authorizer) or restrict the component to "
                "public static content only.",
                FindingCertainty.CONFIRMED_IN_MODEL,
                [item.id for item in unauthenticated],
            )

        # 3. Transport security not enforced on an internet-facing component.
        weak_tls = [
            item
            for item in components
            if item.security.publicly_reachable is True
            and item.security.transport_security
            in {TransportSecurity.UNSPECIFIED, TransportSecurity.NONE, TransportSecurity.TLS_OPTIONAL}
        ]
        if weak_tls:
            add(
                "SEC-TLS",
                "Transport security not stated as enforced for a public entry point",
                Severity.MEDIUM,
                "transport security",
                "Nothing in the model requires TLS for a component reachable from the internet, so "
                "credentials or tokens could be exchanged in cleartext.",
                [f"{item.label}: transport_security = {item.security.transport_security.value}" for item in weak_tls],
                "Enforce HTTPS only, redirect plaintext, and enable HTTP strict transport security at the edge.",
                FindingCertainty.INFERRED_RISK,
                [item.id for item in weak_tls],
            )

        # 4. Sensitive data without a stated protection strategy.
        sensitive_components = [
            item
            for item in components
            if item.security.data_classification in PROTECTED
            and item.type not in SENSITIVE_LOG_TYPES
        ]
        unprotected = [item for item in sensitive_components if item.security.encryption_at_rest in {None, False}]
        if unprotected:
            add(
                "SEC-AT-REST",
                "Confidential data without an identified at-rest protection",
                Severity.MEDIUM,
                "data protection",
                "Components holding confidential or restricted data do not record an encryption-at-rest "
                "decision, so the strategy cannot be confirmed from the model.",
                [f"{item.label}: data_classification = {item.security.data_classification.value}, "
                 f"encryption_at_rest = {item.security.encryption_at_rest}" for item in unprotected],
                "Enable provider-managed encryption for every store holding this data, and record which key "
                "management option (provider-managed or customer-managed) applies.",
                FindingCertainty.INFERRED_RISK,
                [item.id for item in unprotected],
            )
        if sensitive_expected and not any(
            item.security.data_classification in PROTECTED for item in components
        ):
            gap(
                "SEC-CLASSIFY",
                "Which component holds the sensitive data the description implies, and how is it classified?",
                "Without a classification the encryption, retention and access rules cannot be derived.",
                [item.id for item in components if item.type in STATEFUL_TYPES],
                "List which stores hold personal or academic records and label them confidential or restricted.",
            )

        # 5. Backup / recovery.
        stateful = [item for item in components if item.type in STATEFUL_TYPES]
        no_backup = [item for item in stateful if item.security.backup_policy == BackupPolicy.NONE]
        unclear_backup = [item for item in stateful if item.security.backup_policy == BackupPolicy.UNSPECIFIED]
        if no_backup:
            add(
                "SEC-NO-BACKUP",
                "Stateful component with no backup or recovery capability",
                Severity.HIGH,
                "resilience",
                "The model records an explicit absence of backup for a component that holds the system of record.",
                [f"{item.label}: backup_policy = none" for item in no_backup],
                "Enable automated snapshots with point-in-time recovery where supported, and rehearse a restore "
                "before relying on it.",
                FindingCertainty.CONFIRMED_IN_MODEL,
                [item.id for item in no_backup],
            )
        if unclear_backup:
            gap(
                "SEC-BACKUP-UNSPEC",
                "What backup and recovery expectations apply to the stateful stores?",
                "Recovery objectives decide storage, retention and cost; guessing them is how outages become data loss.",
                [item.id for item in unclear_backup],
                "Confirm the required recovery point/time and whether a restore has ever been tested.",
            )

        # 6. Permissions breadth.
        broad = [item for item in components if item.security.iam_scope == IamScope.BROAD]
        if broad:
            add(
                "SEC-IAM-BROAD",
                "Overly broad permissions recorded for a component",
                Severity.HIGH,
                "access control",
                "The model states a permission scope broad enough to reach more than the component needs, "
                "which widens the blast radius of any single compromise.",
                [f"{item.label}: iam_scope = broad" for item in broad],
                "Scope each role to the specific resources and actions used; split the writer, reader and "
                "artefact roles instead of sharing one policy.",
                FindingCertainty.CONFIRMED_IN_MODEL,
                [item.id for item in broad],
            )
        unspecified_scope = [item for item in components if item.security.iam_scope == IamScope.UNSPECIFIED]
        if unspecified_scope:
            gap(
                "SEC-IAM-UNSPEC",
                f"Which identity and permission scope does each of the {len(unspecified_scope)} "
                "unspecified component(s) run under?",
                "Broad identity permissions are one of the most common real-world causes of cloud breaches.",
                [item.id for item in unspecified_scope][:8],
                "List the identity/role each component runs as and what it is allowed to touch.",
            )

        # 7. Secrets handling.
        weak_secrets = [
            item
            for item in components
            if item.type in CREDENTIAL_BEARING
            and (item.security.secrets_handling or "").lower()
            in {"environment variables", "config file on the host", "unspecified", "app config"}
        ]
        if weak_secrets:
            add(
                "SEC-SECRETS",
                "Credentials handled outside a dedicated secret store",
                Severity.MEDIUM,
                "secrets",
                "Components that need provider or third-party credentials are modelled as holding them in "
                "host configuration, which cannot be rotated, scoped or audited independently.",
                [f"{item.label}: secrets_handling = {item.security.secrets_handling}" for item in weak_secrets],
                "Move credentials into a managed secret store, use workload identity where available, and "
                "rotate on a schedule with an expiry that fails closed.",
                FindingCertainty.INFERRED_RISK,
                [item.id for item in weak_secrets],
            )

        # 8. Audit trail.
        if audit_required:
            logging_nodes = [item for item in components if item.type in SENSITIVE_LOG_TYPES]
            if not logging_nodes or all(item.security.audit_logging is not True for item in logging_nodes):
                add(
                    "SEC-AUDIT",
                    "Audit-trail requirement without an identified logging component",
                    Severity.MEDIUM,
                    "auditability",
                    "The requirements call for an audit trail, but no component in this view is modelled as "
                    "capturing immutable audit events.",
                    ["requirements state an audit/retention expectation"]
                    + [f"{item.label}: audit_logging = {item.security.audit_logging}" for item in logging_nodes],
                    "Record actor, action, object and timestamp for state-changing operations into an append-only "
                    "store with retention that matches the obligation.",
                    FindingCertainty.INFERRED_RISK,
                    [item.id for item in (logging_nodes or components[:1])],
                )

        # 9. Input validation on the public entry point.
        entry_points = [
            item
            for item in components
            if item.security.publicly_reachable
            and item.type
            in {
                LogicalComponentType.API_GATEWAY,
                LogicalComponentType.LOAD_BALANCER,
                LogicalComponentType.WEB_SERVER,
                LogicalComponentType.FUNCTION,
                LogicalComponentType.APP_SERVER,
            }
        ]
        unvalidated = [item for item in entry_points if (item.security.input_validation or "unspecified") == "unspecified"]
        if unvalidated:
            gap(
                "SEC-INPUT-VAL",
                "Where are request schema, payload size and content type validated at the public entry point?",
                "Every serverless design pushes parsing, size limits and content-type checks somewhere; if it is "
                "nowhere, handlers inherit the risk.",
                [item.id for item in unvalidated],
                "Confirm where schemas, payload size and content-type are enforced for each route.",
            )

        # 10. Trust boundary clarity.
        modelled = {item.id for boundary in graph.trust_boundaries for item in [
            component for component in components if component.id in boundary.component_ids
        ]}
        outside = [component.id for component in components if component.id not in modelled]
        if outside:
            gap(
                "SEC-BOUNDARY",
                "Which trust boundary do the remaining components sit inside?",
                "An unassigned component has no stated rule about who may reach it, which is how lateral "
                "movement becomes possible.",
                outside,
                "State which network/identity boundary each component belongs to.",
            )
        crossing = [
            connection
            for connection in graph.connections
            if connection.crosses_trust_boundary
            and _is_direct_public_to_data(graph, connection)
        ]
        if crossing:
            add(
                "SEC-EDGE-TO-DATA",
                "Public edge connects directly to a data component",
                Severity.HIGH,
                "segmentation",
                "A connection crosses from the internet-facing boundary straight into the data boundary, "
                "skipping the application tier where authorization is enforced.",
                [f"{connection.source} -> {connection.target} ({connection.kind.value})" for connection in crossing],
                "Terminate all data access inside the application tier and remove the direct path.",
                FindingCertainty.CONFIRMED_IN_MODEL,
                sorted({connection.source for connection in crossing} | {connection.target for connection in crossing}),
            )

        # 11. Multi-tenancy without isolation evidence.
        if multi_tenant:
            stores = [item for item in components if item.type in STATEFUL_TYPES]
            if stores and not any(
                "tenant" in (item.description or "").lower() or "isolation" in (item.description or "").lower()
                for item in stores
            ):
                gap(
                    "SEC-TENANT",
                    "Multiple tenants are described, but no tenant-isolation strategy is recorded for the stores.",
                    "Cross-tenant leakage is the highest-impact failure mode of a shared-data design; row-level "
                    "security, separate schemas and separate databases have very different risk profiles.",
                    [item.id for item in stores],
                    "State how tenant rows are separated and how a query is prevented from reading another tenant.",
                )

        # 12. Cross-request coordination assigned to no primitive.
        if extras.get("coordination_required"):
            functions = [item for item in components if item.type == LogicalComponentType.FUNCTION]
            stores = [item for item in components if item.type in STATEFUL_TYPES]
            if functions and stores:
                add(
                    "SEC-CONCURRENCY",
                    "Coordination requirement with no designated locking primitive",
                    Severity.MEDIUM,
                    "data integrity",
                    "The requirements need mutual exclusion between concurrent executions, but nothing in this "
                    "view assigns that coordination to a mechanism. With many short-lived handlers running in "
                    "parallel, an application-level check-then-write is a race, not a lock.",
                    ["requirements state locking or concurrent-safety behaviour",
                     f"{len(functions)} concurrently executed component(s) and {len(stores)} shared store(s) here"],
                    "Choose and record the mechanism: a transactional conditional write in the store, a locked "
                    "lease in the cache, or single-writer partitioning by key.",
                    FindingCertainty.INFERRED_RISK,
                    [item.id for item in functions + stores][:6],
                )

        # 13. Latency-sensitive path on a cold-start-prone runtime.
        budget = extras.get("latency_budget_ms")
        if extras.get("cold_start_sensitive") or (isinstance(budget, int) and budget <= 150):
            warm = [item for item in components if "provisioned" in str(item.properties).lower()]
            functions = [item for item in components if item.type == LogicalComponentType.FUNCTION]
            if functions and not warm:
                add(
                    "SEC-COLDSTART",
                    "Latency-sensitive path has no warm-start strategy recorded",
                    Severity.LOW,
                    "resilience",
                    "The requirements make start-up latency matter and this view places that path on a runtime "
                    "that may start instances on demand, but no warm-start decision is modelled. This is a design "
                    "gap rather than a vulnerability.",
                    [
                        f"latency budget: {budget} ms" if isinstance(budget, int) else "cold-start sensitivity stated",
                        f"{len(functions)} function-shaped component(s)",
                    ],
                    "Record the warm-start decision (provisioned concurrency, a pre-warmed schedule, or an "
                    "accepted cold-start budget) and verify it with a p99 measurement on the first request after idle.",
                    FindingCertainty.NEEDS_VERIFICATION,
                    [item.id for item in functions][:6],
                )

        return RuleOutcome(findings=findings, gaps=gaps)


def _is_direct_public_to_data(graph: ArchitectureGraph, connection: object) -> bool:
    source = graph.component(getattr(connection, "source", ""))
    target = graph.component(getattr(connection, "target", ""))
    if source is None or target is None:
        return False
    return (
        source.security.publicly_reachable is True
        and target.type in STATEFUL_TYPES
        and target.tier.value == "data"
    )


def _improvements(before: list[SecurityFinding], after: list[SecurityFinding]) -> list[str]:
    after_keys = {(item.category, item.title) for item in after}
    resolved: list[str] = []
    for finding in before:
        if (finding.category, finding.title) in after_keys:
            continue
        resolved.append(
            f"{finding.title} — present in the conventional view, not present in the proposed design "
            f"(severity {finding.severity.value})."
        )
    return resolved


def analyze_architectures(
    proposed: ArchitectureGraph,
    conventional: ArchitectureGraph | None,
    **kwargs: object,
) -> SecurityReport:
    return SecurityAnalyzer().analyze(proposed, conventional, **kwargs)  # type: ignore[arg-type]


__all__ = ["SecurityAnalyzer", "analyze_architectures"]
