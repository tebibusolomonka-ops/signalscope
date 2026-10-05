import uuid
from datetime import UTC, datetime, timedelta

import pytest

from signalscope.domain.diagnostics.acceptance import AcceptanceRunner, AcceptanceStatus
from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile
from signalscope.domain.diagnostics.disaster_recovery_acceptance import (
    DisasterRecoveryRecords,
    SuccessfulDisasterRecoveryDrill,
    VerifiedOrganizationBackup,
    evaluate_disaster_recovery_acceptance,
)
from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
)

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
ORGANIZATION_ID = uuid.uuid4()
TARGET_ID = uuid.uuid4()


def profile(
    *,
    backup_age: int = 24,
    verification_age: int = 24,
    restore_required: bool = False,
    restore_age: int = 24,
    assets_required: bool = False,
) -> AcceptanceProfile:
    return AcceptanceProfile(
        1,
        {
            "backup": {"verified_backup_exists": True, "max_age_hours": backup_age},
            "disaster_recovery": {
                "verification_drill_exists": True,
                "verification_max_age_hours": verification_age,
                "restore_test_required": restore_required,
                "restore_test_max_age_hours": restore_age,
                "asset_verification_succeeded": assets_required,
            },
        },
    )


def backup(*, hours_old: int = 1, include_assets: bool = True) -> VerifiedOrganizationBackup:
    finished = NOW - timedelta(hours=hours_old)
    return VerifiedOrganizationBackup(
        uuid.uuid4(), finished - timedelta(minutes=2), finished, "a" * 64, include_assets
    )


def drill(
    mode: DisasterRecoveryDrillMode,
    *,
    hours_old: int = 1,
    assets: bool = True,
) -> SuccessfulDisasterRecoveryDrill:
    finished = NOW - timedelta(hours=hours_old)
    return SuccessfulDisasterRecoveryDrill(
        uuid.uuid4(),
        mode,
        DisasterRecoveryDrillStatus.COMPLETED,
        finished - timedelta(minutes=5),
        finished,
        ORGANIZATION_ID,
        TARGET_ID if mode is DisasterRecoveryDrillMode.RESTORE_TEST else None,
        assets,
    )


def statuses(
    acceptance_profile: AcceptanceProfile, records: DisasterRecoveryRecords
) -> dict[str, AcceptanceStatus]:
    evidence = evaluate_disaster_recovery_acceptance(acceptance_profile, records, NOW)
    result = AcceptanceRunner().run(acceptance_profile, evidence)
    return {check.requirement: check.status for check in result.checks}


def test_fresh_verified_backup_and_verification_drill_pass() -> None:
    records = DisasterRecoveryRecords(
        backup(), drill(DisasterRecoveryDrillMode.VERIFICATION_ONLY), None
    )

    result = statuses(profile(), records)

    assert result["backup.verified_backup_exists"] is AcceptanceStatus.MET
    assert result["disaster_recovery.verification_drill_exists"] is AcceptanceStatus.MET
    assert "disaster_recovery.restore_test_required" not in result


@pytest.mark.parametrize("records", [DisasterRecoveryRecords(None, None, None)])
def test_missing_backup_and_verification_drill_miss(records: DisasterRecoveryRecords) -> None:
    result = statuses(profile(), records)

    assert result["backup.verified_backup_exists"] is AcceptanceStatus.MISSED
    assert result["disaster_recovery.verification_drill_exists"] is AcceptanceStatus.MISSED


def test_stale_backup_misses() -> None:
    records = DisasterRecoveryRecords(
        backup(hours_old=25), drill(DisasterRecoveryDrillMode.VERIFICATION_ONLY), None
    )

    assert statuses(profile(), records)["backup.verified_backup_exists"] is AcceptanceStatus.MISSED


def test_stale_verification_drill_misses() -> None:
    records = DisasterRecoveryRecords(
        backup(), drill(DisasterRecoveryDrillMode.VERIFICATION_ONLY, hours_old=25), None
    )

    assert (
        statuses(profile(), records)["disaster_recovery.verification_drill_exists"]
        is AcceptanceStatus.MISSED
    )


def test_restore_test_required_and_present_passes() -> None:
    records = DisasterRecoveryRecords(
        backup(),
        drill(DisasterRecoveryDrillMode.VERIFICATION_ONLY),
        drill(DisasterRecoveryDrillMode.RESTORE_TEST),
    )

    result = statuses(profile(restore_required=True), records)

    assert result["disaster_recovery.restore_test_required"] is AcceptanceStatus.MET


def test_restore_test_required_missing_or_stale_misses() -> None:
    without_restore = DisasterRecoveryRecords(
        backup(), drill(DisasterRecoveryDrillMode.VERIFICATION_ONLY), None
    )
    stale_restore = DisasterRecoveryRecords(
        backup(),
        drill(DisasterRecoveryDrillMode.VERIFICATION_ONLY),
        drill(DisasterRecoveryDrillMode.RESTORE_TEST, hours_old=25),
    )

    assert (
        statuses(profile(restore_required=True), without_restore)[
            "disaster_recovery.restore_test_required"
        ]
        is AcceptanceStatus.MISSED
    )
    assert (
        statuses(profile(restore_required=True), stale_restore)[
            "disaster_recovery.restore_test_required"
        ]
        is AcceptanceStatus.MISSED
    )


@pytest.mark.parametrize("assets", [True, False])
def test_asset_verification_uses_stored_drill_evidence(assets: bool) -> None:
    records = DisasterRecoveryRecords(
        backup(), drill(DisasterRecoveryDrillMode.VERIFICATION_ONLY, assets=assets), None
    )

    result = statuses(profile(assets_required=True), records)

    expected = AcceptanceStatus.MET if assets else AcceptanceStatus.MISSED
    assert result["disaster_recovery.asset_verification_succeeded"] is expected


def test_evidence_contains_ids_timestamps_and_no_tenant_content_or_blob_key() -> None:
    backup_record = backup()
    verification = drill(DisasterRecoveryDrillMode.VERIFICATION_ONLY)
    restore = drill(DisasterRecoveryDrillMode.RESTORE_TEST)

    evidence = evaluate_disaster_recovery_acceptance(
        profile(restore_required=True),
        DisasterRecoveryRecords(backup_record, verification, restore),
        NOW,
    )
    rendered = AcceptanceRunner().run(profile(restore_required=True), evidence).to_dict()
    text = str(rendered)

    assert rendered["evidence_references"] == {
        "backup_export_id": str(backup_record.id),
        "restore_test_drill_id": str(restore.id),
        "verification_drill_id": str(verification.id),
    }
    assert rendered["evidence"]["backup"]["finished_at"] == backup_record.finished_at.isoformat()
    assert rendered["evidence"]["disaster_recovery"]["restore_test_drill"][
        "target_organization_id"
    ] == str(TARGET_ID)
    assert "artifact_key" not in text
    assert "tenant content" not in text
