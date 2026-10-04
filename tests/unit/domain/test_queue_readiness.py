import pytest
from sqlalchemy.exc import OperationalError

from signalscope.domain.diagnostics.queue_readiness import QueueReadinessService

pytestmark = pytest.mark.anyio


class FailingSession:
    async def scalar(self, _statement: object) -> int:
        raise OperationalError("SELECT count", {}, Exception("no connection"))


async def test_query_failure_is_reported_per_queue() -> None:
    report = await QueueReadinessService(FailingSession()).observe()

    assert report.queues
    assert report.all_queryable is False
    for queue in report.queues:
        assert queue.query_available is False
        assert queue.waiting == 0
        assert queue.running == 0
        assert queue.oldest_waiting_age_seconds is None
        assert queue.expired_leases == 0
