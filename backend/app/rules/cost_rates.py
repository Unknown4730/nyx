"""Relative cost model coefficients.

These are *model constants*, not prices.  They preserve the relative magnitudes
between capacity-time, per-request execution, storage volume and request counts
so that a comparison is meaningful in shape.  1 RICU is defined as one small
always-on compute unit-month; every other coefficient is expressed against that
anchor.  Bumping `COST_MODEL_VERSION` is required whenever a number changes,
because the version appears in every cost report.
"""

from __future__ import annotations

from dataclasses import dataclass

COST_MODEL_VERSION = "2026.10"


@dataclass(frozen=True)
class Rates:
    """RICU coefficients used by the cost estimator."""

    # Resident capacity
    instance_small: float = 1.0
    instance_large: float = 2.4
    db_small: float = 0.8
    db_storage_gb: float = 0.004
    cache_small: float = 0.5
    search_small: float = 1.0
    lb_fixed: float = 0.12
    lb_per_million: float = 0.0067
    block_storage_gb: float = 0.0012

    # Execution-shaped usage
    per_million_invocations: float = 0.0067
    per_gb_second: float = 5.6e-7
    container_hour: float = 0.0022
    gateway_fixed: float = 0.12
    gateway_per_million: float = 0.033
    db_per_million_queries: float = 0.0067
    provisioned_concurrency: float = 0.35
    queue_per_million: float = 0.0133
    notification_per_thousand: float = 0.0033
    stream_per_million: float = 0.02
    stream_fixed: float = 0.06

    # Data plane
    object_storage_gb: float = 0.0008
    storage_requests_per_million: float = 0.00005
    egress_gb: float = 0.009
    backup_gb: float = 0.0017

    # Rails
    log_ingest_gb: float = 0.0167
    monitoring_fixed: float = 0.033
    secrets_fixed: float = 0.01
    identity_per_mau: float = 0.0033

    # Operational effort proxy (deliberately relative, not money)
    ops_manual_component: float = 0.35
    ops_managed_component: float = 0.12

    def describe(self) -> list[str]:
        return [
            "1 RICU = one small always-on compute unit-month (definition of the unit).",
            f"Function: {self.per_million_invocations} RICU per 1M invocations + {self.per_gb_second} RICU per GB-second.",
            f"Container/job runtime: {self.container_hour} RICU per hour.",
            f"Object storage: {self.object_storage_gb} RICU per GB-month (same in both models).",
            f"Operational load proxy: {self.ops_manual_component} vs {self.ops_managed_component} RICU per component-month.",
        ]
