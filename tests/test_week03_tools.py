from __future__ import annotations

import json
from uuid import uuid4

import student_parts.week03_build_nanas_logbook as week03_module


def test_week03_structured_request_persists_to_sqlite() -> None:
    token = f"week3-real-{uuid4().hex[:8]}"
    payload = {
        "kind": "todo",
        "title": f"{token} 회고 준비",
        "date": "2026-05-20",
        "priority": "high",
        "reason": "수업 테스트",
        "original_text": f"{token} 2026-05-20 회고 준비 할 일 추가해줘",
    }

    saved = json.loads(week03_module.save_structured_request.invoke({"payload": payload}))
    row = json.loads(week03_module.get_saved_request.invoke({"request_id": saved["request_id"]}))["row"]
    rows = json.loads(week03_module.list_saved_requests.invoke({"kind": "todo"}))["rows"]

    assert saved["kind"] == "todo"
    assert row["title"] == payload["title"]
    assert any(item["request_id"] == saved["request_id"] for item in rows)
