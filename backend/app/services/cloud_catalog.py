"""Local, versioned multi-cloud service catalogue and mapping rules.

Design rules followed here:

* Mappings preserve the *logical function* of a component; they do not pretend
  every provider has an identical product.
* Where equivalence is only partial (for example time-series analytics or a
  filesystem share) that is recorded explicitly and surfaced in the UI.
* Every value in `LogicalComponentType` must be present in `MAPPINGS`; an
  import-time assertion enforces that, so a new component type can never be
  silently mapped to nothing.
* No pricing data lives here.  Service identity only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.schemas.architecture import ServiceMapping
from app.schemas.common import CloudProvider, LogicalComponentType

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "cloud_services.json"

EQUIVALENCE_NOTE = (
    "Mappings compare the logical role a component plays, not commercial product parity. "
    "Names, limits and region availability must be re-verified against provider documentation before implementation."
)

_UNMAPPED = object()


@dataclass(frozen=True)
class MappingSpec:
    """One logical component type -> three provider realizations."""

    aws: str
    gcp: str
    azure: str
    reason: str
    equivalence: str = "near"  # near | partial | conceptual
    differences: dict[CloudProvider, str] | None = None
    group: str = "general"


def _spec(
    aws: str,
    gcp: str,
    azure: str,
    reason: str,
    *,
    equivalence: str = "near",
    differences: dict[str, str] | None = None,
    group: str = "general",
) -> MappingSpec:
    return MappingSpec(
        aws=aws,
        gcp=gcp,
        azure=azure,
        reason=reason,
        equivalence=equivalence,
        differences={CloudProvider(key): value for key, value in (differences or {}).items()},
        group=group,
    )


MAPPINGS: dict[LogicalComponentType, MappingSpec] = {
    LogicalComponentType.CLIENT_WEB: _spec(
        "aws.cloudfront",
        "gcp.cloud_cdn",
        "azure.front_door",
        "Static web client assets are hosted and served from the provider edge network rather than from compute.",
        equivalence="partial",
        differences={
            "aws": "CloudFront is paired with S3 origins; Front Door combines CDN and global load balancing in one SKU.",
            "gcp": "Cloud CDN rides on the global load balancer; Media CDN is the alternative for large-scale video.",
            "azure": "Front Door Standard/Premium bundles CDN, WAF and global routing.",
        },
        group="edge",
    ),
    LogicalComponentType.CLIENT_MOBILE: _spec(
        "aws.api_gateway",
        "gcp.api_gateway",
        "azure.api_management",
        "Mobile clients talk to a versioned HTTP API surface; the client itself is out of cloud scope.",
        equivalence="partial",
        group="edge",
    ),
    LogicalComponentType.DNS: _spec(
        "aws.route53",
        "gcp.cloud_dns",
        "azure.azure_dns",
        "Public zone hosting and health-based routing is a directly comparable managed DNS capability.",
        group="edge",
    ),
    LogicalComponentType.CDN: _spec(
        "aws.cloudfront",
        "gcp.cloud_cdn",
        "azure.front_door",
        "Edge caching of assets and media reduces origin load in all three platforms.",
        equivalence="partial",
        group="edge",
    ),
    LogicalComponentType.LOAD_BALANCER: _spec(
        "aws.alb",
        "gcp.cloud_load_balancing",
        "azure.application_gateway",
        "Layer-7 distribution with TLS termination in front of resident compute.",
        equivalence="partial",
        differences={
            "gcp": "GCP's global forwarding rules are front-door style rather than a per-zone L4/7 LB instance.",
            "azure": "Application Gateway is the L7 choice; Azure Load Balancer is L4 only.",
        },
        group="networking",
    ),
    LogicalComponentType.API_GATEWAY: _spec(
        "aws.api_gateway",
        "gcp.api_gateway",
        "azure.api_management",
        "Front-door for HTTP APIs: routing, authorization, throttling, schema validation and a publishable contract.",
        equivalence="partial",
        differences={
            "gcp": "Cloud API Gateway is lightweight; policy-rich governance implies Apigee, which changes the cost shape.",
            "azure": "APIM's dedicated tiers are always-on VMs, so the consumption tier is the only serverless-like option.",
        },
        group="api",
    ),
    LogicalComponentType.WEB_SERVER: _spec(
        "aws.beanstalk",
        "gcp.compute_engine",
        "azure.app_service",
        "Conventional hosting of a server-rendered or monolithic web tier.",
        equivalence="partial",
        group="compute",
    ),
    LogicalComponentType.APP_SERVER: _spec(
        "aws.beanstalk",
        "gcp.cloud_run",
        "azure.app_service",
        "Resident application runtime that owns request handling and business logic.",
        equivalence="partial",
        differences={
            "gcp": "Cloud Run is container PaaS and can scale to zero, which is a different operational model from Beanstalk/App Service.",
        },
        group="compute",
    ),
    LogicalComponentType.CONTAINER_SERVICE: _spec(
        "aws.ecs_fargate",
        "gcp.cloud_run",
        "azure.container_apps",
        "Long-running or non-function-shaped workloads placed on a serverless-friendly container platform.",
        equivalence="near",
        differences={
            "azure": "Container Apps is the closer match; AKS is only needed when Kubernetes features are required.",
        },
        group="compute",
    ),
    LogicalComponentType.VIRTUAL_MACHINE: _spec(
        "aws.ec2",
        "gcp.compute_engine",
        "azure.virtual_machines",
        "Lift-and-shift compute when OS-level control or licensing cannot be abstracted away.",
        equivalence="near",
        group="compute",
    ),
    LogicalComponentType.FUNCTION: _spec(
        "aws.lambda",
        "gcp.cloud_run_functions",
        "azure.functions",
        "Short-lived, event-triggered code with per-invocation billing and no server management.",
        equivalence="partial",
        differences={
            "aws": "Lambda caps execution at 15 minutes and offers provisioned concurrency for latency-sensitive paths.",
            "gcp": "Cloud Run functions are built on Cloud Run: request timeout 540 s and a container-based model with faster start-up.",
            "azure": "The Consumption plan times out after 5 minutes by default; Premium is needed for VNet and warm instances.",
        },
        group="compute",
    ),
    LogicalComponentType.WORKER: _spec(
        "aws.ecs_fargate",
        "gcp.cloud_run_jobs",
        "azure.container_apps",
        "Background consumer of queued work, sized for the job rather than the request.",
        equivalence="partial",
        group="compute",
    ),
    LogicalComponentType.QUEUE: _spec(
        "aws.sqs",
        "gcp.cloud_tasks",
        "azure.service_bus",
        "Durable buffer between producers and consumers with retries and a dead-letter path.",
        equivalence="partial",
        differences={
            "gcp": "Cloud Tasks is task-oriented; a raw high-throughput queue is usually Pub/Sub instead.",
            "azure": "Service Bus Premium provides sessions, dedupe and transactions that SQS does not.",
        },
        group="messaging",
    ),
    LogicalComponentType.PUBSUB: _spec(
        "aws.sns",
        "gcp.pubsub",
        "azure.service_bus",
        "One-to-many event distribution to decoupled subscribers.",
        equivalence="partial",
        differences={
            "azure": "Service Bus topics or Event Grid are chosen depending on whether delivery is enterprise integration or resource events.",
        },
        group="messaging",
    ),
    LogicalComponentType.SCHEDULER: _spec(
        "aws.eventbridge_scheduler",
        "gcp.cloud_scheduler",
        "azure.logic_apps",
        "Cron-style triggering of periodic jobs without a resident scheduler process.",
        equivalence="near",
        differences={
            "azure": "Logic Apps recurrences or Functions timer triggers both cover this; there is no standalone cron product.",
        },
        group="scheduling",
    ),
    LogicalComponentType.BATCH_JOB: _spec(
        "aws.batch",
        "gcp.cloud_run_jobs",
        "azure.batch",
        "Sized, retried execution of a long job with input/output staging.",
        equivalence="partial",
        differences={
            "gcp": "Cloud Run jobs suit container-sized work; larger distributed jobs imply Dataflow or Dataproc.",
        },
        group="compute",
    ),
    LogicalComponentType.OBJECT_STORAGE: _spec(
        "aws.s3",
        "gcp.cloud_storage",
        "azure.blob_storage",
        "Durable, unbounded object storage for uploads, generated documents and media artefacts.",
        equivalence="near",
        group="storage",
    ),
    LogicalComponentType.BLOCK_STORAGE: _spec(
        "aws.ebs",
        "gcp.persistent_disk",
        "azure.managed_disks",
        "Block device attached to a specific VM; only meaningful in the conventional view.",
        equivalence="near",
        group="storage",
    ),
    LogicalComponentType.RELATIONAL_DB: _spec(
        "aws.rds",
        "gcp.cloud_sql",
        "azure.sql_database",
        "Transactional store with declarative constraints, backups and point-in-time recovery.",
        equivalence="near",
        differences={
            "aws": "Aurora separates storage from compute; connection scaling usually needs RDS Proxy.",
            "azure": "Azure SQL and PostgreSQL Flexible Server are both plausible depending on the engine choice.",
        },
        group="data",
    ),
    LogicalComponentType.DOCUMENT_DB: _spec(
        "aws.dynamodb",
        "gcp.firestore",
        "azure.cosmos_db",
        "Schema-flexible document store keyed by access pattern, with single-digit-ms reads.",
        equivalence="partial",
        differences={
            "gcp": "Firestore's cursor-based queries and no joins differ from a general document database.",
            "azure": "Cosmos DB offers multiple APIs and provisioned throughput units rather than per-request pricing by default.",
        },
        group="data",
    ),
    LogicalComponentType.KEY_VALUE_DB: _spec(
        "aws.dynamodb",
        "gcp.firestore",
        "azure.cosmos_db",
        "High-rate key/value access for session, token and short-lived state data.",
        equivalence="partial",
        group="data",
    ),
    LogicalComponentType.CACHE: _spec(
        "aws.elasticache",
        "gcp.memorystore",
        "azure.cache_redis",
        "In-memory store for hot reads, rate counters, locks and shared session state.",
        equivalence="near",
        group="data",
    ),
    LogicalComponentType.SEARCH_INDEX: _spec(
        "aws.opensearch",
        "gcp.vertex_ai_search",
        "azure.ai_search",
        "Inverted-index retrieval for search-as-you-type and faceted queries.",
        equivalence="partial",
        differences={
            "gcp": "Managed options (Vertex AI Search) differ from running Elasticsearch on GKE; choose based on query control needs.",
        },
        group="data",
    ),
    LogicalComponentType.TIME_SERIES_DB: _spec(
        "aws.timestream",
        "gcp.managed_prometheus",
        "azure.data_explorer",
        "Append-heavy metric and telemetry storage with retention tiering.",
        equivalence="conceptual",
        differences={
            "gcp": "There is no dedicated serverless TSDB; Prometheus plus BigQuery/Bigtable is the usual combination.",
            "azure": "Azure Time Series Insights is retired; Data Explorer is the current answer for high-volume time series.",
        },
        group="data",
    ),
    LogicalComponentType.DATA_WAREHOUSE: _spec(
        "aws.redshift",
        "gcp.bigquery",
        "azure.fabric_synapse",
        "Analytical store for reporting and periodic aggregation, fed from operational data.",
        equivalence="partial",
        differences={
            "gcp": "BigQuery's serverless slots model is the closest to pay-per-query; the others need capacity governance.",
        },
        group="analytics",
    ),
    LogicalComponentType.AUTH_IDENTITY: _spec(
        "aws.cognito",
        "gcp.identity_platform",
        "azure.entra_id",
        "Managed authentication, user store, token issuance and password policy enforcement.",
        equivalence="partial",
        differences={
            "azure": "Entra External ID covers customer identity; workload identity uses managed identities instead.",
            "gcp": "Identity Platform is Firebase-derived; Cloud Identity serves employees rather than customers.",
        },
        group="security",
    ),
    LogicalComponentType.SECRETS_MANAGER: _spec(
        "aws.secrets_manager",
        "gcp.secret_manager",
        "azure.key_vault",
        "Central storage and rotation of credentials, with IAM-scoped retrieval.",
        equivalence="near",
        group="security",
    ),
    LogicalComponentType.NOTIFICATION: _spec(
        "aws.ses",
        "gcp.firebase_messaging",
        "azure.notification_hubs",
        "Outbound email, SMS or push delivery to users.",
        equivalence="partial",
        differences={
            "aws": "Amazon SNS/Pinpoint are used for push, SES for email; the mapping assumes email-first notification.",
        },
        group="notification",
    ),
    LogicalComponentType.REPORTING: _spec(
        "aws.batch",
        "gcp.cloud_run_jobs",
        "azure.container_apps",
        "Document and report composition (PDF, CSV, certificates) executed as an asynchronous job.",
        equivalence="partial",
        differences={
            "aws": "Lambda can serve small renders; Step Functions orchestrates multi-stage rendering pipelines.",
        },
        group="compute",
    ),
    LogicalComponentType.ML_INFERENCE: _spec(
        "aws.batch",
        "gcp.vertex_ai",
        "azure.batch",
        "Model execution with accelerator or batch-oriented scheduling.",
        equivalence="conceptual",
        differences={
            "aws": "SageMaker is the dedicated service; it is named here rather than mapped because NYX does not model ML platforms in detail.",
        },
        group="ml",
    ),
    LogicalComponentType.DATA_STREAM: _spec(
        "aws.kinesis",
        "gcp.pubsub",
        "azure.event_hubs",
        "Ordered ingestion pipeline for continuous event data with replay windows.",
        equivalence="near",
        group="messaging",
    ),
    LogicalComponentType.MONITORING: _spec(
        "aws.cloudwatch",
        "gcp.cloud_monitoring",
        "azure.monitor",
        "Metrics, dashboards, and alerting on service-level indicators.",
        equivalence="near",
        group="operations",
    ),
    LogicalComponentType.LOGGING: _spec(
        "aws.lambda_powertools_logging",
        "gcp.cloud_logging",
        "azure.monitor",
        "Central, structured log capture with retention policy and audit trail.",
        equivalence="partial",
        group="operations",
    ),
    LogicalComponentType.CI_ARTIFACT_STORE: _spec(
        "aws.codeartifact",
        "gcp.cloud_build",
        "azure.devops_pipelines",
        "Build pipeline and artefact storage feeding deployment of functions and containers.",
        equivalence="partial",
        group="delivery",
    ),
    LogicalComponentType.BACKUP: _spec(
        "aws.backup",
        "gcp.backup_dr",
        "azure.backup",
        "Policy-driven snapshot and restore capability for stateful data stores.",
        equivalence="partial",
        group="operations",
    ),
}

class CloudCatalogService:
    """Reads the JSON service registry and resolves per-provider mappings."""

    def __init__(self, path: Path = CATALOG_PATH) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.version: str = raw["version"]
        self.disclaimer: str = raw["disclaimer"]
        self.services: dict[str, dict[str, object]] = raw["services"]
        self._validate()

    def _validate(self) -> None:
        missing = []
        for component_type, spec in MAPPINGS.items():
            for key in (spec.aws, spec.gcp, spec.azure):
                if key not in self.services:
                    missing.append(f"{component_type.value} -> {key}")
        if missing:
            raise RuntimeError("cloud_services.json is missing catalogue entries: " + ", ".join(missing))
        unmapped = [item.value for item in LogicalComponentType if item not in MAPPINGS]
        if unmapped:
            raise RuntimeError(f"Logical component types without a cloud mapping: {unmapped}")

    def service(self, key: str) -> dict[str, object]:
        return self.services[key]

    def mapping_for(self, component_type: LogicalComponentType, provider: CloudProvider) -> ServiceMapping | None:
        spec = MAPPINGS.get(component_type)
        if spec is None or provider == CloudProvider.UNDECIDED:
            return None
        key = getattr(spec, provider.value)
        entry = self.services[key]
        limitations = [str(item) for item in entry.get("limitations", [])]
        if spec.equivalence != "near":
            limitations.append(
                f"Equivalence with the other providers is {spec.equivalence}; see the comparison notes."
            )
        return ServiceMapping(
            provider=provider,
            service_name=str(entry["name"]),
            service_url=str(entry.get("url")) or None,
            category=str(entry.get("category", "general")),
            serverless_class=str(entry.get("serverless_class", "managed")),
            reason=spec.reason,
            limitations=limitations,
            differences=([spec.differences[provider]] if spec.differences and provider in spec.differences else []),
            confidence="high" if spec.equivalence == "near" else "medium",
            label=str(entry["name"]),
        )

    def provider_keys(self) -> list[CloudProvider]:
        return [CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE]

    def summary(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for entry in self.services.values():
            counts[str(entry["provider"])] = counts.get(str(entry["provider"]), 0) + 1
        return {
            "version": self.version,
            "disclaimer": self.disclaimer,
            "services_per_provider": counts,
            "logical_component_types": len(MAPPINGS),
            "equivalence_levels": sorted({spec.equivalence for spec in MAPPINGS.values()}),
            "note": EQUIVALENCE_NOTE,
        }


@lru_cache(maxsize=1)
def get_catalog() -> CloudCatalogService:
    return CloudCatalogService()
