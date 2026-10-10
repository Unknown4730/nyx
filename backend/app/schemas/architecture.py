"""Structured architecture representation shared by diagrams, tables and reports.

The graph is the single source of truth: the React Flow canvas, the provider
mapping table, the security analyzer, the cost estimator and the exported
report all read the same `ArchitectureGraph` objects.  There are no parallel
hard-coded diagrams anywhere in the project.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import (
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
    StrictModel,
    TransportSecurity,
)

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class NodePosition(StrictModel):
    x: float = 0.0
    y: float = 0.0


class ComponentTraits(StrictModel):
    """Execution characteristics that the suitability rules actually score."""

    runtime: ComponentRuntime = ComponentRuntime.REQUEST_RESPONSE
    stateful: bool = False
    always_on: bool = False
    event_triggered: bool = False
    duration: DurationProfile = DurationProfile.UNSPECIFIED
    persistent_connections: bool = False
    cpu_or_memory_intensive: bool = False
    gpu_required: bool = False
    custom_runtime: bool = False
    startup_latency_sensitive: bool = False
    connection_pool_pressure: bool = False
    needs_local_filesystem: bool = False
    data_intensity: str = "unspecified"  # low | medium | high | unspecified
    estimated_duration_ms: int | None = Field(default=None, ge=0)

    @field_validator("data_intensity")
    @classmethod
    def _known_intensity(cls, value: str) -> str:
        allowed = {"low", "medium", "high", "unspecified"}
        if value not in allowed:
            raise ValueError(f"data_intensity must be one of {sorted(allowed)}")
        return value


class SecurityEvidence(StrictModel):
    """Security-relevant facts recorded *about* the modelled component.

    `None` means the engine has no evidence either way, which the security
    analyzer must report as a verification gap instead of a vulnerability.
    """

    publicly_reachable: bool | None = None
    requires_authentication: bool | None = None
    authentication_scheme: str | None = Field(default=None, max_length=80)
    transport_security: TransportSecurity | None = None
    data_classification: DataClassification = DataClassification.UNSPECIFIED
    encryption_at_rest: bool | None = None
    iam_scope: IamScope = IamScope.UNSPECIFIED
    backup_policy: BackupPolicy = BackupPolicy.UNSPECIFIED
    secrets_handling: str | None = Field(default=None, max_length=80)
    input_validation: str | None = Field(default=None, max_length=80)
    audit_logging: bool | None = None

    @field_validator("authentication_scheme", "secrets_handling", "input_validation")
    @classmethod
    def _short(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split())[:80]


class ServiceMapping(StrictModel):
    """Provider-specific realization of one logical component."""

    provider: CloudProvider
    service_name: str
    service_url: str | None = None
    category: str = "general"
    serverless_class: str = "managed"  # fully_serverless | serverless_option | managed | serverful
    reason: str = ""
    limitations: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    confidence: str = "high"  # high | medium | low
    label: str | None = None

    @field_validator("serverless_class", "confidence", "category")
    @classmethod
    def _slug(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "_")
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned[:40]


class Component(StrictModel):
    id: str
    label: str
    type: LogicalComponentType
    tier: ComponentTier
    description: str = ""
    deployment_target: DeploymentTarget = DeploymentTarget.MANAGED_SERVICE
    traits: ComponentTraits = Field(default_factory=ComponentTraits)
    properties: dict[str, Any] = Field(default_factory=dict)
    security: SecurityEvidence = Field(default_factory=SecurityEvidence)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    mappings: dict[str, ServiceMapping] = Field(default_factory=dict)
    layer: int = 0
    order: int = 0

    @field_validator("id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        if not SAFE_ID.match(value):
            raise ValueError(f"unsafe component id: {value}")
        return value

    @field_validator("mappings")
    @classmethod
    def _keys_match_provider(cls, value: dict[str, ServiceMapping]) -> dict[str, ServiceMapping]:
        for key, mapping in value.items():
            if key != mapping.provider.value:
                raise ValueError(f"mapping key {key} does not match provider {mapping.provider}")
        return value

    def service_label(self, provider: CloudProvider | str) -> str | None:
        key = provider.value if isinstance(provider, CloudProvider) else str(provider)
        mapping = self.mappings.get(key)
        if mapping is None:
            return None
        return mapping.label or mapping.service_name


class Connection(StrictModel):
    id: str
    source: str
    target: str
    kind: ConnectionKind = ConnectionKind.SYNC_HTTP
    label: str | None = None
    protocol: str | None = None
    crosses_trust_boundary: bool = False
    async_delivery: bool = False
    optional: bool = False

    @field_validator("id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        if not SAFE_ID.match(value):
            raise ValueError(f"unsafe connection id: {value}")
        return value


class TrustBoundary(StrictModel):
    id: str
    label: str
    component_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class ArchitectureGraph(StrictModel):
    """One complete view (conventional or proposed) of the system."""

    id: str
    style: ArchitectureStyle
    title: str
    summary: str = ""
    components: list[Component] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    trust_boundaries: list[TrustBoundary] = Field(default_factory=list)
    layout: dict[str, NodePosition] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _referential_integrity(self) -> "ArchitectureGraph":
        ids = [component.id for component in self.components]
        duplicates = {item for item in ids if ids.count(item) > 1}
        if duplicates:
            raise ValueError(f"duplicate component ids: {sorted(duplicates)}")
        known = set(ids)
        for connection in self.connections:
            if connection.source not in known:
                raise ValueError(f"connection {connection.id} has unknown source {connection.source}")
            if connection.target not in known:
                raise ValueError(f"connection {connection.id} has unknown target {connection.target}")
        for boundary in self.trust_boundaries:
            missing = [item for item in boundary.component_ids if item not in known]
            if missing:
                raise ValueError(f"trust boundary {boundary.id} references unknown components {missing}")
        return self

    @property
    def component_ids(self) -> list[str]:
        return [component.id for component in self.components]

    def component(self, component_id: str) -> Component | None:
        for component in self.components:
            if component.id == component_id:
                return component
        return None


class ComponentInventoryItem(StrictModel):
    """Flat, report-friendly description of an identified component."""

    id: str
    label: str
    type: LogicalComponentType
    tier: ComponentTier
    description: str = ""
    source: str = "derived"  # user_asserted | inferred | template
    required: bool = True
    evidence: list[str] = Field(default_factory=list)


class ComponentPlan(StrictModel):
    """Internal hand-off between component identification and graph building."""

    type: LogicalComponentType
    id: str | None = None
    label: str | None = None
    description: str | None = None
    traits: ComponentTraits = Field(default_factory=ComponentTraits)
    security: SecurityEvidence = Field(default_factory=SecurityEvidence)
    evidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    alternatives: list[LogicalComponentType] = Field(default_factory=list)


class MappingRow(StrictModel):
    """One row of the multi-cloud comparison table."""

    component_id: str
    component_label: str
    logical_type: LogicalComponentType
    aws: ServiceMapping | None = None
    gcp: ServiceMapping | None = None
    azure: ServiceMapping | None = None
    one_to_one: bool = True
    notes: list[str] = Field(default_factory=list)


class CloudCatalog(StrictModel):
    """Versioned, locally stored service catalogue."""

    version: str = "2026.10"
    providers: list[CloudProvider] = Field(
        default_factory=lambda: [CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE]
    )
    entries: dict[LogicalComponentType, dict[CloudProvider, ServiceMapping]] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
