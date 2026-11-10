"""Reader: readiness of the service (MongoDB reachable and the consumer attached)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.dto import ComponentHealth, HealthResponse
from app.enums import ComponentState, ConsumerState, HealthStatus
from app.exceptions import ServiceNotReadyError

PingDatabase = Callable[[], Awaitable[bool]]
ReadConsumerState = Callable[[], ConsumerState]


class HealthReader:
    def __init__(self, ping_database: PingDatabase, consumer_state: ReadConsumerState) -> None:
        self._ping_database = ping_database
        self._consumer_state = consumer_state

    async def read(self) -> HealthResponse:
        """Raises ``ServiceNotReadyError`` (carrying the same report) when not ready."""
        mongo_ok = await self._ping_database()
        consumer_state = self._consumer_state()
        consumer_ok = consumer_state is ConsumerState.CONSUMING
        ready = mongo_ok and consumer_ok
        report = HealthResponse(
            status=HealthStatus.OK if ready else HealthStatus.UNAVAILABLE,
            mongodb=ComponentHealth(
                ok=mongo_ok, state=(ComponentState.UP if mongo_ok else ComponentState.DOWN).value
            ),
            consumer=ComponentHealth(ok=consumer_ok, state=consumer_state.value),
        )
        if not ready:
            raise ServiceNotReadyError(report)
        return report
