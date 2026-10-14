"""Exportable report renderers (Markdown + JSON) built from the analysis object."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.schemas.analysis import AnalysisResult
from app.schemas.common import CloudProvider
from app.services.labels import readable

PROVIDER_LABEL = {
    CloudProvider.AWS: "Amazon Web Services",
    CloudProvider.GCP: "Google Cloud",
    CloudProvider.AZURE: "Microsoft Azure",
    CloudProvider.UNDECIDED: "Not decided",
}


def _c(value: object) -> str:
    """Make one value safe inside a Markdown table cell.

    Whitespace is collapsed (a newline would end the row), backslashes are doubled
    and pipes escaped so that user-supplied names cannot add or break columns.
    """
    text = " ".join(str(value).split())
    return text.replace("\\", "\\\\").replace("|", "\\|")



def export_filename(result: AnalysisResult, extension: str) -> str:
    """One filename rule for every export: nyx-report-<slug of the analysis title>.<extension>.

    Saved projects and unsaved analyses use the same rule, so a download is named the same
    way wherever it came from.
    """
    safe = "".join(character if character.isalnum() or character in "-_" else "-" for character in result.title)
    stem = safe[:48].strip("-").lower() or "analysis"
    return f"nyx-report-{stem}.{extension}"


def to_json(result: AnalysisResult, *, indent: int = 2) -> str:
    payload = {"export": {"generator": "NYX", "kind": "analysis-result", "generated_at": _now()}, **result.to_json_dict()}
    return json.dumps(payload, indent=indent, ensure_ascii=False, sort_keys=False)


def to_markdown(result: AnalysisResult) -> str:
    """Markdown report. The browser print view renders the same sections."""
    lines: list[str] = []
    add = lines.append

    add("# NYX — Cloud Architecture Analysis Report")
    add("")
    add(f"**{result.application.name}**  ")
    add(f"Generated: {result.created_at.strftime('%Y-%m-%d %H:%M UTC')} · Analysis `{result.analysis_id}`  ")
    add(f"Mode: **{_mode(result)}** · Schema `{result.schema_version}` · Rule pack `{result.rule_pack_version}` · "
        f"Catalogue `{result.catalog_version}`")
    add("")
    add("> NYX produces conceptual blueprints and heuristic, explainable estimates. It does not deploy anything, "
        "and its scores and cost figures are not industry benchmarks, prices or financial outcomes.")
    add("")

    add("## 1. Application overview")
    add("")
    add(result.application.description)
    add("")
    add("| Requirement | Value | Source |")
    add("| --- | --- | --- |")
    for label, value, key in _requirement_rows(result):
        add(f"| {_c(label)} | {_c(value)} | {_c(key)} |")
    add("")

    add("## 2. Extracted workload characteristics")
    add("")
    add(f"- Classification: **{readable(result.workload.classification)}**")
    add(f"- {result.workload.headline}")
    add(f"- Request shape: {result.workload.request_shape}")
    add(f"- Data shape: {result.workload.data_shape}")
    add(f"- Execution shape: {result.workload.execution_shape}")
    add("")

    add("## 3. Assumptions and open questions")
    add("")
    if result.assumptions:
        for item in result.assumptions:
            add(f"- **{item.id}** ({readable(item.basis.value)}, impact {item.impact}): {item.statement}")
    else:
        add("- No assumptions were needed; every deciding input was stated explicitly.")
    add("")
    if result.open_questions:
        add("**Unanswered (recorded rather than guessed):**")
        add("")
        for question in result.open_questions:
            add(f"- `{question.field}` — {question.question} *({question.why_it_matters})*")
        add("")

    add("## 4. Serverless suitability")
    add("")
    add(f"**{result.suitability.headline}** — score {result.suitability.score:.0f}/100"
        + (f" (provisional {result.suitability.provisional_score:.0f})" if result.suitability.provisional_score else ""))
    add("")
    add(result.suitability.rationale)
    add("")
    add(f"Recommended pattern: **{readable(result.suitability.recommended_pattern.value)}**")
    add("")
    add("| Factor | Weight | Impact | Contribution | Basis | Evidence |")
    add("| --- | --- | --- | --- | --- | --- |")
    for factor in result.suitability.factors:
        evidence = "; ".join(factor.evidence) or "—"
        add(f"| {_c(factor.name)} | {factor.weight:.2f} | {factor.impact:+.2f} | {factor.contribution:+.3f} | "
            f"{readable(factor.basis)} | {evidence} |")
    add("")
    add(f"Method: {result.suitability.methodology.formula}")
    add("")
    if result.suitability.components:
        add("### Component-level assessment")
        add("")
        add("| Component | Score | Outcome | Realization | Reason |")
        add("| --- | --- | --- | --- | --- |")
        for component in result.suitability.components:
            add(f"| {_c(component.component_label)} | {component.score:.0f} | "
                f"{readable(component.outcome.value)} | {readable(component.recommendation)} | "
                f"{component.recommendation_reason} |")
        add("")
    for caveat in result.suitability.caveats:
        add(f"> {caveat}")
    add("")

    add("## 5. Architecture blueprints")
    add("")
    for graph in result.architectures:
        add(f"### {graph.title}")
        add("")
        add(graph.summary)
        add("")
        add("| Component | Type | Deployment | Description |")
        add("| --- | --- | --- | --- |")
        for component in graph.components:
            add(f"| {_c(component.label)} | {readable(component.type)} | {readable(component.deployment_target)} | "
                f"{component.description} |")
        add("")
        add("Connections:")
        add("")
        for connection in graph.connections:
            boundary = " *(crosses trust boundary)*" if connection.crosses_trust_boundary else ""
            label = f" — {connection.label}" if connection.label else ""
            add(f"- `{connection.source}` → `{connection.target}` ({readable(connection.kind)}){label}{boundary}")
        add("")
        if graph.trust_boundaries:
            add("Trust boundaries: " + "; ".join(
                f"**{boundary.label}** = {', '.join(boundary.component_ids)}" for boundary in graph.trust_boundaries
            ))
            add("")
        for warning in graph.caveats:
            add(f"> {warning}")
        add("")

    add("## 6. Multi-cloud service mapping")
    add("")
    add(f"Provider shown in the diagrams: **{PROVIDER_LABEL[result.default_provider]}**. "
        "Switching provider in the application relabels the same logical components; it does not deploy anything.")
    add("")
    add("| Logical component | AWS | Google Cloud | Azure | 1:1? |")
    add("| --- | --- | --- | --- | --- |")
    for row in result.mapping_table:
        def cell(mapping: object) -> str:
            if mapping is None:
                return "—"
            return _c(getattr(mapping, "service_name", str(mapping)))

        add(f"| {_c(row.component_label)} | {_c(cell(row.aws))} | {_c(cell(row.gcp))} | {_c(cell(row.azure))} | "
            f"{'yes' if row.one_to_one else 'no'} |")
    add("")
    notable = [row for row in result.mapping_table if not row.one_to_one]
    if notable:
        add("Where equivalence is imperfect:")
        add("")
        for row in notable:
            add(f"- **{row.component_label}**: " + " ".join(row.notes))
        add("")

    add("## 7. Security findings (architecture-level)")
    add("")
    add(result.security.scope_statement)
    add("")
    add(f"View audited: `{result.security.audited_view}`. Findings: {len(result.security.findings)}; "
        f"verification questions: {len(result.security.verification_gaps)}.")
    add("")
    if result.security.findings:
        add("| ID | Severity | Certainty | Finding | Components |")
        add("| --- | --- | --- | --- | --- |")
        for finding in result.security.findings:
            add(f"| {_c(finding.id)} | {finding.severity.value} | {readable(finding.certainty)} | {_c(finding.title)} | "
                f"{', '.join(finding.component_ids) or '—'} |")
        add("")
        for finding in result.security.findings:
            add(f"**{finding.id} — {finding.title}** ({finding.severity.value})")
            add("")
            add(f"- Explanation: {finding.explanation}")
            add(f"- Evidence: {'; '.join(finding.evidence)}")
            add(f"- Recommended action: {finding.recommendation}")
            add("")
    else:
        add("No rule fired against the proposed view with the evidence available.")
        add("")
    if result.security.baseline_findings:
        add("### Recorded in the conventional view (the proposal removes these)")
        add("")
        add("| Severity | Certainty | Finding | Evidence |")
        add("| --- | --- | --- | --- |")
        for finding in result.security.baseline_findings:
            add(f"| {finding.severity.value} | {readable(finding.certainty)} | {_c(finding.title)} | "
                f"{'; '.join(finding.evidence)} |")
        add("")
    if result.security.verification_gaps:
        add("### Missing information that must be verified")
        add("")
        for gap in result.security.verification_gaps:
            add(f"- **{gap.id}** {gap.question}")
            add(f"  - Why it matters: {gap.why_it_matters}")
            if gap.suggested_check:
                add(f"  - Suggested check: {gap.suggested_check}")
        add("")
    if result.security.positives:
        add("### Addressed by the proposed design")
        add("")
        for item in result.security.positives:
            add(f"- {item}")
        add("")
    for limitation in result.security.limitations:
        add(f"> {limitation}")
    add("")

    add("## 8. Relative cost comparison")
    add("")
    add(result.cost.disclaimer)
    add("")
    add(f"Period: {result.cost.period}. Unit: **{result.cost.unit_name} ({result.cost.unit})**.")
    add("")
    add("| Scenario | Fixed | Variable | Operational | Total |")
    add("| --- | --- | --- | --- | --- |")
    for scenario in result.cost.scenarios:
        add(f"| {_c(scenario.label)} | {scenario.fixed_ricu:.2f} | {scenario.variable_ricu:.2f} | "
            f"{scenario.operational_ricu:.2f} | **{scenario.total_ricu:.2f}** |")
    add("")
    if "model_relative_change_pct" in result.cost.comparison:
        add(f"Model-relative difference: {result.cost.comparison['model_relative_change_pct']:+.1f}% "
            f"(ratio {result.cost.comparison['ratio_proposed_to_conventional']:.2f}). Derived from the coefficients "
            "above — not a guaranteed saving.")
        add("")
    if result.cost.fixed_share:
        add("Fixed share of total: " + ", ".join(f"{key} {value:.0f}%" for key, value in result.cost.fixed_share.items()))
        add("")
    for scenario in result.cost.scenarios:
        add(f"### {scenario.label} line items")
        add("")
        add("| Item | Qty | Unit | RICU | Type | Basis |")
        add("| --- | --- | --- | --- | --- | --- |")
        for item in scenario.line_items:
            add(f"| {_c(item.label)} | {item.quantity:g} | {_c(item.unit)} | {item.ricu:g} | {item.category.value} | "
                f"{readable(item.basis)} |")
        add("")
    if result.cost.sensitivity:
        add("### Sensitivity")
        add("")
        add("| Driver | Scenario | Conventional | Proposed |")
        add("| --- | --- | --- | --- |")
        for entry in result.cost.sensitivity:
            add(f"| {_c(entry.name)} | {_c(entry.low_label)} | {entry.conventional_delta_pct:+.1f}% | "
                f"{entry.proposed_delta_pct:+.1f}% |")
        add("")
    if result.cost.insufficient_inputs:
        add("### Inputs that were not sufficient")
        add("")
        for item in result.cost.insufficient_inputs:
            add(f"- {item}")
        add("")
    add("### Model assumptions")
    add("")
    for assumption in result.cost.assumptions:
        add(f"- {assumption}")
    add("")

    add("## 9. Migration assessment")
    add("")
    add(f"Overall complexity: **{readable(result.migration.overall_complexity.value)}** "
        f"(weighted {result.migration.complexity_score:.0f}/100).")
    add("")
    add("### Drivers")
    add("")
    for driver in result.migration.complexity_drivers:
        add(f"- {driver}")
    add("")
    add("### Components requiring modification")
    add("")
    add("| Component | Change | Complexity | Reason |")
    add("| --- | --- | --- | --- |")
    for change in result.migration.components_requiring_modification:
        add(f"| {_c(change.component_label)} | {_c(change.change)} | {change.complexity.value} | {_c(change.reason)} |")
    add("")
    if result.migration.dependencies_to_review:
        add("### Dependencies to review")
        add("")
        for item in result.migration.dependencies_to_review:
            add(f"- {item}")
        add("")
    if result.migration.compatibility_issues:
        add("### Compatibility issues")
        add("")
        for item in result.migration.compatibility_issues:
            add(f"- {item}")
        add("")
    add("### Roadmap")
    add("")
    for phase in result.migration.phases:
        add(f"**Phase {phase.index}: {phase.title}** — {phase.objective}")
        add("")
        for activity in phase.activities:
            add(f"- {activity}")
        add("")
        if phase.exit_criteria:
            add("Exit criteria: " + "; ".join(phase.exit_criteria))
            add("")
        add(f"Effort: {phase.effort.value} · Risk: {phase.risk.value}"
            + (f" · Components: {', '.join(phase.components_touched)}" if phase.components_touched else ""))
        add("")
    add("### Validation requirements")
    add("")
    for item in result.migration.validation_requirements:
        add(f"- {item}")
    add("")
    add("### Risks")
    add("")
    for item in result.migration.risks:
        add(f"- {item}")
    add("")
    if result.migration.caveats:
        add("### Caveats on this roadmap")
        add("")
        for item in result.migration.caveats:
            add(f"- {item}")
        add("")

    add("## 10. Limitations and disclosures")
    add("")
    for limitation in result.limitations:
        add(f"- **{limitation.code}** — {limitation.statement}")
    add("")
    if result.ai.status not in {"not_configured", "disabled_by_request"} or result.engine_mode.value == "ai_assisted":
        add("## Appendix — AI layer")
        add("")
        add(f"- Status: `{result.ai.status}` · provider `{result.ai.provider}` · model `{result.ai.model or '—'}` · "
            f"attempts {result.ai.attempts} · latency {result.ai.latency_ms or 0} ms")
        add(f"- Accepted fields: {', '.join(result.ai.accepted_fields) or 'none'}")
        add(f"- Rejected fields: {', '.join(result.ai.rejected_fields) or 'none'}")
        add(f"- Note: {result.ai.note}")
        add("")
    add("---")
    add("")
    add(f"_Exported from NYX at {_now()}._")
    add("")
    return "\n".join(lines)


def _requirement_rows(result: AnalysisResult) -> list[tuple[str, str, str]]:
    requirements = result.application
    rows: list[tuple[str, str, str]] = [
        ("Application type", readable(requirements.application_type.value),
         _basis(result, "application_type")),
        ("Expected users", f"{requirements.expected_users:,}" if requirements.expected_users else "not stated",
         _basis(result, "expected_users")),
        ("Traffic pattern", (readable(requirements.traffic_pattern.value) if requirements.traffic_pattern
                             else "not stated"), _basis(result, "traffic_pattern")),
        ("Data storage", ", ".join(readable(kind) for kind in requirements.data_storage) or "not stated",
         _basis(result, "data_storage")),
        ("Availability", (readable(requirements.availability.value) if requirements.availability
                          else "not stated"), _basis(result, "availability")),
        ("Budget preference", (readable(requirements.budget.value) if requirements.budget else "not stated"),
         _basis(result, "budget")),
        ("Preferred provider", PROVIDER_LABEL.get(requirements.preferred_provider or CloudProvider.UNDECIDED),
         _basis(result, "preferred_provider")),
    ]
    if requirements.additional_requirements:
        rows.append(("Additional requirements", requirements.additional_requirements, "user provided"))
    return rows


def _basis(result: AnalysisResult, field_name: str) -> str:
    entry = result.application.provenance.get(field_name)
    if entry is None:
        return "not stated"
    return readable(entry.basis.value)


def _mode(result: AnalysisResult) -> str:
    if result.engine_mode.value == "ai_assisted":
        return f"AI-assisted extraction ({result.ai.model or 'unknown model'}) + deterministic analysis"
    return "deterministic local rules engine (no AI used)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
