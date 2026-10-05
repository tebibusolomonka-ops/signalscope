from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile


class AcceptanceStatus(StrEnum):
    MET = "met"
    MISSED = "missed"
    WARNING = "warning"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    values: dict[str, bool | None]
    references: dict[str, str]
    warnings: tuple[str, ...] = ()
    facts: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    requirement: str
    status: AcceptanceStatus
    message: str


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    profile_version: int
    checks: tuple[AcceptanceCheck, ...]
    evidence_references: dict[str, str]
    evidence: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return not any(check.status is AcceptanceStatus.MISSED for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_version": self.profile_version,
            "passed": self.passed,
            "requirements_met": [
                check.requirement for check in self.checks if check.status is AcceptanceStatus.MET
            ],
            "requirements_missed": [
                check.requirement
                for check in self.checks
                if check.status is AcceptanceStatus.MISSED
            ],
            "warnings": [
                check.message for check in self.checks if check.status is AcceptanceStatus.WARNING
            ],
            "manual_checks": [
                check.requirement
                for check in self.checks
                if check.status is AcceptanceStatus.MANUAL
            ],
            "checks": [
                {
                    "requirement": check.requirement,
                    "status": check.status.value,
                    "message": check.message,
                }
                for check in self.checks
            ],
            "evidence_references": dict(sorted(self.evidence_references.items())),
            "evidence": self.evidence or {},
        }


class AcceptanceRunner:
    def run(self, profile: AcceptanceProfile, evidence: AcceptanceEvidence) -> AcceptanceResult:
        checks: list[AcceptanceCheck] = []
        for section, requirements in sorted(profile.sections.items()):
            for name, required in sorted(requirements.items()):
                if not isinstance(required, bool) or not required:
                    continue
                key = f"{section}.{name}"
                observed = evidence.values.get(key)
                if observed is True:
                    status = AcceptanceStatus.MET
                    message = "Requirement is met."
                elif observed is False:
                    status = AcceptanceStatus.MISSED
                    message = "Requirement is not met."
                else:
                    status = AcceptanceStatus.MANUAL
                    message = "No factual evidence is available; confirm manually."
                checks.append(AcceptanceCheck(key, status, message))
        checks.extend(
            AcceptanceCheck("evidence", AcceptanceStatus.WARNING, warning)
            for warning in evidence.warnings
        )
        return AcceptanceResult(
            profile.version,
            tuple(checks),
            evidence.references,
            evidence.facts,
        )
