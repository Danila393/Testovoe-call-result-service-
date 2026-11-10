from __future__ import annotations

import json
from typing import Any


def message(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "call_id": "call_0001",
        "campaign_id": "camp_001",
        "campaign_name": "Напоминание о платеже",
        "campaign_created_at": "2026-10-20T10:00:00Z",
        "phone": "79001234567",
        "status": "success",
        "created_at": "2026-10-20T10:06:00Z",
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not ...}


def message_bytes(**overrides: Any) -> bytes:
    return json.dumps(message(**overrides), ensure_ascii=False).encode()
