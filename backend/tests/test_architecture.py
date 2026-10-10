"""Architecture engine: two views, graph validity, layout, per-component realization.

These tests exercise the engine through the pipeline (the only supported
composition) so that the graphs they assert on are the graphs the API returns.
"""

from __future__ import annotations

import pytest

from app.rules.architecture_layout import GAP_X, NODE_HEIGHT, NODE_WIDTH
from app.schemas.analysis import AnalysisOptions, AnalysisRequest
from app.schemas.common import CloudProvider, ComponentTier, DeploymentTarget, LogicalComponentType
from app.schemas.requirements import ApplicationRequirements
from app.services.pipeline import AnalysisPipeline
from app.services.templates import requirements_for

PIPELINE = AnalysisPipeline()
PROVIDER_VALUES = {"aws", "gcp", "azure"}


def run(description: str, **overrides):
    requirements = ApplicationRequirements(name="Architecture fixture", description=description, **overrides)
    return PIPELINE.run(AnalysisRequest(requirements=requirements, options=AnalysisOptions(use_ai=False)))


def graphs_of(result):
    return {graph.id: graph for graph in result.architectures}


def test_both_views_are_returned_in_a_fixed_order():
    result = run(
        "An online examination platform for 10000 students: authenticated REST API, relational database, "
        "file storage for PDF answer scripts, queue-driven transcoding workers and email notifications."
    )
    conventional, proposed = result.architectures
    assert (conventional.id, proposed.id) == ("conventional", "proposed")
    assert conventional.style.value == "conventional"
    assert proposed.style.value in {"serverless", "hybrid"}
    assert result.primary_view == "proposed"
    assert conventional.summary and proposed.summary
    assert conventional.title != proposed.title


def test_conventional_view_is_serverful_and_proposed_is_cloud_native():
    result = run(
        "An e-commerce catalogue with a search index, relational database, object storage for images, "
        "payment callbacks and 50000 users with spiky traffic."
    )
    conventional, proposed = result.architectures
    compute_like = {ComponentTier.APPLICATION, ComponentTier.PROCESSING, ComponentTier.INTEGRATION}
    conventional_targets = {
        component.deployment_target for component in conventional.components if component.tier in compute_like
    }
    assert conventional_targets <= {DeploymentTarget.VIRTUAL_MACHINE, DeploymentTarget.CONTAINER}
    assert DeploymentTarget.SERVERLESS_FUNCTION in {
        component.deployment_target for component in proposed.components
    } or DeploymentTarget.CONTAINER in {component.deployment_target for component in proposed.components}
    # The same component id keeps its identity across views so the UI can diff them.
    assert {component.id for component in conventional.components} & {
        component.id for component in proposed.components
    }


def test_component_types_come_from_the_closed_vocabulary():
    result = run("A simple internal tool with an API, a relational database and file uploads.")
    for graph in result.architectures:
        assert graph.components
        for component in graph.components:
            assert component.type in set(LogicalComponentType)
            assert component.tier in set(ComponentTier)
            assert component.label and component.description
            assert component.traits is not None
            assert set(component.mappings) == PROVIDER_VALUES


def test_every_edge_and_boundary_references_known_components():
    # ArchitectureGraph itself raises on dangling references; this asserts the
    # validator is armed and the produced graphs pass it.
    from app.schemas.architecture import ArchitectureGraph, Connection

    base = graphs_of(run("An attendance portal with a public API, a database and object storage."))["proposed"]
    with pytest.raises(Exception):
        ArchitectureGraph.model_validate(
            {
                **base.model_dump(),
                "connections": [Connection(id="x", source="client", target="does-not-exist").model_dump()],
            }
        )
    for graph in base, graphs_of(run("A helpdesk with an API and a database."))["conventional"]:
        ids = {component.id for component in graph.components}
        for connection in graph.connections:
            assert connection.source in ids and connection.target in ids
        for boundary in graph.trust_boundaries:
            assert set(boundary.component_ids) <= ids


def test_no_orphan_nodes_and_no_duplicate_edges():
    result = run(
        "A food delivery application with driver tracking over websockets, an ordering API, a relational "
        "database, a cache, object storage for receipts and push notifications for 100000 users."
    )
    for graph in result.architectures:
        linked = {connection.source for connection in graph.connections} | {
            connection.target for connection in graph.connections
        }
        assert not ({component.id for component in graph.components} - linked)
        pairs = [(connection.source, connection.target, connection.kind) for connection in graph.connections]
        assert len(pairs) == len(set(pairs))
        ids = [connection.id for connection in graph.connections]
        assert len(ids) == len(set(ids)), "edge ids must be stable and unique for React Flow"


def test_layout_is_deterministic_non_overlapping_and_left_to_right():
    first = run("A REST API with a database, a cache, object storage and a scheduled report job.")
    second = run("A REST API with a database, a cache, object storage and a scheduled report job.")
    for graph, twin in zip(first.architectures, second.architectures):
        assert graph.layout == twin.layout
        assert set(graph.layout) == {component.id for component in graph.components}
        boxes = [(graph.layout[component.id].x, graph.layout[component.id].y) for component in graph.components]
        for index, (x, y) in enumerate(boxes):
            for other_x, other_y in boxes[index + 1 :]:
                horizontal_gap = abs(x - other_x)
                vertical_gap = abs(y - other_y)
                assert horizontal_gap >= NODE_WIDTH + GAP_X - 1 or vertical_gap >= NODE_HEIGHT - 1, (
                    f"nodes overlap in {graph.id}: {(x, y)} vs {(other_x, other_y)}"
                )
    proposed = graphs_of(first)["proposed"]
    for connection in proposed.connections:
        source_layer = next(component for component in proposed.components if component.id == connection.source)
        target_layer = next(component for component in proposed.components if component.id == connection.target)
        if source_layer.layer != target_layer.layer:
            assert proposed.layout[source_layer.id].x <= proposed.layout[target_layer.id].x


def test_event_driven_work_gets_a_queue_and_a_worker():
    _, proposed = run(
        "A file processing pipeline: users upload large videos, the work is queued and background workers "
        "transcode each file for up to 30 minutes."
    ).architectures
    types = {component.type for component in proposed.components}
    assert LogicalComponentType.QUEUE in types
    assert {LogicalComponentType.WORKER, LogicalComponentType.BATCH_JOB, LogicalComponentType.REPORTING} & types
    worker = next(
        component
        for component in proposed.components
        if component.type in {LogicalComponentType.WORKER, LogicalComponentType.BATCH_JOB}
    )
    assert worker.traits.duration.value in {"long", "indefinite", "medium"}


def test_always_on_and_stateful_work_is_never_labelled_a_function():
    _, proposed = run(
        "A realtime collaboration backend that keeps websocket connections open for hours, holds the "
        "session in process memory and must always be running for 200000 concurrent users."
    ).architectures
    flagged = [
        component
        for component in proposed.components
        if component.traits.persistent_connections or component.traits.always_on or component.traits.stateful
    ]
    assert flagged
    for component in flagged:
        assert component.deployment_target is not DeploymentTarget.SERVERLESS_FUNCTION


def test_provider_selection_changes_labels_only():
    description = "An exam platform with an authenticated API, relational database, file storage and emails."
    aws = run(description)
    gcp = PIPELINE.run(
        AnalysisRequest(
            requirements=ApplicationRequirements(name="Architecture fixture", description=description),
            options=AnalysisOptions(use_ai=False, default_provider=CloudProvider.GCP),
        )
    )
    assert aws.default_provider is CloudProvider.AWS
    assert gcp.default_provider is CloudProvider.GCP
    for left, right in zip(aws.architectures, gcp.architectures):
        assert [component.id for component in left.components] == [component.id for component in right.components]
        assert left.connections == right.connections
    assert {component.mappings["aws"].service_name for component in graphs_of(aws)["proposed"].components} != {
        component.mappings["gcp"].service_name for component in graphs_of(gcp)["proposed"].components
    }
    assert aws.suitability.score == gcp.suitability.score


def test_pipeline_builds_valid_graphs_for_every_template():
    for identifier in (
        "college-attendance",
        "online-examination",
        "ecommerce-application",
        "food-delivery-platform",
        "file-processing-pipeline",
    ):
        result = PIPELINE.run(
            AnalysisRequest(requirements=requirements_for(identifier), options=AnalysisOptions(use_ai=False))
        )
        for graph in result.architectures:
            assert 4 <= len(graph.components) <= 24, f"{identifier}/{graph.id} has {len(graph.components)} nodes"
            assert len(graph.connections) >= len(graph.components) - 1
            assert graph.trust_boundaries, f"{identifier}/{graph.id} has no trust boundary"
        assert result.mapping_table


def test_truncation_keeps_the_spine_and_discloses_the_drop():
    result = PIPELINE.run(
        AnalysisRequest(
            requirements=requirements_for("ecommerce-application"),
            options=AnalysisOptions(use_ai=False, max_operations_per_view=6),
        )
    )
    proposed = graphs_of(result)["proposed"]
    assert len(proposed.components) <= 6
    assert {"client", "api"} <= {component.id for component in proposed.components}, "request path must survive"
    assert proposed.caveats and any("consolidated" in caveat for caveat in proposed.caveats)
