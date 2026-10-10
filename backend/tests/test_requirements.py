"""Requirement extraction and validation — the anti-hallucination boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.common import AvailabilityExpectation, CloudProvider, FieldBasis, TrafficPattern
from app.schemas.requirements import ApplicationRequirements, RequirementSignals
from app.services.requirement_extractor import extract_requirements as extract

SHORT = "An internal tool for 40 staff with an API and a database."

# --------------------------------------------------------------------------- schema


def test_name_and_description_are_required_and_bounded():
    with pytest.raises(ValidationError):
        ApplicationRequirements()
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="a", description="some description that is long enough")
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="a" * 200, description="some description")
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="Fine", description="x" * 5000)
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="Fine", description=SHORT, expected_users=0)
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="Fine", description=SHORT, expected_users=600_000_000)


def test_enum_fields_reject_invented_values():
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="ok", description=SHORT, traffic_pattern="sometimes")
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="ok", description=SHORT, data_storage=["postgres"])
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="ok", description=SHORT, preferred_provider="oracle")


def test_strict_models_refuse_unknown_fields():
    with pytest.raises(ValidationError):
        ApplicationRequirements(name="ok", description=SHORT, invented_field=True)
    with pytest.raises(ValidationError):
        RequirementSignals.model_validate({"nonexistent": 1})


def test_unknown_enum_sentinels_are_normalised_to_missing():
    for value in ("unknown", "unspecified", "none"):
        requirements = ApplicationRequirements(name="ok", description=SHORT, traffic_pattern=value)
        assert requirements.traffic_pattern in (None, TrafficPattern.UNKNOWN)
    requirements = ApplicationRequirements(name="ok", description=SHORT, data_storage=["relational"])
    assert requirements.data_storage == ["relational"]


def test_storage_kinds_are_deduplicated_and_sorted():
    requirements = ApplicationRequirements(
        name="ok", description=SHORT, data_storage=["relational", "object_storage", "relational", "cache_session"]
    )
    values = [str(kind.value) for kind in requirements.data_storage]
    # Deduplicated, and in the canonical vocabulary order so that two equivalent
    # inputs always produce one identical document.
    assert values == ["relational", "object_storage", "cache_session"]


def test_empty_optional_strings_become_none():
    requirements = ApplicationRequirements(name="ok", description=SHORT, additional_requirements="   ")
    assert requirements.additional_requirements is None


def test_provenance_records_where_each_value_came_from():
    requirements = ApplicationRequirements(
        name="ok",
        description="A booking system with 500 users and spiky traffic.",
        availability="high",
    )
    provenance = requirements.provenance
    assert set(provenance) <= set(type(requirements).model_fields)
    assert provenance["availability"].basis is FieldBasis.USER
    assert requirements.basis_for("availability") is FieldBasis.USER
    assert requirements.is_asserted("availability") is True
    extraction_view = extract(requirements)
    # The derived figure is written back into the requirement the report reads,
    # but always tagged as inferred so it can never masquerade as user input.
    assert extraction_view.requirements.expected_users == 500
    assert extraction_view.requirements.basis_for("expected_users") is FieldBasis.INFERRED
    assert requirements.basis_for("expected_users") is FieldBasis.UNSPECIFIED, "the caller's object is never mutated"
    assert requirements.basis_for("preferred_provider") is FieldBasis.UNSPECIFIED
    assert requirements.is_asserted("preferred_provider") is False


def test_defaults_are_labelled_as_defaults_not_as_user_input():
    requirements = ApplicationRequirements(name="ok", description="A booking system with 500 users.")
    assert requirements.preferred_provider in (None, CloudProvider.UNDECIDED)
    assert requirements.application_type.value == "unknown" or requirements.basis_for("application_type") in {
        FieldBasis.INFERRED,
        FieldBasis.DEFAULT,
    }
    assert requirements.basis_for("budget") is not FieldBasis.USER


def test_expected_users_does_not_swallow_year_numbers():
    requirements = ApplicationRequirements(
        name="ok", description="Attendance portal for the 2024/25 academic year serving 1200 students."
    )
    assert extract(requirements).requirements.expected_users == 1200  # the year is not a headcount


def test_stated_peak_rate_is_preferred_over_derivation():
    requirements = ApplicationRequirements(
        name="ok", description="Attendance portal with 2500 students; peak is 80 requests/minute."
    )
    extraction = extract(requirements)
    assert extraction.signals.expected_users == 2500
    signals = extraction.signals
    assert signals.peak_requests_per_minute == 80
    assert signals.monthly_requests and signals.monthly_requests > 0


def test_duration_and_availability_wording_is_captured():
    extraction = extract(
        ApplicationRequirements(
            name="ok",
            description=(
                "An internal admin tool used by 30 staff; it is only needed during business hours and a single "
                "video transcode can run for 45 minutes."
            ),
        )
    )
    assert extraction.signals.long_running_jobs is True
    assert extraction.signals.longest_operation_minutes == 45
    assert extraction.signals.business_hours_only in (True, None)


# -------------------------------------------------------------------------- signals


def test_signals_only_carry_evidence_and_never_a_recommendation():
    extraction = extract(
        ApplicationRequirements(
            name="ok",
            description="Video transcoding jobs of about 20 minutes for 5000 users; the API tier is stateless.",
        )
    )
    signals = extraction.signals
    assert signals.long_running_jobs is True
    assert signals.gpu_required in (False, None)
    assert isinstance(signals.notes, dict)
    for key, value in signals.notes.items():
        assert isinstance(key, str) and isinstance(value, str) and value
    assert not hasattr(signals, "recommendation")
    assert not hasattr(signals, "architecture")
    assert not hasattr(signals, "cost_ricu")


def test_unsupported_signals_stay_unestablished_rather_than_defaulting_to_no():
    signals = extract(ApplicationRequirements(name="ok", description="A simple internal notes app for 12 users.")).signals
    assert signals.is_established("multi_tenant") is False
    assert signals.is_established("persistent_connections") is False
    assert signals.multi_tenant is None
    assert signals.persistent_connections is None
    assert "multi_tenant" in signals.unknown_fields(list(RequirementSignals.model_fields))


def test_assumptions_carry_impact_and_questions_are_for_deciding_fields():
    extraction = extract(ApplicationRequirements(name="ok", description="An attendance portal with QR codes."))
    assert extraction.assumptions
    for assumption in extraction.assumptions:
        assert assumption.statement
        assert assumption.impact in {"low", "medium", "high"}
        assert assumption.basis in set(FieldBasis)
    assert extraction.open_questions
    for question in extraction.open_questions:
        assert question.field
        assert question.question.strip().endswith("?")
        assert question.why_it_matters
    assert {"expected_users", "availability"} & {question.field for question in extraction.open_questions}


def test_assumptions_and_questions_are_bounded():
    description = " ".join(
        [
            "The system has 5000 users and spiky traffic with 90 second uploads and 20 minute jobs.",
            *["GPU inference is required and the runtime is custom."] * 5,
            *["There is a websocket session per user that stays open for hours."] * 5,
            *["The data is financial and PCI scoped with audit logging."] * 5,
        ]
    )
    extraction = extract(ApplicationRequirements(name="ok", description=description))
    assert len(extraction.assumptions) <= 40
    assert len(extraction.open_questions) <= 12


@pytest.mark.parametrize(
    "identifier",
    [
        "college-attendance",
        "online-examination",
        "ecommerce-application",
        "food-delivery-platform",
        "file-processing-pipeline",
    ],
)
def test_every_template_extracts_something_real(identifier):
    from app.services.templates import requirements_for

    requirements = requirements_for(identifier)
    assert requirements is not None
    extraction = extract(requirements)
    established = [name for name in RequirementSignals.model_fields if extraction.signals.is_established(name)]
    assert len(established) >= 3, f"{identifier} extracted too little: {established}"
    assert extraction.requirements.expected_users or extraction.assumptions, "silence must be recorded as an assumption"


def test_normalisation_survives_newlines_quotes_and_tabs():
    requirements = ApplicationRequirements(
        name="  Weird \n name ", description="Line one.\n\nLine\ttwo.", additional_requirements="  "
    )
    assert requirements.name == "Weird name"
    assert "Line one." in requirements.description
    assert "\n" not in requirements.description and "\t" not in requirements.description
    assert requirements.additional_requirements is None


def test_ai_proposal_field_list_is_the_contract_with_the_prompt():
    from app.schemas.ai import ALLOWED_SIGNAL_KEYS, AiExtractionProposal, JSON_SCHEMA

    assert set(ALLOWED_SIGNAL_KEYS) <= set(RequirementSignals.model_fields)
    assert set(JSON_SCHEMA["properties"]) - {"signals"} <= set(AiExtractionProposal.model_fields)
    assert JSON_SCHEMA["additionalProperties"] is False, "the model may not add its own fields"
    assert JSON_SCHEMA["required"] == ["signals"]
    # Anything the model returns is read only through the documented keys.
    proposal = AiExtractionProposal.model_validate(
        {"_meta": {"anything": True}, "architecture": {"use": "lambda"}, "signals": {"long_running_jobs": True}}
    )
    assert not hasattr(proposal, "architecture")
    assert proposal.signals == {"long_running_jobs": True}
    assert not hasattr(proposal, "_meta")


def test_merge_only_fills_gaps_and_never_overrules_the_user():
    from app.services.requirement_extractor import RequirementExtractionService

    service = RequirementExtractionService()
    stated = ApplicationRequirements(
        name="Stated",
        description="An exam platform for 10000 students.",
        availability="high",
    )
    extraction = service.extract(stated)
    from app.schemas.ai import AiExtractionProposal

    proposal = AiExtractionProposal.model_validate({"availability": "best_effort", "budget": "minimize"})
    merged, accepted, rejected = service.merge_ai_proposal(extraction, proposal)
    assert merged.requirements.availability is AvailabilityExpectation.HIGH
    assert "availability (user value kept)" in rejected
    assert "budget" in accepted
    assert merged.requirements.basis_for("budget") is FieldBasis.AI


def test_out_of_range_and_wrongly_typed_ai_values_are_dropped_before_the_merge():
    from app.schemas.ai import AiExtractionProposal
    from app.services.requirement_extractor import RequirementExtractionService

    proposal = AiExtractionProposal.model_validate(
        {
            "signals": {
                "expected_users": -3,
                "long_running_jobs": "yes",
                "monthly_requests": "many",
                "invented_signal": True,
                "compliance_regime": "some free text about a regime",
            }
        }
    )
    # Only the free-text field survives; every typed field with a bad value is gone.
    assert set(proposal.signals) == {"compliance_regime"}

    extraction = RequirementExtractionService().extract(
        ApplicationRequirements(name="ok", description="A small internal tool for 20 users.")
    )
    before = extraction.signals.long_running_jobs
    merged, accepted, rejected = RequirementExtractionService().merge_ai_proposal(
        extraction, AiExtractionProposal.model_validate({"signals": {"long_running_jobs": "definitely"}})
    )
    assert merged.signals.long_running_jobs == before
    assert not accepted or set(accepted) <= set(RequirementSignals.model_fields)


def test_signals_reject_out_of_range_assignment_even_directly():
    signals = RequirementSignals()
    with pytest.raises(Exception):
        signals.set_field("expected_users", -1, FieldBasis.INFERRED, "must be rejected")
    with pytest.raises(Exception):
        signals.set_field("not_a_real_signal", True, FieldBasis.INFERRED, "unknown key")
    signals.set_field("expected_users", 500, FieldBasis.USER, "stated")
    assert signals.expected_users == 500
    assert signals.basis_for("expected_users") is FieldBasis.USER
