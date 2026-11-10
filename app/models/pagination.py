from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DEFAULT_LIMIT: Final = 100
MAX_LIMIT: Final = 1000


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int = DEFAULT_LIMIT
    offset: int = 0
