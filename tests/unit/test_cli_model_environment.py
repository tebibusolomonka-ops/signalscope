import io
import json

from signalscope.cli import build_parser, model_environment


def test_model_environment_arguments() -> None:
    plain = build_parser().parse_args(["model-environment"])
    structured = build_parser().parse_args(["model-environment", "--json"])

    assert plain.json is False
    assert structured.json is True


def test_model_environment_json_output_has_no_secrets() -> None:
    out = io.StringIO()

    assert model_environment(out, json_output=True) == 0
    report = json.loads(out.getvalue())
    assert set(report["models"]) == {"embedding", "reranker", "gliner", "gliner2", "qwen"}
    assert "token" not in out.getvalue().lower()
    assert "password" not in out.getvalue().lower()
