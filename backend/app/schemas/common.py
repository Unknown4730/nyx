"""Shared enums and base models for the NYX analysis schema.

The enums in this module form the contract between the backend rules engine and
the frontend.  Every value here is a plain string so that the JSON payload
stays readable and stable across the API boundary.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "nyx.analysis/1"


class StrEnum(str, Enum):
    """String enum compatible with Python 3.10 (``enum.StrEnum`` is 3.11+)."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @classmethod
    def values(cls) -> list[str]:
        return [member.value for member in cls]


class StrictModel(BaseModel):
    """Base model: unknown keys are rejected so schema drift fails loudly."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False, str_strip_whitespace=True)


class LenientModel(BaseModel):
    """Base model for AI-authored payloads: unknown keys are ignored."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Requirements input enums
# ---------------------------------------------------------------------------


class FieldBasis(StrEnum):
    """Where a value came from.  Drives the "user-provided vs inferred" UI."""

    USER = "user_provided"
    TEMPLATE = "template"
    INFERRED = "inferred"
    AI = "ai_assisted"
    DEFAULT = "engine_default"
    UNSPECIFIED = "unspecified"


class ApplicationType(StrEnum):
    WEB_APP = "web_app"
    MOBILE_BACKEND = "mobile_backend"
    API_SERVICE = "api_service"
    CONTENT_SITE = "content_site"
    ECOMMERCE = "ecommerce"
    LEARNING_PLATFORM = "learning_platform"
    EXAMINATION_PLATFORM = "examination_platform"
    LOGISTICS_MARKETPLACE = "logistics_marketplace"
    BATCH_PROCESSING = "batch_processing"
    DATA_PIPELINE = "data_pipeline"
    REALTIME_COLLABORATION = "realtime_collaboration"
    STREAMING_MEDIA = "streaming_media"
    IOT_INGESTION = "iot_ingestion"
    ML_INFERENCE = "ml_inference"
    INTERNAL_TOOL = "internal_tool"
    UNKNOWN = "unknown"


class TrafficPattern(StrEnum):
    STEADY = "steady"
    DIURNAL = "diurnal"
    SPIKY_EVENT = "spiky_event_driven"
    BURSTY_SCHEDULED = "bursty_scheduled"
    UNPREDICTABLE = "unpredictable"
    UNKNOWN = "unknown"


class AvailabilityExpectation(StrEnum):
    BEST_EFFORT = "best_effort"
    STANDARD = "standard"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class BudgetPreference(StrEnum):
    MINIMIZE = "minimize"
    BALANCED = "balanced"
    PERFORMANCE_FIRST = "performance_first"
    UNKNOWN = "unknown"


class DataStorageKind(StrEnum):
    RELATIONAL = "relational"
    DOCUMENT = "document"
    KEY_VALUE = "key_value"
    OBJECT_STORAGE = "object_storage"
    FILE_SHARE = "file_share"
    CACHE_SESSION = "cache_session"
    SEARCH_INDEX = "search_index"
    TIME_SERIES = "time_series"
    ANALYTICAL_WAREHOUSE = "analytical_warehouse"
    QUEUE_OR_LOG = "queue_or_log"
    NONE = "none"
    UNKNOWN = "unknown"


class CloudProvider(StrEnum):
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    UNDECIDED = "undecided"


# ---------------------------------------------------------------------------
# Architecture enums
# ---------------------------------------------------------------------------


class LogicalComponentType(StrEnum):
    """The closed vocabulary of logical components the engine may emit.

    Keeping this list closed is what allows the visualization layer to reject
    anything the model invented rather than trusting it blindly.
    """

    CLIENT_WEB = "client_web"
    CLIENT_MOBILE = "client_mobile"
    DNS = "dns"
    CDN = "cdn"
    LOAD_BALANCER = "load_balancer"
    API_GATEWAY = "api_gateway"
    WEB_SERVER = "web_server"
    APP_SERVER = "app_server"
    CONTAINER_SERVICE = "container_service"
    VIRTUAL_MACHINE = "virtual_machine"
    FUNCTION = "function"
    WORKER = "worker"
    QUEUE = "queue"
    PUBSUB = "pubsub"
    SCHEDULER = "scheduler"
    BATCH_JOB = "batch_job"
    OBJECT_STORAGE = "object_storage"
    BLOCK_STORAGE = "block_storage"
    RELATIONAL_DB = "relational_db"
    DOCUMENT_DB = "document_db"
    KEY_VALUE_DB = "key_value_db"
    CACHE = "cache"
    SEARCH_INDEX = "search_index"
    TIME_SERIES_DB = "time_series_db"
    DATA_WAREHOUSE = "data_warehouse"
    AUTH_IDENTITY = "auth_identity"
    SECRETS_MANAGER = "secrets_manager"
    NOTIFICATION = "notification"
    REPORTING = "reporting"
    ML_INFERENCE = "ml_inference"
    DATA_STREAM = "data_stream"
    MONITORING = "monitoring"
    LOGGING = "logging"
    CI_ARTIFACT_STORE = "ci_artifact_store"
    BACKUP = "backup"


class ComponentTier(StrEnum):
    EDGE = "edge"
    PRESENTATION = "presentation"
    APPLICATION = "application"
    INTEGRATION = "integration"
    PROCESSING = "processing"
    DATA = "data"
    SECURITY = "security"
    OPERATIONS = "operations"


class ComponentRuntime(StrEnum):
    REQUEST_RESPONSE = "request_response"
    EVENT_TRIGGERED = "event_triggered"
    LONG_RUNNING = "long_running"
    STREAMING = "streaming"
    SCHEDULED_BATCH = "scheduled_batch"
    ALWAYS_ON = "always_on"
    STATIC = "static"
    MANAGED = "managed"


class DurationProfile(StrEnum):
    SUB_SECOND = "sub_second"
    FEW_SECONDS = "few_seconds"
    MINUTES = "minutes"
    INDEFINITE = "indefinite"
    UNSPECIFIED = "unspecified"


class ConnectionKind(StrEnum):
    SYNC_HTTP = "sync_http"
    ASYNC_EVENT = "async_event"
    DATA_READ = "data_read"
    DATA_WRITE = "data_write"
    STREAM = "stream"
    SCHEDULE = "schedule"
    MANAGEMENT = "management"
    STATIC_ASSET = "static_asset"


class ArchitectureStyle(StrEnum):
    CONVENTIONAL = "conventional"
    SERVERLESS = "serverless"
    HYBRID = "hybrid"


class DeploymentTarget(StrEnum):
    SERVERLESS_FUNCTION = "serverless_function"
    MANAGED_SERVICE = "managed_service"
    CONTAINER = "container"
    VIRTUAL_MACHINE = "virtual_machine"
    RETAIN_AS_IS = "retain_as_is"
    REVIEW_REQUIRED = "review_required"


class SuitabilityOutcome(StrEnum):
    STRONG_CANDIDATE = "strong_candidate"
    SUITABLE_WITH_MODIFICATIONS = "suitable_with_modifications"
    PARTIAL_ADOPTION = "partial_serverless_adoption"
    FURTHER_ASSESSMENT = "further_assessment_required"
    POOR_CANDIDATE = "poor_candidate_for_proposed_serverless"


class RecommendedPattern(StrEnum):
    SERVERLESS_FIRST = "serverless_first"
    SERVERLESS_WHERE_SUITABLE = "serverless_where_suitable"
    HYBRID = "hybrid"
    MANAGED_CONTAINER = "managed_container"
    CONVENTIONAL_KEEP = "conventional_keep"
    FURTHER_ASSESSMENT = "further_assessment"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingCertainty(StrEnum):
    """Distinguishes evidence-backed findings from gaps that need review."""

    CONFIRMED_IN_MODEL = "confirmed_in_model"
    INFERRED_RISK = "inferred_risk"
    NEEDS_VERIFICATION = "needs_verification"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    NONE = "none"
    UNSPECIFIED = "unspecified"


class TransportSecurity(StrEnum):
    TLS_ENFORCED = "tls_enforced"
    TLS_OPTIONAL = "tls_optional"
    NONE = "none"
    UNSPECIFIED = "unspecified"


class IamScope(StrEnum):
    SCOPED = "scoped"
    MANAGED_DEFAULT = "managed_default"
    BROAD = "broad"
    NONE = "none"
    UNSPECIFIED = "unspecified"


class BackupPolicy(StrEnum):
    AUTOMATED = "automated"
    MANUAL = "manual"
    NONE = "none"
    UNSPECIFIED = "unspecified"


class CostCategory(StrEnum):
    FIXED = "fixed"
    VARIABLE = "variable"
    OPERATIONAL = "operational"


class EffortLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    FURTHER_ASSESSMENT = "further_assessment_required"


class EngineMode(StrEnum):
    DETERMINISTIC = "deterministic_rules"
    AI_ASSISTED = "ai_assisted"


class AiAttemptStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    DISABLED_BY_REQUEST = "disabled_by_request"
    SUCCESS = "success"
    CACHED = "cached"
    FAILED_VALIDATION = "failed_validation"
    FAILED_PROVIDER = "failed_provider"
    FAILED_TIMEOUT = "failed_timeout"
    FAILED_EMPTY = "failed_empty"
    FAILED_RATE_LIMIT = "failed_rate_limit"


class ProjectKind(StrEnum):
    USER = "user_project"
    EXAMPLE = "example_project"
