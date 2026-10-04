from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.deployment import (
    DeploymentDiagnosticsService,
    alembic_migration_head,
)


def test_without_database_reports_config_and_head() -> None:
    report = DeploymentDiagnosticsService(Settings()).without_database()

    assert report.readiness is None
    assert report.queues == ()
    assert report.migration_current is None
    assert report.migration_head
    # No database configured, so the configuration cannot be production-healthy.
    assert report.healthy is False


def test_migration_head_matches_code() -> None:
    report = DeploymentDiagnosticsService(
        Settings(), migration_head=lambda: "abc123"
    ).without_database()

    assert report.migration_head == "abc123"
    assert report.migration_up_to_date is False


def test_alembic_migration_head_is_a_revision() -> None:
    head = alembic_migration_head()

    assert isinstance(head, str) and head


def test_to_dict_has_the_expected_shape() -> None:
    data = DeploymentDiagnosticsService(Settings()).without_database().to_dict()

    assert set(data) == {
        "healthy",
        "environment",
        "production_config",
        "readiness",
        "queues",
        "migration",
    }
    assert data["readiness"] is None
    assert data["migration"]["up_to_date"] is False
