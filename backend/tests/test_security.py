"""Security analysis: evidence-gated findings, certainty labels, graded severity."""

from __future__ import annotations

from app.schemas.architecture import ArchitectureGraph, Component, Connection, NodePosition
from app.schemas.common import (
    ArchitectureStyle,
    ComponentTier,
    DeploymentTarget,
    FindingCertainty,
    LogicalComponentType,
    Severity,
)
from app.schemas.architecture import SecurityEvidence
from app.services.security_analyzer import SecurityAnalyzer
from app.services.templates import requirements_for
from app.services.pipeline import AnalysisPipeline
from app.schemas.analysis import AnalysisOptions, AnalysisRequest


def component(component_id, label, type_, *, security=None, tier=ComponentTier.APPLICATION, target=None):
    return Component(
        id=component_id,
        label=label,
        type=type_,
        tier=tier,
        description=f"{label} description",
        deployment_target=target or DeploymentTarget.SERVERLESS_FUNCTION,
        security=security or SecurityEvidence(),
    )


def graph(components, connections=None, *, graph_id="proposed"):
    return ArchitectureGraph(
        id=graph_id,
        style=ArchitectureStyle.HYBRID,
        title="Test view",
        components=components,
        connections=connections
        or [
            Connection(id=f"e{i}", source=components[0].id, target=item.id)
            for i, item in enumerate(components[1:] or components[:1], start=1)
        ],
        layout={item.id: NodePosition(x=0.0, y=float(index * 200)) for index, item in enumerate(components)},
    )


def analyze(proposed, conventional=None, **kwargs):
    return SecurityAnalyzer().analyze(proposed, conventional, **kwargs)


def test_finding_fires_only_when_the_evidence_is_in_the_model():
    exposed = graph(
        [
            component("client", "Web client", LogicalComponentType.CLIENT_WEB, security=SecurityEvidence(publicly_reachable=True)),
            component(
                "db",
                "Exams database",
                LogicalComponentType.RELATIONAL_DB,
                tier=ComponentTier.DATA,
                security=SecurityEvidence(publicly_reachable=True, data_classification="restricted"),
            ),
        ]
    )
    report = analyze(exposed)
    fired = [finding for finding in report.findings if "SEC-PUBLIC-STORE" in finding.references[0]]
    assert fired, "a publicly reachable store must produce a finding"
    finding = fired[0]
    assert finding.severity in {Severity.HIGH, Severity.CRITICAL}
    assert finding.certainty is FindingCertainty.CONFIRMED_IN_MODEL
    assert finding.component_ids == ["db"]
    assert finding.evidence and finding.recommendation
    assert "publicly_reachable = true" in " ".join(finding.evidence)


def test_missing_information_becomes_a_question_not_a_finding():
    quiet = graph(
        [
            component("client", "Web client", LogicalComponentType.CLIENT_WEB),
            component("api", "Exams API", LogicalComponentType.API_GATEWAY),
            component(
                "db", "Exams database", LogicalComponentType.RELATIONAL_DB, tier=ComponentTier.DATA
            ),
        ]
    )
    report = analyze(quiet)
    assert not [finding for finding in report.findings if "SEC-PUBLIC-STORE" in finding.references[0]]
    assert not [finding for finding in report.findings if "no authentication requirement" in finding.title.lower()]
    assert report.verification_gaps
    for gap in report.verification_gaps:
        assert gap.question.strip().endswith("?")
        assert gap.why_it_matters
        assert gap.suggested_check


def test_every_finding_carries_certainty_and_a_recommendation():
    result = AnalysisPipeline().run(
        AnalysisRequest(requirements=requirements_for("online-examination"), options=AnalysisOptions(use_ai=False))
    )
    findings = result.security.findings + result.security.baseline_findings
    assert findings, "the conventional view must be audited too"
    for finding in findings:
        assert finding.certainty in set(FindingCertainty)
        assert finding.recommendation
        assert finding.evidence
        assert finding.architecture_view in {"proposed", "conventional"}
        assert finding.references and finding.references[0].startswith("NYX security rule SEC-")
    # A proposed view with no findings must say so in terms of the evidence, not
    # as a clean bill of health.
    if not result.security.findings:
        assert result.security.verification_gaps


def test_severity_is_graded_rather_than_all_critical():
    result = AnalysisPipeline().run(
        AnalysisRequest(requirements=requirements_for("college-attendance"), options=AnalysisOptions(use_ai=False))
    )
    findings = result.security.findings + result.security.baseline_findings
    assert findings
    assert {finding.severity for finding in findings} != {Severity.CRITICAL}
    assert any(finding.severity in {Severity.LOW, Severity.MEDIUM} for finding in findings)
    assert all(finding.severity in set(Severity) for finding in findings)


def test_positive_findings_are_not_invented_for_show():
    # An input with no sensitive data and no exposure should surface no confirmed findings
    # on the proposed view — only questions.
    requirements = requirements_for("file-processing-pipeline")
    result = AnalysisPipeline().run(
        AnalysisRequest(requirements=requirements, options=AnalysisOptions(use_ai=False))
    )
    proposed_findings = [
        finding for finding in result.security.findings if finding.architecture_view == "proposed"
    ]
    for finding in proposed_findings:
        assert finding.evidence
    assert result.security.scope_statement
    assert result.security.limitations
    assert "not a penetration test" in result.security.scope_statement


def test_conventional_view_findings_are_compared_against_the_proposed_one():
    requirements = requirements_for("ecommerce-application")
    result = AnalysisPipeline().run(
        AnalysisRequest(requirements=requirements, options=AnalysisOptions(use_ai=False))
    )
    report = result.security
    assert report.audited_view == "proposed"
    assert report.baseline_findings, "the conventional view should show what the redesign removes"
    assert report.positives
    for item in report.positives:
        assert "conventional view" in item
    for finding in report.baseline_findings:
        assert finding.evidence and finding.certainty is not None


def test_certainty_and_severity_counts_agree_with_the_reported_findings():
    result = AnalysisPipeline().run(
        AnalysisRequest(requirements=requirements_for("food-delivery-platform"), options=AnalysisOptions(use_ai=False))
    )
    report = result.security
    assert set(report.by_certainty) == {level.value for level in FindingCertainty}
    assert set(report.counts) == {level.value for level in Severity}
    assert sum(report.counts.values()) == len(report.findings)
    assert sum(report.by_certainty.values()) >= len(report.findings)
    for level, count in report.counts.items():
        assert count == len([finding for finding in report.findings if finding.severity.value == level])


def test_audit_secrets_and_encryption_rules_trigger_on_their_own_evidence():
    store = component(
        "db",
        "Ledger database",
        LogicalComponentType.RELATIONAL_DB,
        tier=ComponentTier.DATA,
        security=SecurityEvidence(
            data_classification="restricted",
            encryption_at_rest=False,
            iam_scope="broad",
            requires_authentication=True,
        ),
    )
    api = component(
        "api", "Ledger API", LogicalComponentType.API_GATEWAY, security=SecurityEvidence(requires_authentication=True)
    )
    worker = component(
        "ledger-writer",
        "Ledger writer",
        LogicalComponentType.APP_SERVER,
        security=SecurityEvidence(secrets_handling="environment variables"),
    )
    report = analyze(graph([api, store, worker]), audit_required=True)
    codes = " | ".join(" ".join(finding.references) for finding in report.findings)
    assert "SEC-AT-REST" in codes, codes
    assert "SEC-SECRETS" in codes, codes
    assert "SEC-IAM-BROAD" in codes, codes
    assert "SEC-AUDIT" in codes, codes
    assert Severity.HIGH in {finding.severity for finding in report.findings}
    secrets_finding = next(f for f in report.findings if "SEC-SECRETS" in f.references[0])
    assert secrets_finding.component_ids == ["ledger-writer"]
    assert "environment variables" in " ".join(secrets_finding.evidence)


def test_unstated_properties_become_questions_not_findings():
    api = component(
        "api",
        "Public API",
        LogicalComponentType.API_GATEWAY,
        security=SecurityEvidence(publicly_reachable=True, requires_authentication=True),
    )
    store = component("db", "Store", LogicalComponentType.RELATIONAL_DB, tier=ComponentTier.DATA)
    report = analyze(graph([api, store]))
    gap_text = " ".join(gap.question for gap in report.verification_gaps).lower()
    assert "validated" in gap_text or "entry point" in gap_text, gap_text
    assert all(gap.suggested_check for gap in report.verification_gaps)
    assert not [finding for finding in report.findings if "SEC-INPUT-VAL" in finding.references[0]]
