from __future__ import annotations

from pathlib import Path

import pytest

from arvp.evidence import (
    FAILURE_EVIDENCE_VERSION,
    FailureCode,
    FailureEvidence,
    PortableEvidenceError,
    validate_portable_metadata,
)


def test_failure_evidence_version_constant() -> None:
    assert FAILURE_EVIDENCE_VERSION == "arvp.failure-evidence.v1"


def test_failure_codes_literal() -> None:
    # All valid failure codes should be accepted
    codes: list[FailureCode] = [
        "expected_domain_failure",
        "input_unavailable",
        "invalid_input",
        "unexpected_exception",
        "insufficient_evidence",
    ]
    for code in codes:
        evidence = FailureEvidence(code=code)
        assert evidence.code == code


def test_failure_evidence_from_unexpected_exception() -> None:
    exc = FileNotFoundError("C:\\Users\\secret\\data.txt")
    evidence = FailureEvidence.from_unexpected_exception(exc, stage="runner")

    assert evidence.code == "unexpected_exception"
    assert evidence.exception_type == "FileNotFoundError"
    assert evidence.stage == "runner"
    assert evidence.metadata is None


def test_failure_evidence_expected_domain_failure() -> None:
    evidence = FailureEvidence.expected_domain_failure(
        stage="runner", metadata={"reason": "timeout"}
    )
    assert evidence.code == "expected_domain_failure"
    assert evidence.exception_type is None
    assert evidence.stage == "runner"
    assert evidence.metadata == {"reason": "timeout"}


def test_failure_evidence_input_unavailable() -> None:
    evidence = FailureEvidence.input_unavailable(stage="loader")
    assert evidence.code == "input_unavailable"
    assert evidence.exception_type is None
    assert evidence.stage == "loader"


def test_failure_evidence_invalid_input() -> None:
    evidence = FailureEvidence.invalid_input(metadata={"field": "score"})
    assert evidence.code == "invalid_input"
    assert evidence.metadata == {"field": "score"}


def test_failure_evidence_insufficient_evidence() -> None:
    evidence = FailureEvidence.insufficient_evidence()
    assert evidence.code == "insufficient_evidence"


def test_failure_evidence_to_dict() -> None:
    evidence = FailureEvidence(
        code="expected_domain_failure",
        exception_type=None,
        stage="runner",
        metadata={"reason": "timeout", "count": 3},
    )
    d = evidence.to_dict()
    assert d == {
        "code": "expected_domain_failure",
        "stage": "runner",
        "metadata": {"reason": "timeout", "count": 3},
    }
    # exception_type should not be in dict when None
    assert "exception_type" not in d


def test_failure_evidence_to_dict_with_exception_type() -> None:
    evidence = FailureEvidence(
        code="unexpected_exception",
        exception_type="ValueError",
        stage="runner",
        metadata=None,
    )
    d = evidence.to_dict()
    assert d == {
        "code": "unexpected_exception",
        "exception_type": "ValueError",
        "stage": "runner",
    }
    assert "metadata" not in d


def test_failure_evidence_rejects_invalid_code() -> None:
    with pytest.raises(PortableEvidenceError, match="invalid failure code"):
        FailureEvidence(code="not_a_valid_code")


def test_failure_evidence_rejects_qualified_exception_type() -> None:
    with pytest.raises(PortableEvidenceError, match="simple class name"):
        FailureEvidence(
            code="unexpected_exception",
            exception_type="builtins.ValueError",
        )


def test_failure_evidence_rejects_empty_stage() -> None:
    with pytest.raises(PortableEvidenceError, match="non-empty string"):
        FailureEvidence(code="invalid_input", stage="")


def test_failure_evidence_rejects_non_mapping_metadata() -> None:
    with pytest.raises(PortableEvidenceError, match="must be a mapping"):
        FailureEvidence(code="invalid_input", metadata=["not", "a", "mapping"])


def test_validate_portable_metadata_valid() -> None:
    # Simple valid metadata
    validated = validate_portable_metadata({"key": "value", "count": 42})
    assert validated == {"key": "value", "count": 42}

    # Nested valid metadata
    validated = validate_portable_metadata({"nested": {"key": "value"}})
    assert validated == {"nested": {"key": "value"}}


def test_validate_portable_metadata_rejects_non_mapping() -> None:
    with pytest.raises(PortableEvidenceError, match="must be a mapping"):
        validate_portable_metadata("not a mapping")


def test_validate_portable_metadata_rejects_non_canonicalizable() -> None:
    # Non-portable types should be rejected
    with pytest.raises(PortableEvidenceError, match="not canonicalizable"):
        validate_portable_metadata({"bad": {1, 2}})

    with pytest.raises(PortableEvidenceError, match="not canonicalizable"):
        validate_portable_metadata({"bad": float("nan")})

    with pytest.raises(PortableEvidenceError, match="not canonicalizable"):
        validate_portable_metadata({"bad": float("inf")})


def test_validate_portable_metadata_rejects_danger_keys() -> None:
    for danger_key in [
        "api_key",
        "API_KEY",
        "api_secret",
        "authorization",
        "connection_string",
        "database_url",
        "dsn",
        "file_path",
        "password",
        "path",
        "secret",
        "token",
    ]:
        with pytest.raises(PortableEvidenceError, match="forbidden key"):
            validate_portable_metadata({danger_key: "value"})

    # Nested danger key
    with pytest.raises(PortableEvidenceError, match="forbidden key"):
        validate_portable_metadata({"nested": {"api_key": "value"}})

    # Danger key in list
    with pytest.raises(PortableEvidenceError, match="forbidden key"):
        validate_portable_metadata({"items": [{"token": "value"}]})


def test_validate_portable_metadata_rejects_surrogates() -> None:
    with pytest.raises(PortableEvidenceError, match="surrogate codepoints"):
        validate_portable_metadata({"\ud800": "value"})


def test_validate_portable_metadata_rejects_reserved_arvp() -> None:
    with pytest.raises(PortableEvidenceError, match="reserved key"):
        validate_portable_metadata({"$arvp": "value"})


def test_validate_portable_metadata_returns_copy() -> None:
    original = {"key": "value"}
    validated = validate_portable_metadata(original)
    assert validated is not original
    assert validated == original


def test_validate_portable_metadata_nested_validation() -> None:
    # Valid nested structure
    validated = validate_portable_metadata({"a": {"b": [1, 2, 3]}})
    assert validated == {"a": {"b": [1, 2, 3]}}

    # Invalid nested (danger key in nested dict)
    with pytest.raises(PortableEvidenceError, match="forbidden key"):
        validate_portable_metadata({"a": {"b": {"password": "secret"}}})


def test_failure_evidence_serialization_roundtrip() -> None:
    original = FailureEvidence(
        code="expected_domain_failure",
        stage="runner",
        metadata={"reason": "timeout", "retry_count": 3},
    )
    d = original.to_dict()
    # Reconstruct from dict
    reconstructed = FailureEvidence(**d)
    assert reconstructed.code == original.code
    assert reconstructed.stage == original.stage
    assert reconstructed.metadata == original.metadata
    assert reconstructed.exception_type == original.exception_type


def test_failure_evidence_codes_completeness() -> None:
    # Ensure all FailureCode values have corresponding classmethods
    codes = FailureCode.__args__
    assert "expected_domain_failure" in codes
    assert "input_unavailable" in codes
    assert "invalid_input" in codes
    assert "unexpected_exception" in codes
    assert "insufficient_evidence" in codes


def test_validate_portable_metadata_rejects_surrogate_in_value() -> None:
    with pytest.raises(PortableEvidenceError, match="not canonicalizable"):
        validate_portable_metadata({"key": "\ud800"})


def test_validate_portable_metadata_path_object_rejected() -> None:
    with pytest.raises(PortableEvidenceError, match="not canonicalizable"):
        validate_portable_metadata({"path": Path("some/path")})


def test_failure_evidence_validates_metadata_at_construction() -> None:
    with pytest.raises(PortableEvidenceError, match="forbidden key"):
        FailureEvidence.invalid_input(metadata={"token": "secret"})

    with pytest.raises(PortableEvidenceError, match="not canonicalizable"):
        FailureEvidence.invalid_input(metadata={"value": Path("local/file")})


def test_failure_evidence_defensively_copies_nested_metadata() -> None:
    original = {"nested": {"reason": "stable"}}
    evidence = FailureEvidence.invalid_input(metadata=original)

    original["nested"]["reason"] = "mutated"
    assert evidence.metadata == {"nested": {"reason": "stable"}}

    projected = evidence.to_dict()
    projected["metadata"]["nested"]["reason"] = "changed"  # type: ignore[index]
    assert evidence.metadata == {"nested": {"reason": "stable"}}


def test_failure_evidence_rejects_non_token_stage_and_exception_type() -> None:
    with pytest.raises(PortableEvidenceError, match="stage"):
        FailureEvidence(code="invalid_input", stage=r"C:\Users\alice")

    with pytest.raises(PortableEvidenceError, match="exception_type"):
        FailureEvidence(
            code="unexpected_exception",
            exception_type="File/NotFoundError",
        )
