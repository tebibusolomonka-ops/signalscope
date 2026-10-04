from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
    OrganizationDisasterRecoveryDrill,
)


def test_mode_values() -> None:
    assert {mode.value for mode in DisasterRecoveryDrillMode} == {
        "verification_only",
        "restore_test",
    }


def test_status_values() -> None:
    assert {status.value for status in DisasterRecoveryDrillStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
    }


def test_table_name() -> None:
    assert OrganizationDisasterRecoveryDrill.__tablename__ == (
        "organization_disaster_recovery_drills"
    )
