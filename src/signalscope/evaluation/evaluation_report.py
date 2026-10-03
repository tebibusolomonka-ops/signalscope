from dataclasses import asdict, dataclass
from typing import Any

from signalscope.evaluation.manifest import DatasetTask

EVALUATION_REPORT_VERSION = 1


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    report_version: int
    task: DatasetTask
    model: str
    provider: str
    dataset: dict[str, Any]
    created_at: str
    environment: dict[str, Any]
    configuration: dict[str, Any]
    metrics: dict[str, Any]
    timings: dict[str, float]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluation_report(
    *,
    task: DatasetTask,
    model: str,
    provider: str,
    dataset_name: str,
    dataset_fingerprint: str,
    created_at: str,
    configuration: dict[str, Any],
    metrics: dict[str, Any],
    timings: dict[str, float],
    environment: dict[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
) -> EvaluationReport:
    return EvaluationReport(
        report_version=EVALUATION_REPORT_VERSION,
        task=task,
        model=model,
        provider=provider,
        dataset={"name": dataset_name, "fingerprint": dataset_fingerprint},
        created_at=created_at,
        environment={} if environment is None else environment,
        configuration=configuration,
        metrics=metrics,
        timings=timings,
        warnings=warnings,
    )
