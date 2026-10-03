import hashlib
import unicodedata
from datetime import timedelta

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.sources.scheduling import Clock
from signalscope.domain.users.email import InvalidEmailError, normalize_email
from signalscope.domain.users.throttle import AuthenticationThrottle


def login_identifier(email: str) -> str:
    """Return a stable one-way identifier without retaining the email address."""
    try:
        value = normalize_email(email)
    except InvalidEmailError:
        value = unicodedata.normalize("NFKC", email).strip().casefold()
    return hashlib.sha256(value.encode()).hexdigest()


class LoginThrottleService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        *,
        window_seconds: int,
        max_failures: int,
        block_seconds: int,
    ) -> None:
        self.session = session
        self.clock = clock
        self.window = timedelta(seconds=window_seconds)
        self.max_failures = max_failures
        self.block = timedelta(seconds=block_seconds)

    async def is_blocked(self, identifier: str) -> bool:
        blocked_until = await self.session.scalar(
            select(AuthenticationThrottle.blocked_until).where(
                AuthenticationThrottle.identifier == identifier
            )
        )
        return blocked_until is not None and blocked_until > self.clock()

    async def record_failure(self, identifier: str) -> None:
        now = self.clock()
        table = AuthenticationThrottle.__table__
        reset = table.c.window_started_at <= now - self.window
        next_count = case((reset, 1), else_=table.c.failure_count + 1)
        reset_block = now + self.block if self.max_failures == 1 else None
        next_block = case(
            (reset, reset_block),
            (next_count >= self.max_failures, now + self.block),
            else_=table.c.blocked_until,
        )
        statement = insert(AuthenticationThrottle).values(
            identifier=identifier,
            failure_count=1,
            window_started_at=now,
            blocked_until=reset_block,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[AuthenticationThrottle.identifier],
            set_={
                "failure_count": next_count,
                "window_started_at": case((reset, now), else_=table.c.window_started_at),
                "blocked_until": next_block,
                "updated_at": now,
            },
        )
        await self.session.execute(statement)
        await self.session.commit()

    async def clear(self, identifier: str) -> None:
        await self.session.execute(
            delete(AuthenticationThrottle).where(AuthenticationThrottle.identifier == identifier)
        )
        await self.session.commit()
