"""Plain text output for retrieval evaluation reports."""

from collections.abc import Sequence

from signalscope.evaluation.retrieval import RetrievalReport


def format_reports(dataset: str, query_count: int, reports: Sequence[RetrievalReport]) -> str:
    """Numbers only. They say nothing about which method is better in general."""
    lines = [f"Dataset: {dataset}", f"Queries: {query_count}"]
    for report in reports:
        metrics = report.metrics
        lines.append("")
        lines.append(report.mode.capitalize())
        lines.extend(f"Recall@{k}: {metrics.recall[k]:.3f}" for k in report.ks)
        lines.extend(f"MRR@{k}: {metrics.mrr[k]:.3f}" for k in report.ks)
        lines.extend(f"nDCG@{k}: {metrics.ndcg[k]:.3f}" for k in report.ks)
        lines.append(f"Mean: {report.latency.mean_ms:.2f} ms")
        lines.append(f"p50: {report.latency.p50_ms:.2f} ms")
        lines.append(f"p95: {report.latency.p95_ms:.2f} ms")
    return "\n".join(lines) + "\n"
