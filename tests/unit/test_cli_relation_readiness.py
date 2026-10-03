import json
from io import StringIO
from pathlib import Path

from signalscope.cli import build_parser, check_relation_readiness_command


def _files(tmp_path: Path, precision: float = 0.9) -> tuple[Path, Path]:
    report = tmp_path / "report.json"
    profile = tmp_path / "profile.json"
    report.write_text(
        json.dumps(
            {
                "task": "relation_evaluation",
                "micro_precision": precision,
                "micro_recall": 0.8,
                "micro_f1": 0.85,
                "reference_triple_count": 10,
                "per_type": {},
            }
        ),
        encoding="utf-8",
    )
    profile.write_text(
        json.dumps(
            {
                "profile_version": 1,
                "requirements": {"minimum_micro_precision": 0.8},
            }
        ),
        encoding="utf-8",
    )
    return report, profile


def test_parser_accepts_relation_readiness_command(tmp_path: Path) -> None:
    report, profile = _files(tmp_path)
    args = build_parser().parse_args(
        ["check-relation-readiness", str(report), str(profile), "--json"]
    )
    assert args.command == "check-relation-readiness"
    assert args.json is True


def test_command_reports_pass_as_json(tmp_path: Path) -> None:
    report, profile = _files(tmp_path)
    out = StringIO()
    assert check_relation_readiness_command(report, profile, json_output=True, out=out) == 0
    assert json.loads(out.getvalue())["passed"] is True


def test_command_reports_missed_requirement(tmp_path: Path) -> None:
    report, profile = _files(tmp_path, precision=0.7)
    out = StringIO()
    assert check_relation_readiness_command(report, profile, out=out) == 2
    assert "met no" in out.getvalue()
