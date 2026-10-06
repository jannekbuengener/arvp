# ARVP Canonical Contract v2

**Version**: `arvp.canonical.v2`  
**Status**: Frozen for implementation  
**Supersedes**: v0.1 (internal, never publicly released)

---

## Overview

This document specifies the canonical JSON serialization and SHA-256 fingerprinting contract for ARVP (Automated Reproducible Validation Primitives). The contract defines:

1. **Portable value types** accepted for canonicalization
2. **Serialization rules** for each type
3. **Fingerprint computation** with domain separation
4. **Validation rules** for fingerprint strings

The contract is designed for **deterministic, cross-platform identity** of evidence artifacts, dataset content, run provenance, and evaluation results.

---

## Portable Value Model

### Accepted Types

| Python Type | Canonical JSON Form | Notes |
|-------------|---------------------|-------|
| `None` | `null` | Preserved in mappings (not removed) |
| `bool` | `true` / `false` | Distinct from `int` in JSON |
| `int` | number | Arbitrary precision; exact type `int` only |
| `float` (finite) | number | Shortest round-trip via `json.dumps`; `-0.0` → `0.0` |
| `Decimal` (finite) | `$arvp` extension object | Value identity; `as_tuple()` only |
| `str` | string | UTF-8; no Unicode normalization; surrogates rejected |
| `list` | array | Order preserved; exact type `list` only |
| `tuple` | array | **Same as list** — portable sequence; exact type `tuple` only |
| `dict` (str keys only) | object | Keys sorted; exact type `dict` only |

### Rejected Types (Fail-Closed)

- `bytes`, `bytearray`
- `set`, `frozenset`
- `Enum`, `IntEnum`
- `pathlib.Path`
- `dataclass`, `NamedTuple`
- `dict`, `list`, `tuple` subclasses
- Arbitrary `Mapping`/`Sequence` subclasses
- Arbitrary objects
- Non-string mapping keys
- Non-finite `float`/`Decimal` (`NaN`, `±Inf`)
- Strings containing surrogate codepoints (U+D800–U+DFFF)
- Mapping keys equal to `"$arvp"` (reserved namespace)

---

## Type-Specific Rules

### Float

- **Finite only** — `NaN`, `+Inf`, `-Inf` → `CanonicalizationError`
- **No pre-rounding** — raw IEEE-754 binary64 value
- **Signed zero collapse** — `-0.0` → `0.0` before serialization
- **Serialization**: `json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True)`
- **Cross-platform claim**: Stable on Python 3.11–3.14, Ubuntu + Windows (Golden Vectors freeze this)
- **No cross-language guarantee** — documented as Python-portable only

### Decimal

- **Finite only** — `NaN`, `±Inf` → `CanonicalizationError`
- **Algorithm**: Uses `Decimal.as_tuple()` exclusively — no `normalize()`, no context operations
- **Value identity**: Numerically equal Decimals produce identical canonical forms
  - `Decimal("1")` ≡ `Decimal("1.0")` ≡ `Decimal("1.00")` ≡ `Decimal("1E+0")`
  - `Decimal("0.10")` ≡ `Decimal("0.100")`
  - `Decimal("0")` ≡ `Decimal("-0")`
- **Internal representation** (`$arvp` extension):
  ```json
  {
    "$arvp": {
      "coefficient": "<signed-digit-string>",
      "exponent": <int>,
      "type": "decimal"
    }
  }
  ```
- **Coefficient contract**:
  - `"0"` for zero (never `"-0"`)
  - Positive: regex `[1-9][0-9]*` (no leading zeros)
  - Negative: regex `-[1-9][0-9]*` (no leading zeros after minus)
  - Derived from `as_tuple()` digits with trailing zeros removed, exponent adjusted

**Examples**:
| Input | Coefficient | Exponent |
|-------|-------------|----------|
| `Decimal("1")` | `"1"` | `0` |
| `Decimal("1.00")` | `"1"` | `0` |
| `Decimal("0.10")` | `"1"` | `-1` |
| `Decimal("-123.4500")` | `"-12345"` | `-2` |
| `Decimal("1E+100")` | `"1"` | `100` |

**Critical**: The `$arvp` extension is an **internal output** of the canonicalizer. It does not pass through user-input validation. User input containing `"$arvp"` as a mapping key is rejected before any recursive descent.

### Null Preservation

- Explicit `None` values in mappings are preserved as `null` in JSON
- `{"x": None}` → `{"x": null}` (NOT removed)
- `{}` and `{"x": null}` have different canonical bytes and fingerprints

### Sequences

- **`list`** → JSON array `[...]`
- **`tuple`** → JSON array `[...]` (identical to list)
- **Order** fully preserved
- **No type tag** — portable value semantics, not Python object identity

### Mappings

- **Keys MUST be `str`** — fail-closed otherwise (recursive)
- **`null` values preserved** — `{"x": None}` → `{"x": null}`
- **Keys sorted lexicographically** (via `json.dumps(sort_keys=True)`)
- **Reserved key** `"$arvp"` rejected at all nesting levels
- **Surrogate codepoints** in keys rejected

### Unicode

- **Encoding**: UTF-8 (JSON mandate)
- **`ensure_ascii=False`** — raw codepoints preserved
- **Normalization**: **NONE** — `"é"` (U+00E9, NFC) ≠ `"e\u0301"` (U+0065 U+0301, NFD)
- **Surrogate rejection**: Strings containing U+D800–U+DFFF → `CanonicalizationError`
- **Control characters**: Standard JSON escaping via `json.dumps`
- **Non-BMP valid scalars** (emoji, etc.): Preserved as-is

---

## Cycle Detection

- **Per-call** `active_ids: set[int]` — container `id()` tracked on recursive entry, removed in `finally`
- **Cycle** (e.g., `x = []; x.append(x)`) → `CanonicalizationError`
- **Shared acyclic references** allowed:
  ```python
  shared = {"x": 1}
  [shared, shared]  # OK — same object, not cyclic
  ```

---

## Domain Separation

### Constants

```python
CANONICAL_CONTRACT_VERSION = "arvp.canonical.v2"
# Domain separator derived internally:
# FINGERPRINT_DOMAIN_SEPARATOR = CANONICAL_CONTRACT_VERSION.encode("ascii") + b"\x00"
```

### Fingerprint Computation

```python
def canonical_hash(value: Any) -> str:
    canonical_bytes = canonical_json_dumps(value).encode("utf-8")
    domain_sep = CANONICAL_CONTRACT_VERSION.encode("ascii") + b"\x00"
    return hashlib.sha256(domain_sep + canonical_bytes).hexdigest()
```

### Claim

- Contract version alters hash preimage deterministically
- v2/v3 are domain-separated
- Practical uniqueness relies on SHA-256 collision resistance
- **No "never collide" guarantee**

---

## Public API

```python
# From arvp.canonical (re-exported from arvp)
CANONICAL_CONTRACT_VERSION: str = "arvp.canonical.v2"


def canonical_json_dumps(value: Any) -> str: ...
def canonical_hash(value: Any) -> str: ...
def validate_fingerprint(value: object, field: str = "fingerprint") -> str: ...


class CanonicalizationError(ValueError): ...


class FingerprintFormatError(ValueError): ...
```

**NOT exported**: `canonicalize()` (internal implementation detail)

---

## Fingerprint Validator

### `validate_fingerprint(value, field="fingerprint") -> str`

Accepts only:
- `str`
- Exactly 64 characters
- Lowercase hex (`0-9a-f`)
- No whitespace
- No prefix (`sha256:`, etc.)

Raises `FingerprintFormatError` (subclass of `ValueError`) on violation.

### Domain Error Boundaries

| Domain Module | Canonical Call | Domain Error |
|---------------|----------------|--------------|
| `datasets.py` | `canonical_hash(payload)` | `DatasetIdentityError` |
| `provenance.py` | `canonical_hash(...)`, `validate_fingerprint(...)` | `ProvenanceError` |
| `evaluation.py` | `validate_fingerprint(...)` | `EvaluationError` |
| `scenarios.py` | `canonical_hash(...)`, `canonical_json_dumps(...)` | `ScenarioError` |

---

## Golden Vectors

### Fixture Location

`tests/fixtures/canonical_v2_golden.json` — 49 vectors (31 positive, 18 negative)

### Oracle (Non-Circular)

1. Contract frozen in this document
2. `expected_json` manually authored from contract
3. `expected_fingerprint` computed independently via stdlib-only script:
   ```python
   hashlib.sha256(b"arvp.canonical.v2\x00" + expected_json.encode("utf-8")).hexdigest()
   ```
4. No imports from `arvp.canonical` in oracle script
5. No placeholder hashes in committed fixture

### Test Coverage

Positive cases: empty object, explicit null, bool, int, float (incl. signed zero), Decimal (value identity), list/tuple, nested mappings, order independence, Unicode NFC/NFD/emoji, shared acyclic reference.

Negative cases: non-finite float/Decimal, reserved `$arvp` key, non-string keys, `IntEnum`, `dict`/`list` subclasses, `set`, surrogates (string/key), cycles, missing/extra fields.

---

## Dataset Integration

### Core Principle

**Canonical intermediate data (`$arvp` extension) never leaves `canonical.py`.** Dataset layer stores original portable values; canonicalization happens at fingerprint time.

### Changes from v0.1

1. **Removed** `_normalize_content_value()` (Decimal→float conversion, `str(key)` coercion)
2. **`DatasetRequest.__post_init__`**: Validates keys (exact `str`, not `"$arvp"`), copies originals, validates canonicalizability via `canonical_json_dumps()`
3. **`identify_content()`**: Original values in payload; sort key uses `canonical_json_dumps(record[order_by])` + record hash tiebreaker
4. **Ordering semantics**: Canonical JSON total order (not numeric/lexical). Example: `1`, `2`, `10` sort as `1`, `10`, `2` (JSON string order)

---

## Cross-Platform Validation

### Platform Smoke (`tools/platform_smoke.py`)

- Loads golden fixture via `tools/canonical_v2_golden.py` (relative path)
- Verifies all 31 positive vectors: exact `expected_json` and `expected_fingerprint`
- Verifies all 18 negative vectors: expected `CanonicalizationError`
- Runs from checkout; `arvp` imported from installed wheel in package job
- No test-package runtime dependency; fixture not in wheel

### CI Matrix

- `unit / py3.11` through `py3.14`
- `lint`, `typecheck`, `package`
- `platform-smoke / ubuntu`, `platform-smoke / windows`

---

## Breaking Changes (v0.1 → v2)

| v0.1 Behavior | v2 Behavior | Migration |
|---------------|-------------|-----------|
| `float("nan")` → `null` hash | `CanonicalizationError` | Validate finiteness upstream |
| `{"x": None}` → `{}` hash | `{"x": null}` hash | Re-compute fingerprints |
| `Decimal("1.00")` → `"1"` hash | `$arvp` decimal extension hash | Re-compute all dataset/content fingerprints |
| `-0.0` → same as `0.0` | **Same** (collapsed) | No change needed |
| `[1,2]` ≡ `(1,2)` hash | **Same** (portable sequence) | No change needed |
| `len(fp)==64` validator | Strict lowercase hex | Update external validators |
| `IntEnum`/`dict` subclass accepted | Rejected | Use explicit portable values |

**Live Consumers**: None (no committed fingerprint fixtures, registry local-only).

---

## Implementation Files

| File | Role |
|------|------|
| `src/arvp/canonical.py` | Core implementation |
| `src/arvp/datasets.py` | Dataset request/content identity (uses canonical) |
| `src/arvp/provenance.py` | Run provenance/registry (uses canonical) |
| `src/arvp/evaluation.py` | Evaluation/gates (uses canonical) |
| `src/arvp/scenarios.py` | Scenario orchestration (uses canonical) |
| `src/arvp/__init__.py` | Public API exports |
| `tests/test_canonical.py` | Golden vector + contract tests |
| `tests/fixtures/canonical_v2_golden.json` | Frozen golden vectors |
| `tools/canonical_v2_golden.py` | Fixture loader + reconstruction |
| `tools/platform_smoke.py` | Cross-platform golden verification |
| `docs/canonical-contract-v2.md` | This document |

---

## Validation Commands

```powershell
# Full local validation
python -m pytest tests/
python -m ruff check .
python -m ruff format --check .
python -m mypy src/arvp
python -m build && python -m twine check dist/*
python tools/platform_smoke.py
```

---

## Appendix: Identity Matrix (Explicit)

| A | B | Same Fingerprint? |
|---|---|-------------------|
| `1` (int) | `1.0` (float) | **NO** |
| `1` (int) | `Decimal("1")` | **NO** |
| `1.0` (float) | `Decimal("1")` | **NO** |
| `"1"` (str) | `Decimal("1")` | **NO** |
| `True` | `1` | **NO** |
| `False` | `0` | **NO** |
| `0.0` | `-0.0` | **YES** |
| `Decimal("0")` | `Decimal("-0")` | **YES** |
| `Decimal("1")` | `Decimal("1.00")` | **YES** |
| `Decimal("0.10")` | `Decimal("0.100")` | **YES** |
| `[1, 2]` | `(1, 2)` | **YES** |
| `{"x": None}` | `{}` | **NO** |

---

*End of Contract Specification*