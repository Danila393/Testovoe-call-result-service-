from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DEFAULT_LIMIT: Final = 100
MAX_LIMIT: Final = 1000
# MongoDB $skip takes an int64; a sane bound turns absurd offsets into 422, not 500.
MAX_OFFSET: Final = 1_000_000


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int = DEFAULT_LIMIT
    offset: int = 0
