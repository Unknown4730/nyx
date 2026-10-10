"""AI provider abstraction: every failure mode degrades, nothing crashes or fabricates.

No test here performs a network call: the transport is a stub.  These tests
cover the eight required fallback cases (invalid JSON, malformed schema,
provider error, timeout, rate limit, empty response, unexpected keys, no key).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import AiConfig
from app.schemas.ai import AiExtractionProposal
from app.schemas.analysis import AnalysisOptions, AnalysisRequest
from app.schemas.common import AiAttemptStatus, AvailabilityExpectation, EngineMode
from app.schemas.requirements import ApplicationRequirements
from app.services.ai_provider import (
    SYSTEM_PROMPT,
    CompletionOutcome,
    NullProvider,
    OpenAICompatibleProvider,
    build_provider,
    build_user_prompt,
    engine_mode_for,
    parse_model_json,
)
from app.services.pipeline import AnalysisPipeline
from app.services.requirement_extractor import RequirementExtractionService
from app.services.templates import requirements_for


class StubTransport:
    """Programmatic stand-in for an OpenAI-compatible endpoint."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post_json(self, url, headers, payload, timeout):  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        status, body = response
        return status, body, json.dumps(body)


def completion(content: str | None = None, *, body: dict | None = None) -> tuple[int, dict]:
    if body is not None:
        return 200, body
    return 200, {"choices": [{"message": {"role": "assistant", "content": content or "{}"}}]}


def config(**overrides) -> AiConfig:
    payload: dict[str, Any] = {
        "enabled": True,
        "base_url": "https://inference.invalid/v1",
        "api_key": "test-key-not-a-secret",
        "model": "stub-model",
        "timeout_s": 0.05,
        "max_retries": 1,
        "min_interval_ms": 0,
        "cache_ttl_s": 0,
    }
    payload.update(overrides)
    return AiConfig(**payload)


def provider(*responses: Any, **overrides: Any) -> tuple[OpenAICompatibleProvider, StubTransport]:
    transport = StubTransport(list(responses))
    return OpenAICompatibleProvider(config(**overrides), transport=transport), transport


# A signal the deterministic rules cannot see in any template text, so accepting it
# is observable in the engine mode rather than being a no-op.
GOOD = {"signals": {"backup_expectation_days": 30}, "assumptions": ["Backups were assumed daily."]}


# ------------------------------------------------------------------ configuration


def test_no_key_configured_means_the_null_provider_and_a_complete_analysis():
    stub = build_provider(AiConfig(enabled=False, base_url="", api_key=""))
    assert isinstance(stub, NullProvider) or stub.available() is False
    outcome = stub.complete_json(system="s", user="u")
    assert outcome.status == AiAttemptStatus.NOT_CONFIGURED
    assert outcome.proposal is None
    assert outcome.succeeded is False

    result = AnalysisPipeline(ai_provider=stub).run(
        AnalysisRequest(requirements=requirements_for("online-examination"), options=AnalysisOptions(use_ai=True))
    )
    assert result.engine_mode is EngineMode.DETERMINISTIC
    assert result.ai.status == AiAttemptStatus.NOT_CONFIGURED
    assert result.ai.note
    # The analysis itself is complete, not partial.
    assert result.suitability.score > 0
    assert result.cost.scenarios and result.migration.phases and result.security is not None


def test_enabled_flag_with_missing_base_url_is_treated_as_unconfigured():
    assert config(base_url="", api_key="x").configured is False
    assert config(base_url="https://x.invalid", api_key="").configured is False
    assert config().configured is True
    provider_object = build_provider(config(base_url="https://x.invalid", api_key=""))
    assert isinstance(provider_object, NullProvider)


def test_configuration_never_leaks_the_key_into_status_or_prompts():
    snapshot = config().public_status()
    assert snapshot["configured"] is True
    assert snapshot["api_key_set"] is True
    assert "test-key-not-a-secret" not in json.dumps(snapshot)
    active, transport = provider(completion(json.dumps(GOOD)))
    active.complete_json(system=SYSTEM_PROMPT, user="Describe: an app")
    sent = transport.calls[0]
    assert sent["headers"]["Authorization"] == "Bearer test-key-not-a-secret"
    # The key travels only as a header; it never enters the prompt or the payload.
    assert "test-key-not-a-secret" not in json.dumps(sent["payload"])


# ------------------------------------------------------------------- failure modes


def test_timeout_degrades_to_a_recorded_failure():
    active, _ = provider(TimeoutError("upstream did not answer in time"))
    outcome = active.complete_json(system="s", user="u")
    assert outcome.status == AiAttemptStatus.FAILED_TIMEOUT
    assert outcome.proposal is None
    assert "timed out" in outcome.note.lower()


def test_rate_limit_is_recorded_and_bounded():
    active, transport = provider((429, {"error": {"message": "slow down"}, "retry_after": 0}))
    outcome = active.complete_json(system="s", user="u")
    assert outcome.status == AiAttemptStatus.FAILED_RATE_LIMIT
    assert outcome.attempts <= 1 + config().max_retries + 1
    assert len(transport.calls) == outcome.attempts


def test_provider_error_is_not_raised():
    active, _ = provider((503, {"error": {"message": "engine overloaded"}}))
    outcome = active.complete_json(system="s", user="u")
    assert outcome.status == AiAttemptStatus.FAILED_PROVIDER
    assert "503" in outcome.note and "engine overloaded" in outcome.note
    assert outcome.proposal is None


def test_non_json_response_is_discarded():
    active, _ = provider(completion("Sure! An architecture would use Lambda and S3 and save 40%."))
    outcome = active.complete_json(system="s", user="u")
    assert outcome.status == AiAttemptStatus.FAILED_VALIDATION
    assert outcome.proposal is None
    assert "not valid JSON" in outcome.note or "not JSON" in outcome.note


def test_empty_response_is_recorded_as_empty():
    for body in ({"choices": [{"message": {"role": "assistant", "content": "   "}}]}, {"choices": []}):
        active, _ = provider(completion(None, body=body))
        outcome = active.complete_json(system="s", user="u")
        assert outcome.status == AiAttemptStatus.FAILED_EMPTY, body
        assert outcome.proposal is None


def test_fenced_json_is_still_parsed():
    active, _ = provider(completion("```json\n" + json.dumps(GOOD) + "\n```"))
    outcome = active.complete_json(system="s", user="u")
    assert outcome.status == AiAttemptStatus.SUCCESS
    assert outcome.proposal is not None
    assert outcome.proposal.signals["backup_expectation_days"] == 30


def test_unexpected_keys_are_ignored_and_wrong_types_are_rejected_locally():
    # The provider transport only checks the envelope; type-correctness is enforced
    # by the local merge, which must refuse the bad values and say so.
    active, _ = provider(
        completion(
            json.dumps(
                {
                    "signals": {"long_running_jobs": "yes", "gpu_required": 1},
                    "architecture": {"use": "lambda"},
                    "cost_saving_pct": 40,
                }
            )
        )
    )
    outcome = active.complete_json(system="s", user="u")
    assert outcome.status == AiAttemptStatus.SUCCESS
    assert outcome.proposal is not None
    assert not hasattr(outcome.proposal, "architecture")

    result = AnalysisPipeline(ai_provider=active).run(
        AnalysisRequest(requirements=requirements_for("file-processing-pipeline"), options=AnalysisOptions(use_ai=True))
    )
    assert result.engine_mode is EngineMode.DETERMINISTIC, "nothing was accepted, so the result stays rule-based"
    assert result.ai.status in {AiAttemptStatus.SUCCESS, AiAttemptStatus.FAILED_VALIDATION}
    assert result.ai.rejected_fields or not result.ai.accepted_fields
    # The deterministic value for this template already exists, so a bad AI value
    # must leave it untouched rather than replace it.
    assert result.signals.long_running_jobs is True


def test_malformed_schema_json_array_is_rejected():
    active, _ = provider(completion(json.dumps([1, 2, 3])))
    outcome = active.complete_json(system="s", user="u")
    assert outcome.status == AiAttemptStatus.FAILED_VALIDATION
    assert "not an object" in outcome.note


def test_a_bad_enum_value_is_rejected_and_unknown_keys_are_ignored():
    with pytest.raises(Exception):
        AiExtractionProposal.model_validate({"traffic_pattern": "usually_quiet"})
    proposal = AiExtractionProposal.model_validate(
        {"signals": {"long_running_jobs": True}, "expected_users": "lots", "services": ["s3"]}
    )
    assert proposal.signals == {"long_running_jobs": True}
    assert proposal.traffic_pattern is None
    assert not hasattr(proposal, "services")


# ------------------------------------------------------------------------- success


def test_valid_output_is_accepted_and_engine_mode_becomes_ai_assisted():
    active, transport = provider(completion(json.dumps(GOOD)))
    result = AnalysisPipeline(ai_provider=active).run(
        AnalysisRequest(requirements=requirements_for("file-processing-pipeline"), options=AnalysisOptions(use_ai=True))
    )
    assert result.engine_mode is EngineMode.AI_ASSISTED
    assert result.ai.status == AiAttemptStatus.SUCCESS
    assert "backup_expectation_days" in result.ai.accepted_fields
    assert result.ai.model == "stub-model"
    assert result.ai.provider == "openai-compatible"
    assert result.ai.attempts >= 1
    assert len(transport.calls) == 1
    sent_user_prompt = transport.calls[0]["payload"]["messages"][1]["content"]
    assert "Return the JSON object now" in sent_user_prompt
    assert '"backup_expectation_days"' not in sent_user_prompt  # the model is not fed the answer key
    assert "do not contradict" in sent_user_prompt.lower()
    assert '"signals"' in SYSTEM_PROMPT


def test_valid_but_non_decisive_output_stays_labelled_rule_based():
    active, _ = provider(completion(json.dumps({"assumptions": ["The client is a web app."]})))
    result = AnalysisPipeline(ai_provider=active).run(
        AnalysisRequest(requirements=requirements_for("college-attendance"), options=AnalysisOptions(use_ai=True))
    )
    assert result.ai.status == AiAttemptStatus.SUCCESS
    assert result.ai.accepted_fields == []
    assert result.engine_mode is EngineMode.DETERMINISTIC, "nothing changed the analysis, so it stays rule-based"


def test_ai_may_not_overwrite_what_the_user_stated():
    service = RequirementExtractionService()
    extraction = service.extract(
        ApplicationRequirements(name="Stated", description="An exam platform for 10000 students.", availability="high")
    )
    assert extraction.requirements.expected_users == 10000 or extraction.signals.expected_users == 10000
    proposal = AiExtractionProposal.model_validate(
        {"availability": "best_effort", "signals": {"expected_users": 5_000_000}}
    )
    merged, accepted, rejected = service.merge_ai_proposal(extraction, proposal)
    assert merged.requirements.availability is AvailabilityExpectation.HIGH, "a stated value is never overruled"
    assert "availability (user value kept)" in rejected
    assert "expected_users" not in accepted, "an already-established signal is left alone"
    assert merged.signals.expected_users == 10000


def test_ai_may_not_invent_services_or_architecture():
    assert "signals" in SYSTEM_PROMPT
    for forbidden in ("must not design an architecture", "must not invent facts"):
        assert forbidden in SYSTEM_PROMPT
    prompt = build_user_prompt(requirements_for("online-examination"), {"expected_users": 10000})
    assert "expected_users" in prompt
    assert "do not contradict" in prompt.lower()
    assert "Return one JSON object and nothing else" in SYSTEM_PROMPT


def test_identical_request_is_served_from_the_cache():
    active, transport = provider(completion(json.dumps(GOOD)), cache_ttl_s=60)
    first = active.complete_json(system="s", user="u")
    second = active.complete_json(system="s", user="u")
    assert first.status == AiAttemptStatus.SUCCESS
    assert second.status == AiAttemptStatus.CACHED
    assert second.attempts == 0
    assert len(transport.calls) == 1
    assert second.proposal == first.proposal


def test_caching_can_be_disabled():
    active, transport = provider(completion(json.dumps(GOOD)), cache_ttl_s=0)
    active.complete_json(system="s", user="u")
    active.complete_json(system="s", user="u")
    assert len(transport.calls) == 2


def test_parse_model_json_is_tolerant_but_never_silent():
    assert parse_model_json("") == (None, "The provider returned an empty message body.")
    assert parse_model_json("no json here") == (None, "The provider response was not JSON, so it was discarded.")
    parsed, note = parse_model_json('prefix {"a": 1} suffix')
    assert parsed == {"a": 1} and note == ""
    assert parse_model_json("[1,2]")[0] is None


def test_engine_mode_helper_maps_only_on_a_validated_proposal():
    accepted = CompletionOutcome(status=AiAttemptStatus.SUCCESS, proposal=AiExtractionProposal.model_validate({}))
    assert engine_mode_for(accepted) is EngineMode.AI_ASSISTED
    # A transport success with nothing usable is still a rule-based analysis.
    assert engine_mode_for(CompletionOutcome(status=AiAttemptStatus.SUCCESS)) is EngineMode.DETERMINISTIC
    for status in (
        AiAttemptStatus.FAILED_TIMEOUT,
        AiAttemptStatus.FAILED_RATE_LIMIT,
        AiAttemptStatus.FAILED_VALIDATION,
        AiAttemptStatus.FAILED_EMPTY,
        AiAttemptStatus.FAILED_PROVIDER,
        AiAttemptStatus.NOT_CONFIGURED,
        AiAttemptStatus.DISABLED_BY_REQUEST,
    ):
        assert engine_mode_for(CompletionOutcome(status=status)) is EngineMode.DETERMINISTIC


def test_use_ai_false_never_touches_the_transport():
    active, transport = provider(completion(json.dumps(GOOD)))
    result = AnalysisPipeline(ai_provider=active).run(
        AnalysisRequest(requirements=requirements_for("college-attendance"), options=AnalysisOptions(use_ai=False))
    )
    assert transport.calls == []
    assert result.engine_mode is EngineMode.DETERMINISTIC
    assert result.ai.status == AiAttemptStatus.DISABLED_BY_REQUEST
    assert result.ai.attempts == 0


def test_retries_are_bounded_by_configuration():
    active, transport = provider((500, {"error": {"message": "boom"}}), max_retries=2)
    outcome = active.complete_json(system="s", user="u")
    assert len(transport.calls) <= 3
    assert outcome.attempts <= 3
    assert outcome.status == AiAttemptStatus.FAILED_PROVIDER
