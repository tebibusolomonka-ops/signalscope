import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ACCEPTANCE_PROFILE_VERSION = 1

SECTION_FIELDS: dict[str, dict[str, type[bool] | type[int]]] = {
    "deployment": {
        "validation_passes": bool,
        "migration_current": bool,
        "production_configuration_valid": bool,
    },
    "security": {
        "auth_enabled": bool,
        "login_throttling_configured": bool,
        "session_expiry_configured": bool,
        "absolute_session_expiry_configured": bool,
        "idle_session_expiry_configured": bool,
        "security_headers_enabled": bool,
        "csp_enabled": bool,
        "support_bundle_redaction_succeeds": bool,
    },
    "backup": {
        "verified_backup_exists": bool,
        "max_age_hours": int,
    },
    "disaster_recovery": {
        "drill_exists": bool,
        "max_age_hours": int,
        "verification_drill_exists": bool,
        "verification_max_age_hours": int,
        "restore_test_required": bool,
        "restore_test_max_age_hours": int,
        "asset_verification_succeeded": bool,
    },
    "operations": {
        "startup_preflight_passes": bool,
        "support_bundle_works": bool,
    },
    "frontend": {
        "lint_passes": bool,
        "tests_pass": bool,
        "build_passes": bool,
    },
    "model_evaluation": {
        "quality_gate_evidence_exists": bool,
    },
}


class AcceptanceProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AcceptanceProfile:
    version: int
    sections: dict[str, dict[str, bool | int]]

    def section(self, name: str) -> dict[str, bool | int] | None:
        return self.sections.get(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            **{name: dict(values) for name, values in sorted(self.sections.items())},
        }


def load_acceptance_profile(path: Path) -> AcceptanceProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AcceptanceProfileError(f"Could not read acceptance profile: {error}") from error
    if not isinstance(raw, dict):
        raise AcceptanceProfileError("Acceptance profile must be a JSON object.")
    if raw.get("version") != ACCEPTANCE_PROFILE_VERSION:
        raise AcceptanceProfileError("Acceptance profile version must be 1.")
    unknown_sections = set(raw) - {"version", *SECTION_FIELDS}
    if unknown_sections:
        raise AcceptanceProfileError(f"Unknown acceptance section: {sorted(unknown_sections)[0]}.")
    sections: dict[str, dict[str, bool | int]] = {}
    for name, field_types in SECTION_FIELDS.items():
        value = raw.get(name)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise AcceptanceProfileError(f"Acceptance section {name} must be an object.")
        unknown_fields = set(value) - set(field_types)
        if unknown_fields:
            raise AcceptanceProfileError(
                f"Unknown {name} requirement: {sorted(unknown_fields)[0]}."
            )
        normalized: dict[str, bool | int] = {}
        for field, field_value in value.items():
            expected = field_types[field]
            if expected is bool and not isinstance(field_value, bool):
                raise AcceptanceProfileError(f"{name}.{field} must be true or false.")
            if expected is int and (
                not isinstance(field_value, int) or isinstance(field_value, bool) or field_value < 1
            ):
                raise AcceptanceProfileError(f"{name}.{field} must be a positive whole number.")
            normalized[field] = field_value
        sections[name] = normalized
    return AcceptanceProfile(ACCEPTANCE_PROFILE_VERSION, sections)
