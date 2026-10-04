import io
import json
from pathlib import Path

from signalscope.cli import build_parser, validate_production_config
from signalscope.core.settings import Environment, Settings

PASSWORD = "cli-secret-pw"


def production_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "auth_enabled": True,
        "database_url": f"postgresql+asyncpg://admin:{PASSWORD}@db.internal/signalscope",
        "blob_dir": Path("/srv/blobs"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def run(settings: Settings, **options: object) -> tuple[int, str]:
    out = io.StringIO()
    code = validate_production_config(settings, out, **options)  # type: ignore[arg-type]
    return code, out.getvalue()


def test_arguments() -> None:
    args = build_parser().parse_args(["validate-production-config", "--json"])
    assert args.json is True


def test_clean_configuration_exits_zero() -> None:
    code, output = run(production_settings())

    assert code == 0
    assert "ERROR" not in output


def test_bad_configuration_exits_nonzero() -> None:
    code, output = run(production_settings(auth_enabled=False))

    assert code == 1
    assert "ERROR: authentication" in output


def test_output_never_prints_the_password() -> None:
    _, text_output = run(production_settings(auth_enabled=False))
    _, json_output = run(production_settings(auth_enabled=False), json_output=True)

    assert PASSWORD not in text_output
    assert PASSWORD not in json_output
    json.loads(json_output)
