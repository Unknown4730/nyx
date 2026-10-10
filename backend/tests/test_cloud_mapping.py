"""Cloud catalogue mapping: names must exist, equivalence must be honest, switch is labels only."""

from __future__ import annotations

import json

import pytest

from app.schemas.analysis import AnalysisOptions, AnalysisRequest
from app.schemas.common import CloudProvider, LogicalComponentType
from app.schemas.requirements import ApplicationRequirements
from app.services.cloud_catalog import MAPPINGS, get_catalog
from app.services.pipeline import AnalysisPipeline
from app.services.templates import requirements_for

PROVIDERS = (CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE)
CATALOG = get_catalog()


def test_catalogue_loads_with_a_version_and_a_disclaimer():
    assert CATALOG.version == "2026.10"
    assert "not a pricing file" in CATALOG.disclaimer
    assert CATALOG.provider_keys() == list(PROVIDERS)
    summary = CATALOG.summary()
    assert summary["logical_component_types"] == len(LogicalComponentType)
    assert sum(summary["services_per_provider"].values()) == len(CATALOG.services)


def test_every_service_entry_is_complete_and_provider_consistent():
    for key, service in CATALOG.services.items():
        provider = key.split(".")[0]
        assert provider in {"aws", "gcp", "azure"}, key
        assert service["provider"] == provider
        assert service["name"]
        assert service["url"].startswith("https://")
        assert service["category"]
        assert service["serverless_class"] in {"fully_serverless", "managed", "serverful"}


def test_every_logical_type_maps_to_every_provider():
    assert set(MAPPINGS) == set(LogicalComponentType)
    for component_type, spec in MAPPINGS.items():
        for provider in PROVIDERS:
            key = getattr(spec, provider.value)
            assert key in CATALOG.services, f"{component_type.value}/{provider.value} -> {key} missing"
            mapping = CATALOG.mapping_for(component_type, provider)
            assert mapping is not None
            assert mapping.service_name == CATALOG.services[key]["name"]
            assert mapping.provider is provider
            assert mapping.reason
            assert mapping.confidence in {"high", "medium", "low"}


@pytest.mark.parametrize("component_type", sorted(item.value for item in LogicalComponentType))
def test_imperfect_equivalence_is_disclosed_on_the_mapping(component_type):
    spec = MAPPINGS[LogicalComponentType(component_type)]
    assert spec.equivalence in {"near", "partial", "conceptual"}
    for provider in PROVIDERS:
        mapping = CATALOG.mapping_for(LogicalComponentType(component_type), provider)
        if spec.equivalence == "near":
            assert mapping.confidence == "high"
        else:
            assert mapping.confidence == "medium"
            assert mapping.limitations or spec.differences


def test_undecided_provider_yields_no_mapping_rather_than_a_guess():
    assert CATALOG.mapping_for(LogicalComponentType.FUNCTION, CloudProvider.UNDECIDED) is None


def test_mapping_table_rows_cover_the_proposed_view():
    result = AnalysisPipeline().run(
        AnalysisRequest(requirements=requirements_for("online-examination"), options=AnalysisOptions(use_ai=False))
    )
    proposed = result.architectures[1]
    rows = result.mapping_table
    assert {row.component_id for row in rows} == {component.id for component in proposed.components}
    for row in rows:
        assert row.component_label and row.logical_type
        for mapping in (row.aws, row.gcp, row.azure):
            assert mapping is not None
            assert mapping.service_name and mapping.service_url.startswith("https://")
        if not row.one_to_one:
            assert row.notes, f"{row.component_id} claims imperfect equivalence without a note"
        else:
            assert MAPPINGS[LogicalComponentType(row.logical_type)].equivalence == "near"


def test_provider_choice_never_changes_topology_or_analysis():
    requirements = ApplicationRequirements(
        name="Mapping fixture",
        description="A ticketing API with a relational database, queue workers and email notifications for 5000 users.",
    )
    snapshots: dict[CloudProvider, tuple] = {}
    for provider in PROVIDERS:
        result = AnalysisPipeline().run(
            AnalysisRequest(
                requirements=requirements, options=AnalysisOptions(use_ai=False, default_provider=provider)
            )
        )
        graph = result.architectures[1]
        snapshots[provider] = (
            json.dumps([(component.id, component.type.value, component.layer) for component in graph.components]),
            json.dumps([connection.model_dump() for connection in graph.connections], sort_keys=True),
            json.dumps(result.suitability.model_dump(), sort_keys=True),
            json.dumps(result.cost.model_dump(), sort_keys=True),
            graph,
        )
    assert len({snapshots[provider][0] for provider in PROVIDERS}) == 1, "topology changed with the provider"
    assert len({snapshots[provider][1] for provider in PROVIDERS}) == 1, "edges changed with the provider"
    assert len({snapshots[provider][2] for provider in PROVIDERS}) == 1, "scores changed with the provider"
    assert len({snapshots[provider][3] for provider in PROVIDERS}) == 1, "cost changed with the provider"
    service_names = {
        provider: {component.mappings[provider.value].service_name for component in snapshots[provider][4].components}
        for provider in PROVIDERS
    }
    assert len({frozenset(names) for names in service_names.values()}) == 3, "each provider must label differently"


def test_preferred_provider_becomes_the_default_view():
    result = AnalysisPipeline().run(
        AnalysisRequest(
            requirements=ApplicationRequirements(
                name="Azure first",
                description="An internal helpdesk with a REST API, a relational database and attachments.",
                preferred_provider="azure",
            ),
            options=AnalysisOptions(use_ai=False),
        )
    )
    assert result.default_provider is CloudProvider.AZURE
    assert result.providers == list(PROVIDERS)
