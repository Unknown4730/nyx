"""Deterministic lexical rules that turn a free-text description into signals.

Every rule is a (pattern, effect) pair evaluated over the lower-cased user
text.  A rule may only set a signal that is not already asserted by the user or
a template, and every rule that fires is recorded in `matched_rules` so that a
test can assert *why* a value appeared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from app.schemas.common import (
    ApplicationType,
    AvailabilityExpectation,
    BudgetPreference,
    DataStorageKind,
    TrafficPattern,
)
from app.schemas.requirements import RequirementSignals

# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_MULTIPLIERS = {
    "": 1,
    "k": 1_000,
    "thousand": 1_000,
    "lakh": 100_000,
    "lac": 100_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "crore": 10_000_000,
}

_NOUNS = (
    r"(?:students?|users?|customers?|people|person|employees?|staff|members?|players?|clients?|accounts?|citizens?"
    r"|passengers?|drivers?|riders?|subscribers?|patients?|candidates?|children|registrants?|attendees?"
    r"|teachers?|faculty|admins?|administrators?|operators?|agents?|moderators?|inspectors?|examiners?"
    r"|shoppers?|buyers?|sellers?|vendors?|suppliers?|couriers?|sensors?|devices?|terminals?|endpoints?)"
)

USER_COUNT_RE = re.compile(
    rf"(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|lakh|lac|million|crore)?\s*"
    rf"(?:\+|approx(?:imately)?|around|about|more than|over|up to)?\s*(?:[a-z]{{2,14}}[\s-]{{0,1}}){{0,3}}?{_NOUNS}"
)
USER_COUNT_REVERSE_RE = re.compile(
    rf"{_NOUNS}\s*(?:base|pool)?\s*(?:of|:)?\s*(?:approx(?:imately)?|around|about|more than|over|up to)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|lakh|lac|million|crore)?"
)
REQUESTS_PER_DAY_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\s*"
    r"(requests?|calls?|api calls?|http calls?|events?|uploads?|page ?views?|read ops?)\s*(?:per|a|/)\s*day"
)
REQUESTS_PER_MONTH_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\s*"
    r"(requests?|calls?|api calls?|events?|uploads?|page ?views?)\s*(?:per|a|/)\s*(?:month|months)"
)
MINUTES_RE = re.compile(r"(?:takes?|runs?|lasts?|up to|about|around)?\s*(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?|seconds?|secs?)\b")
SIZE_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(kb|mb|gb|tb|pb)\b")
LATENCY_RE = re.compile(r"(?:under|within|less than|about|around|p95 of|p99 of|under about)?\s*(\d[\d,]*)\s*(ms|milliseconds?|seconds?)\b(?:\s*(?:response|latency|p95|p99))?")
SLA_RE = re.compile(r"(\d{2}(?:\.\d+)?)\s*%")
LATENCY_BUDGET_RE = re.compile(r"(?:latency|response time)\s*(?:budget|target|of|under|within)?\s*(?:of)?\s*(\d[\d,]*)\s*(ms|milliseconds?)")

# Business transactions (orders, submissions) are *not* request volume: one order
# implies many requests.  Only request-shaped nouns are trusted for volume.
BUSINESS_EVENT_PER_DAY_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\s*(orders?|submissions?|transactions?|bookings?)\s*(?:per|a|/)\s*day"
)
REQUESTS_PER_BUSINESS_EVENT = 12


def _to_number(digits: str, multiplier: str | None) -> float:
    value = float(digits.replace(",", ""))
    return value * _MULTIPLIERS.get((multiplier or "").lower(), 1)


@dataclass
class RuleHit:
    """A rule that fired, with the field it set."""

    rule_id: str
    field: str
    evidence: str


@dataclass
class KeywordRule:
    rule_id: str
    pattern: re.Pattern[str]
    field: str
    value: object
    evidence: str = ""
    only_if_absent: bool = True


def _rx(*words: str) -> re.Pattern[str]:
    """Build a whole-word alternation tolerant of plurals and verb inflections.

    `session` therefore matches both "session" and "sessions" without turning
    multi-word phrases such as "cpu intensive" into broken patterns.
    """
    alternatives: list[str] = []
    for word in words:
        tokens = word.split(" ")
        rendered: list[str] = []
        for index, token in enumerate(tokens):
            if any(character in token for character in ".+*?[](){}|\\^$"):
                rendered.append(re.escape(token))
                continue
            safe = re.escape(token)
            if index == len(tokens) - 1 and token.isalpha() and not token.endswith("s"):
                safe += "(?:s|es|ing|ed|d)?"
            rendered.append(safe)
        alternatives.append(r"\s+".join(rendered))
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b")


# ---------------------------------------------------------------------------
# Lexicon tables
# ---------------------------------------------------------------------------

TRAFFIC_RULES: list[KeywordRule] = [
    KeywordRule("traffic.spiky", _rx("spike", "spikes", "spiky", "surge", "surges", "burst", "bursts",
                                      "increases significantly", "peak during", "peaks during", "flash sale",
                                      "result day", "results day", "exam window", "exam hours", "during exams",
                                      "during examination", "during examinations", "test window", "on result",
                                      "voting window", "admission window", "seasonal", "rush hour"),
                "traffic_pattern", TrafficPattern.SPIKY_EVENT, "description mentions sudden surges or windowed peaks"),
    KeywordRule("traffic.scheduled", _rx("nightly", "weekly job", "monthly", "end of day", "end of month",
                                         "cron", "scheduled", "schedule", "batch at", "every hour", "daily at",
                                         "overnight", "after hours"),
                "traffic_pattern", TrafficPattern.BURSTY_SCHEDULED, "description mentions time-scheduled processing"),
    KeywordRule("traffic.diurnal", _rx("business hours", "office hours", "daytime", "weekday", "class hours",
                                       "9 to 5", "morning", "evening peak", "lunch"),
                "traffic_pattern", TrafficPattern.DIURNAL, "usage follows a daily rhythm"),
    KeywordRule("traffic.steady", _rx("steady", "constant", "even load", "predictable traffic", "24/7",
                                      "round the clock", "continuous traffic"),
                "traffic_pattern", TrafficPattern.STEADY, "description states load is flat and predictable"),
    KeywordRule("traffic.unpredictable", _rx("unpredictable", "viral", "hard to forecast", "no idea when",
                                             "spikes randomly", "uncertain traffic"),
                "traffic_pattern", TrafficPattern.UNPREDICTABLE, "load is explicitly hard to forecast"),
]

TYPE_RULES: list[tuple[re.Pattern[str], ApplicationType]] = [
    (_rx("examination", "exam", "online test", "proctoring", "mcq", "question paper"), ApplicationType.EXAMINATION_PLATFORM),
    (_rx("attendance", "roll call", "mark presence", "biometric", "timetable", "result processing", "student portal",
         "learning management", "lms", "assignment", "course enrolment"), ApplicationType.LEARNING_PLATFORM),
    (_rx("e-commerce", "ecommerce", "shopping", "cart", "checkout", "product catalog", "order placement", "seller"),
     ApplicationType.ECOMMERCE),
    (_rx("food delivery", "rider", "restaurant", "order tracking", "delivery partner", "grocery delivery"),
     ApplicationType.LOGISTICS_MARKETPLACE),
    (_rx("file processing", "pipeline", "etl", "ingest", "transform", "batch processing", "data processing"),
     ApplicationType.BATCH_PROCESSING),
    (_rx("chat", "messaging", "realtime collaboration", "video call", "presence"),
     ApplicationType.REALTIME_COLLABORATION),
    (_rx("video streaming", "live streaming", "vod", "media player"), ApplicationType.STREAMING_MEDIA),
    (_rx("iot", "sensor", "device telemetry", "fleet tracking", "gps tracker"), ApplicationType.IOT_INGESTION),
    (_rx("mobile app", "android", "ios", "mobile backend"), ApplicationType.MOBILE_BACKEND),
    (_rx("public api", "rest api for", "developer platform", "webhook"), ApplicationType.API_SERVICE),
    (_rx("portfolio", "brochure site", "content site", "blog", "news site", "cms"), ApplicationType.CONTENT_SITE),
    (_rx("model serving", "inference", "ml model", "machine learning service"), ApplicationType.ML_INFERENCE),
    (_rx("internal tool", "admin panel", "back office", "staff only"), ApplicationType.INTERNAL_TOOL),
]

BOOL_RULES: list[KeywordRule] = [
    # Execution shape
    KeywordRule("signal.long_running", _rx("transcod", "encoding", "video processing", "rendering", "renders",
                                           "image processing pipeline", "ml training", "model training", "simulation",
                                           "compilation", "zip all", "bulk export", "large report generation"),
                "long_running_jobs", True, "long-running processing step described"),
    KeywordRule("signal.no_long_running", _rx("stateless api", "quick lookups", "simple crud"), "long_running_jobs",
                False, "workload described as short stateless operations"),
    KeywordRule("signal.cpu_intensive", _rx("cpu intensive", "compute intensive", "memory heavy", "heavy image",
                                            "resize", "ffmpeg", "opencv", "pandas", "numerical", "compression",
                                            "large csv", "video frames"),
                "cpu_or_memory_intensive", True, "compute/memory-heavy processing identified"),
    KeywordRule("signal.gpu", _rx("gpu", "cuda", "deep learning", "llm inference", "tensorflow", "pytorch",
                                  "stable diffusion"), "gpu_required", True, "GPU acceleration requested"),
    KeywordRule("signal.custom_runtime", _rx("ffmpeg", "opencv", "latex", "chromium", "headless browser",
                                             "phantomjs", "imagemagick", "native library", ".net framework",
                                             "oracle client", "custom python packages"),
                "custom_runtime_required", True, "custom runtime or native dependency named"),
    # Trigger model
    KeywordRule("signal.event_driven", _rx("when a file is uploaded", "on upload", "whenever", "trigger", "event",
                                           "react to", "as soon as", "notification is sent when", "message arrives",
                                           "queue", "subscriber"), "event_driven", True,
                "work is triggered by an event rather than a waiting client"),
    KeywordRule("signal.scheduled_batch", _rx("nightly", "daily at", "weekly", "cron", "scheduled job", "end of day",
                                              "every month", "monthly report", "at 5 pm", "over the weekend"),
                "scheduled_batch", True, "time-scheduled processing described"),
    KeywordRule("signal.streaming", _rx("stream", "streaming ingestion", "clickstream", "telemetry feed",
                                        "event stream", "log feed", "continuous data"), "streaming_ingestion", True,
                "continuous event or data stream described"),
    KeywordRule("signal.persistent", _rx("chat", "websocket", "web socket", "socket.io", "real-time updates",
                                          "live updates", "keep-alive connection", "long-lived connection",
                                          "sse", "server-sent events", "live tracking"),
                "persistent_connections", True, "protocol requiring long-lived connections"),
    # Coupling
    KeywordRule("signal.stateful_sessions", _rx("session", "shopping cart", "sticky", "server-side state",
                                                "holds state", "stateful", "in-memory state"),
                "stateful_sessions", True, "server-side session or in-memory state mentioned"),
    KeywordRule("signal.stateless", _rx("jwt", "stateless", "token based auth", "signed token"), "stateful_sessions",
                False, "stateless/token-based session handling mentioned"),
    KeywordRule("signal.locking", _rx("seat locking", "concurrent booking", "race condition", "inventory lock",
                                      "reserve seats", "lock the seat", "last seat", "double booking",
                                      "concurrent submission"), "shared_locking_required", True,
                "coordination or locking between concurrent workers required"),
    KeywordRule("signal.transactional", _rx("payment", "order", "booking", "transaction", "inventory", "wallet",
                                            "refund", "debit", "credit"), "transactional_writes", True,
                "transactional write path identified"),
    KeywordRule("signal.fanout_reads", _rx("leaderboard", "everyone views", "results page", "browse catalog",
                                           "product listing", "ranking", "high read"), "high_fanout_reads", True,
                "read fan-out larger than write volume"),
    # Data plane
    KeywordRule("signal.relational", _rx("grades", "attendance records", "marks", "student records", "orders",
                                         "inventory", "relational", "sql", "foreign key", "enrollment", "booking",
                                         "accounts", "audit"), "relational_data", True,
                "relational/record-oriented data described"),
    KeywordRule("signal.document", _rx("survey", "questionnaire", "free-form", "flexible schema", "json documents",
                                        "question bank", "metadata", "form responses", "profile"),
                "document_data", True, "schema-flexible documents described"),
    KeywordRule("signal.key_value", _rx("session store", "cache", "token store", "rate limit counter", "key value",
                                        "short-lived state"), "key_value_data", True, "key/value access pattern"),
    KeywordRule("signal.object_storage", _rx("upload", "file", "pdf", "image", "photo", "certificate", "invoice",
                                            "attachment", "video", "audio", "document storage", "export", "csv",
                                            "receipt"), "object_storage_needed", True,
                "files or generated artefacts must be stored"),
    KeywordRule("signal.filesystem", _rx("shared folder", "network drive", "smb", "nfs", "file system", "posix",
                                         "directory structure", "mounted drive"), "filesystem_semantics_required",
                True, "filesystem semantics rather than object storage"),
    KeywordRule("signal.search", _rx("search", "full text", "faceted", "filter products", "find courses",
                                     "autocomplete"), "search_needed", True, "search or browse-by-text requirement"),
    KeywordRule("signal.cache", _rx("cache", "cached", "redis", "frequently accessed", "hot data"), "cache_needed",
                True, "caching requirement identified"),
    KeywordRule("signal.messaging", _rx("queue", "job queue", "background job", "worker", "asynchronous", "pubsub",
                                        "topic", "message"), "messaging_needed", True,
                "queueing or messaging between components"),
    KeywordRule("signal.generated_files", _rx("certificate", "generate pdf", "pdf certificate", "invoice",
                                              "report", "download", "receipt", "transcript", "scorecard"),
                "generated_files", True, "application generates file artefacts"),
    KeywordRule("signal.sensitive", _rx("grades", "marks", "personal", "pii", "payment", "medical", "health",
                                        "student records", "aadhaar", "password", "date of birth", "contact details",
                                        "salary"), "sensitive_data", True, "sensitive or personal data involved"),
    KeywordRule("signal.audit", _rx("audit", "who changed", "tamper", "immutab", "compliance log", "legal hold",
                                    "retain records"), "requires_audit_trail", True, "audit-trail requirement stated"),
    KeywordRule("signal.notification", _rx("email", "sms", "whatsapp", "notify", "notification", "reminder", "push",
                                           "alert the student", "otp"), "notification_required", True,
                "outbound notification required"),
    KeywordRule("signal.reporting", _rx("pdf", "certificate", "report", "invoice", "transcript", "scorecard",
                                        "statement"), "pdf_or_reporting", True, "document/report generation required"),
    KeywordRule("signal.public", _rx("public", "internet facing", "students can access", "anyone", "open api",
                                      "mobile app", "guests"), "public_internet_facing", True,
                "component must be reachable from the public internet"),
    KeywordRule("signal.multi_tenant", _rx("multiple colleges", "multi-tenant", "multi tenant", "branches",
                                          "franchise", "each school has", "per institution"), "multi_tenant", True,
                "multiple isolated tenants described"),
    KeywordRule("signal.latency_sensitive", _rx("sub-second", "real-time bidding", "must feel instant",
                                                "low latency is critical", "first paint", "latency sensitive",
                                                "cold start"), "cold_start_sensitive", True,
                "first-request latency explicitly matters"),
    KeywordRule("signal.on_prem", _rx("on-premise", "on premises", "our own server", "data centre", "datacenter",
                                      "existing server", "migrating from", "current system runs on", "legacy"),
                "existing_on_prem_assets", True, "existing self-hosted assets to migrate"),
    KeywordRule("signal.business_hours_only", _rx("only during class", "office hours only", "used only during exams",
                                                  "during working hours", "campus hours"), "business_hours_only",
                True, "usage confined to defined windows"),
    KeywordRule("signal.backup", _rx("backup", "back up", "recovery", "rpo", "should not lose", "restore",
                                     "point in time"), "backup_expectation_days", None, "backup/recovery expectation stated"),
]

STORAGE_KIND_RULES: list[tuple[re.Pattern[str], DataStorageKind]] = [
    (_rx("grades", "attendance", "records", "orders", "inventory", "enrollment", "marks", "transactions"),
     DataStorageKind.RELATIONAL),
    (_rx("survey", "question bank", "form", "flexible", "profile", "json"), DataStorageKind.DOCUMENT),
    (_rx("file", "pdf", "image", "photo", "video", "upload", "attachment", "certificate"),
     DataStorageKind.OBJECT_STORAGE),
    (_rx("session", "cache", "leaderboard", "rate limit", "otp"), DataStorageKind.CACHE_SESSION),
    (_rx("search", "autocomplete", "full text", "filter catalog"), DataStorageKind.SEARCH_INDEX),
    (_rx("sensor", "telemetry", "gps", "tracking", "heartbeat"), DataStorageKind.TIME_SERIES),
    (_rx("analytics", "reporting", "dashboard", "history", "warehouse"), DataStorageKind.ANALYTICAL_WAREHOUSE),
    (_rx("queue", "job", "background task", "notification"), DataStorageKind.QUEUE_OR_LOG),
    (_rx("shared folder", "network drive", "smb", "nfs"), DataStorageKind.FILE_SHARE),
]

AVAILABILITY_RULES: list[tuple[re.Pattern[str], AvailabilityExpectation]] = [
    (_rx("zero downtime", "must not go down", "mission critical", "99.99", "never down", "critical availability"),
     AvailabilityExpectation.CRITICAL),
    (_rx("highly available", "99.9", "no downtime during exams", "redundant"), AvailabilityExpectation.HIGH),
    (_rx("best effort", "internal only", "academic project", "nice to have", "99%", "during business hours"),
     AvailabilityExpectation.BEST_EFFORT),
]

BUDGET_RULES: list[tuple[re.Pattern[str], BudgetPreference]] = [
    (_rx("cheap", "lowest cost", "budget", "free tier", "minimize cost", "no money", "limited funds", "cost saving"),
     BudgetPreference.MINIMIZE),
    (_rx("performance first", "fastest possible", "cost is no issue", "maximise throughput"),
     BudgetPreference.PERFORMANCE_FIRST),
]

COMPLIANCE_RE = re.compile(r"\b(ferpa|gdpr|hipaa|pci[- ]?dss|sox|dpdp|iso ?27001|soc ?2|sevzo)\b")
INTEGRATION_RE = re.compile(
    r"\b(razorpay|stripe|paypal|upi|gpay|phonepe|paytm|sendgrid|twilio|firebase|google maps|mapbox|whatsapp|"
    r"zoom|meet|gcs|s3 bucket|slack|jira|github)\b"
)


# ---------------------------------------------------------------------------
# Derived planning constants (documented, used by the cost model too)
# ---------------------------------------------------------------------------

SESSIONS_PER_USER_BY_TYPE: dict[ApplicationType, float] = {
    ApplicationType.EXAMINATION_PLATFORM: 1.1,
    ApplicationType.LEARNING_PLATFORM: 1.4,
    ApplicationType.ECOMMERCE: 1.8,
    ApplicationType.LOGISTICS_MARKETPLACE: 3.0,
    ApplicationType.BATCH_PROCESSING: 0.4,
    ApplicationType.DATA_PIPELINE: 0.5,
    ApplicationType.REALTIME_COLLABORATION: 4.0,
    ApplicationType.STREAMING_MEDIA: 2.2,
    ApplicationType.IOT_INGESTION: 6.0,
    ApplicationType.MOBILE_BACKEND: 2.5,
    ApplicationType.API_SERVICE: 2.0,
    ApplicationType.CONTENT_SITE: 1.2,
    ApplicationType.ML_INFERENCE: 1.5,
    ApplicationType.INTERNAL_TOOL: 1.3,
    ApplicationType.WEB_APP: 1.6,
    ApplicationType.UNKNOWN: 1.5,
}

REQUESTS_PER_SESSION = 9
PEAK_RATIO_BY_TRAFFIC: dict[TrafficPattern, float] = {
    TrafficPattern.SPIKY_EVENT: 3.2,
    TrafficPattern.BURSTY_SCHEDULED: 2.4,
    TrafficPattern.DIURNAL: 1.9,
    TrafficPattern.UNPREDICTABLE: 2.6,
    TrafficPattern.STEADY: 1.15,
    TrafficPattern.UNKNOWN: 1.6,
}
CONCURRENCY_SHARE_BY_TRAFFIC: dict[TrafficPattern, float] = {
    TrafficPattern.SPIKY_EVENT: 0.30,
    TrafficPattern.BURSTY_SCHEDULED: 0.20,
    TrafficPattern.DIURNAL: 0.14,
    TrafficPattern.UNPREDICTABLE: 0.22,
    TrafficPattern.STEADY: 0.09,
    TrafficPattern.UNKNOWN: 0.12,
}
ACTIVE_DAYS_PER_MONTH = 26
HOURS_PER_DAY = 24.0


def parse_user_count(text: str) -> int | None:
    text = text.lower()
    for regex in (USER_COUNT_RE, USER_COUNT_REVERSE_RE):
        match = regex.search(text)
        if match:
            groups = match.groups()
            digits = next((g for g in groups if g and re.match(r"^\d", g)), None)
            multiplier = next((g for g in groups if g and re.match(r"^[a-zA-Z]+$", g) and g.lower() in _MULTIPLIERS),
                              None)
            if digits:
                return int(max(1, round(_to_number(digits, multiplier))))
    return None


def parse_duration_minutes(text: str) -> float | None:
    text = text.lower()
    best: float | None = None
    for match in MINUTES_RE.finditer(text):
        value = float(match.group(1))
        unit = match.group(2)
        minutes = value
        if unit.startswith("hour"):
            minutes = value * 60
        elif unit.startswith("sec"):
            minutes = value / 60
        best = minutes if best is None else max(best, minutes)
    return round(best, 3) if best is not None else None


def _largest_size(text: str, target_unit: str) -> float | None:
    factors = {"kb": 1 / 1024, "mb": 1, "gb": 1024, "tb": 1024 * 1024, "pb": 1024 * 1024 * 1024}
    best: float | None = None
    for match in SIZE_RE.finditer(text):
        value = float(match.group(1).replace(",", "")) * factors[match.group(2)]
        best = value if best is None else max(best, value)
    if best is None:
        return None
    return round(best / factors[target_unit], 4)


def parse_dataset_gb(text: str) -> float | None:
    text = text.lower()
    matches = [m for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(gb|tb)\b", text)]
    if not matches:
        return None
    total = 0.0
    for match in matches:
        value = float(match.group(1).replace(",", ""))
        total += value * (1024 if match.group(2) == "tb" else 1)
    return total


def parse_upload_mb(text: str) -> float | None:
    text = text.lower()
    scoped = re.findall(r"(?:files?|uploads?|images?|photos?|videos?|attachments?)[^.]{0,40}?(\d[\d,]*(?:\.\d+)?)\s*(mb|kb|gb)", text)
    if not scoped:
        return None
    best = max(float(value) * {"kb": 1 / 1024, "mb": 1.0, "gb": 1024.0}[unit] for value, unit in scoped)
    return round(best, 3)


def parse_latency_ms(text: str) -> int | None:
    candidates: list[int] = []
    text = text.lower()
    for match in re.finditer(r"(?:under|within|less than|p95 of|p99 of|in about|target of)?\s*(\d[\d,]*)\s*(ms|milliseconds?)\b", text):
        candidates.append(int(match.group(1).replace(",", "")))
    for match in re.finditer(r"(?:under|within|less than|in about|responds? in)\s*(\d+(?:\.\d+)?)\s*seconds?\b", text):
        candidates.append(int(float(match.group(1)) * 1000))
    return min(candidates) if candidates else None


def parse_sla_percent(text: str) -> AvailabilityExpectation | None:
    values = [float(m.group(1)) for m in SLA_RE.finditer(text.lower())]
    if not values:
        return None
    top = max(values)
    if top >= 99.99:
        return AvailabilityExpectation.CRITICAL
    if top >= 99.9:
        return AvailabilityExpectation.HIGH
    if top >= 99.0:
        return AvailabilityExpectation.STANDARD
    return AvailabilityExpectation.BEST_EFFORT


PEAK_RATE_PER_MINUTE_RE = re.compile(
    r"(?:peak|sustain|handle|burst|serve|load)[^.:;\n]{0,40}?"
    r"(\d[\d,\. ]*?)\s*(?:requests?|reqs?|calls?|transactions?|hits?|users?|submissions?|sessions?)"
    r"\s*(?:per|/)\s*(?:minute|min|m)\b"
)
PEAK_RATE_PER_SECOND_RE = re.compile(
    r"(?:peak|sustain|handle|burst|serve|load)[^.:;\n]{0,40}?"
    r"(\d[\d,\. ]*?)\s*(?:requests?|reqs?|calls?|transactions?|hits?)\s*(?:per|/)\s*(?:second|sec|s)\b"
)
PEAK_RATE_TRAILING_RE = re.compile(
    r"(\d[\d,\. ]*?)\s*(?:requests?|reqs?|calls?|transactions?)\s*(?:per|/)\s*(?:minute|min)\b[^.:;\n]{0,20}?peak"
)


def parse_peak_rate(text: str) -> int | None:
    """Read a stated peak request rate out of prose.

    People write "peak is 80 requests/minute" far more often than they fill in a
    form field, and a stated peak is worth much more than a rate derived from a
    monthly average — so it has to win when both exist.
    """
    lowered = text.lower()
    for pattern in (PEAK_RATE_PER_MINUTE_RE, PEAK_RATE_TRAILING_RE):
        match = pattern.search(lowered)
        if match:
            value = _to_number(match.group(1), "")
            if value and value >= 1:
                return int(value)
    match = PEAK_RATE_PER_SECOND_RE.search(lowered)
    if match:
        value = _to_number(match.group(1), "")
        if value and value >= 1:
            return int(round(value * 60))
    return None


def parse_requests(text: str) -> int | None:
    text = text.lower()
    match = REQUESTS_PER_DAY_RE.search(text)
    if match:
        return int(_to_number(match.group(1), match.group(2))) * ACTIVE_DAYS_PER_MONTH
    match = REQUESTS_PER_MONTH_RE.search(text)
    if match:
        return int(_to_number(match.group(1), match.group(2)))
    per_day = re.search(r"(\d[\d,]*)\s*(requests?|calls?|page ?views?)\s*a day", text)
    if per_day:
        return int(float(per_day.group(1).replace(",", ""))) * ACTIVE_DAYS_PER_MONTH
    return None


@dataclass
class ExtractionOutcome:
    signal_updates: dict[str, object] = field(default_factory=dict)
    hits: list[RuleHit] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)

    def set(self, rule_id: str, name: str, value: object, evidence: str, signals: RequirementSignals) -> None:
        if not signals.is_established(name):
            self.signal_updates[name] = value
            self.matched_rules.append(rule_id)
            self.hits.append(RuleHit(rule_id, name, evidence))


def evaluate_text(text: str, signals: RequirementSignals) -> ExtractionOutcome:
    """Apply every lexical rule to the description and any extra technical notes."""
    outcome = ExtractionOutcome()
    lowered = text.lower()

    users = parse_user_count(lowered)
    if users:
        outcome.set("number.users", "expected_users", users, f"stated user count parsed as {users:,}", signals)

    requests = parse_requests(lowered)
    if requests:
        outcome.set("number.requests", "monthly_requests", requests, f"stated request volume parsed as {requests:,}/month", signals)

    peak_rate = parse_peak_rate(lowered)
    if peak_rate:
        outcome.set(
            "number.peak_rate",
            "peak_requests_per_minute",
            peak_rate,
            f"stated peak request rate parsed as {peak_rate:,} requests/minute",
            signals,
        )

    minutes = parse_duration_minutes(lowered)
    if minutes is not None:
        outcome.set("number.duration", "longest_operation_minutes", minutes,
                    f"longest stated operation parsed as {minutes:g} min", signals)

    dataset_gb = parse_dataset_gb(lowered)
    if dataset_gb:
        outcome.set("number.dataset", "dataset_size_gb", dataset_gb, f"stated data volume {dataset_gb:,.0f} GB", signals)

    upload_mb = parse_upload_mb(lowered)
    if upload_mb:
        outcome.set("number.upload", "upload_size_mb", upload_mb, f"stated upload size {upload_mb:g} MB", signals)

    latency = parse_latency_ms(lowered)
    if latency:
        outcome.set("number.latency", "latency_budget_ms", latency, f"stated latency target {latency} ms", signals)
        if latency <= 150:
            outcome.set("number.latency_sensitive", "cold_start_sensitive", True,
                        f"a {latency} ms budget is sensitive to cold starts", signals)

    for rule in TRAFFIC_RULES:
        if rule.pattern.search(lowered):
            outcome.set(rule.rule_id, rule.field, rule.value, rule.evidence, signals)

    for rule in BOOL_RULES:
        if rule.value is None:
            if rule.pattern.search(lowered) and not signals.is_established(rule.field):
                outcome.matched_rules.append(rule.rule_id)
                outcome.hits.append(RuleHit(rule.rule_id, rule.field, rule.evidence))
            continue
        if rule.pattern.search(lowered):
            outcome.set(rule.rule_id, rule.field, rule.value, rule.evidence, signals)

    sla = parse_sla_percent(lowered)
    if sla is not None:
        outcome.set("number.sla", "availability_hint", sla.value, f"stated availability target {sla.value}", signals)

    compliance = COMPLIANCE_RE.search(lowered)
    if compliance:
        outcome.set("compliance.regime", "compliance_regime", compliance.group(1).upper(),
                    f"compliance regime named in the description: {compliance.group(1).upper()}", signals)

    integrations = sorted({m.group(1) for m in INTEGRATION_RE.finditer(lowered)})
    if integrations:
        outcome.set("integrations.third_party", "third_party_integrations", integrations,
                    "third-party services named: " + ", ".join(integrations), signals)
        outcome.set("integrations.external_api", "external_api_dependencies", integrations,
                    "external API dependency assumed for each integration", signals)

    return outcome


def detect_application_type(text: str) -> ApplicationType | None:
    lowered = text.lower()
    for pattern, app_type in TYPE_RULES:
        if pattern.search(lowered):
            return app_type
    return None


def detect_traffic_pattern(text: str) -> TrafficPattern | None:
    lowered = text.lower()
    for rule in TRAFFIC_RULES:
        if rule.pattern.search(lowered):
            return rule.value  # type: ignore[return-value]
    return None


def detect_availability(text: str) -> AvailabilityExpectation | None:
    lowered = text.lower()
    sla = parse_sla_percent(lowered)
    if sla is not None:
        return sla
    for pattern, expectation in AVAILABILITY_RULES:
        if pattern.search(lowered):
            return expectation
    return None


def detect_budget(text: str) -> BudgetPreference | None:
    lowered = text.lower()
    for pattern, preference in BUDGET_RULES:
        if pattern.search(lowered):
            return preference
    return None


def detect_storage_kinds(text: str) -> list[DataStorageKind]:
    lowered = text.lower()
    found: list[DataStorageKind] = []
    for pattern, kind in STORAGE_KIND_RULES:
        if pattern.search(lowered) and kind not in found:
            found.append(kind)
    return found
