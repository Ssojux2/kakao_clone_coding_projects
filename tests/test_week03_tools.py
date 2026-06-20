from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import student_parts.week03_build_nanas_logbook as week03_module
from fixed.app_store import AppSQLiteStore
from fixed.session_scope import conversation_session_scope
from fixed.student_api import save_structured_request_payload


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


def test_week03_save_defaults_unmentioned_meeting_to_private_schedule(tmp_path) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    saved = save_structured_request_payload(
        {
            "kind": "group_schedule",
            "title": "개발 미팅",
            "date": "2026-06-22",
            "start_time": "10:00",
            "end_time": "11:00",
            "members": ["철수", "영희"],
            "reason": "모델이 기본 외부 멤버를 추측함",
            "original_text": "내 개발 미팅 2026-06-22 오전 10시에 잡아줘",
        },
        store=store,
    )
    rows = store.list_schedules(limit=10)

    assert saved["kind"] == "personal_schedule"
    assert rows[0]["request_kind"] == "personal_schedule"
    assert rows[0]["attendees"] == ["나"]


def test_week03_saved_schedules_are_visible_from_new_chat_scope(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(week03_module, "CONFIG", replace(week03_module.CONFIG, app_db_path=db_path))
    store = AppSQLiteStore(db_path)
    store.save_structured_request(
        {
            "kind": "personal_schedule",
            "title": "SQLite 장기 기억 일정",
            "date": "2026-06-24",
            "start_time": "14:00",
            "end_time": "15:00",
            "members": ["나"],
        }
    )

    with conversation_session_scope("brand_new_chat"):
        listed = json.loads(week03_module.personal_list_saved_schedules.invoke({"limit": 10}))

    assert listed["tool_name"] == "personal_list_saved_schedules"
    assert listed["schedules"][0]["title"] == "SQLite 장기 기억 일정"
