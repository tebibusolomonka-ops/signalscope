import io

import pytest

from signalscope.cli import build_parser, create_user
from signalscope.core.settings import Settings

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    args = build_parser().parse_args(
        ["create-user", "ana@example.org", "--display-name", "Ana", "--system-admin"]
    )

    assert (args.email, args.display_name, args.system_admin, args.password_stdin) == (
        "ana@example.org",
        "Ana",
        True,
        False,
    )


def test_there_is_no_password_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["create-user", "ana@example.org", "--password", "secret"])

    assert "unrecognized arguments" in capsys.readouterr().err


async def test_needs_a_database() -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await create_user(Settings(), "ana@example.org", out, err, ask_password=lambda _: "x")

    assert code == 1
    assert "SIGNALSCOPE_DATABASE_URL" in err.getvalue()
