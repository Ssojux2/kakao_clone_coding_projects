from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import student_parts.week03_build_nanas_logbook as week03_module
from fixed.app_store import AppSQLiteStore
from fixed.session_scope import conversation_session_scope
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES
from student_parts.week03_build_nanas_logbook import save_structured_request_payload


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


def test_week03_save_preserves_llm_kind_and_members(tmp_path) -> None:
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

    assert saved["kind"] == "group_schedule"
    assert rows[0]["request_kind"] == "group_schedule"
    assert rows[0]["attendees"] == ["철수", "영희"]


def test_week03_save_unwraps_structured_request_before_sqlite(tmp_path) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    saved = save_structured_request_payload(
        {
            "ok": True,
            "tool_name": "extract_schedule_request",
            "base_date": "2026-06-21",
            "structured_request": {
                "kind": "personal_schedule",
                "title": "개인 코칭",
                "date": "2026-06-22",
                "start_time": "10:00",
                "end_time": "11:00",
                "members": ["나"],
                "reason": "구조화된 tool 결과",
                "original_text": "내일 오전 10시에 개인 코칭 저장해줘",
            },
        },
        store=store,
    )
    row = store.get_saved_request(saved["request_id"])
    schedules = store.list_schedules(limit=10)

    assert saved["kind"] == "personal_schedule"
    assert row is not None
    assert row["kind"] == "personal_schedule"
    assert json.loads(row["raw_json"])["title"] == "개인 코칭"
    assert schedules[0]["title"] == "개인 코칭"


def test_week03_save_structures_raw_text_before_sqlite(tmp_path, monkeypatch) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")

    def fake_extract_structured_request(text: str) -> week03_module.StructuredRequest:
        return week03_module.StructuredRequest(
            kind="todo",
            title="회고 준비",
            date="2026-06-23",
            priority="high",
            reason="자연어 저장 전 구조화",
            original_text=text,
        )

    monkeypatch.setattr(week03_module, "extract_structured_request", fake_extract_structured_request)

    saved = save_structured_request_payload("2026-06-23까지 회고 준비 할 일 추가해줘", store=store)
    row = store.get_saved_request(saved["request_id"])

    assert saved["kind"] == "todo"
    assert row is not None
    assert row["title"] == "회고 준비"
    assert json.loads(row["raw_json"])["original_text"] == "2026-06-23까지 회고 준비 할 일 추가해줘"


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


def test_week03_personal_create_schedule_also_persists_to_sqlite(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(week03_module, "CONFIG", replace(week03_module.CONFIG, app_db_path=db_path))

    with conversation_session_scope("same_chat"):
        created = json.loads(
            week03_module.personal_create_schedule.invoke(
                {
                    "title": "내일 미팅",
                    "date": "2026-06-21",
                    "start_time": "10:00",
                    "end_time": "미정",
                    "attendees": ["나"],
                }
            )
        )
        listed = json.loads(week03_module.personal_list_saved_schedules.invoke({"limit": 10}))

    schedules = AppSQLiteStore(db_path).list_schedules(limit=10)

    assert created["tool_name"] == "personal_create_schedule"
    assert created["sqlite_save"]["tool_name"] == "save_structured_request"
    assert created["sqlite_save"]["saved_rows"][1]["table"] == "schedules"
    assert listed["schedules"][0]["title"] == "내일 미팅"
    assert schedules[0]["date"] == "2026-06-21"
    assert schedules[0]["start_time"] == "10:00"


def test_week03_personal_schedule_survives_restart_memory_reset(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(week03_module, "CONFIG", replace(week03_module.CONFIG, app_db_path=db_path))
    PERSONAL_SCHEDULES.clear()

    with conversation_session_scope("before_restart"):
        created = json.loads(
            week03_module.personal_create_schedule.invoke(
                {
                    "title": "재시작 후 확인할 개인 일정",
                    "date": "2026-06-25",
                    "start_time": "09:30",
                    "end_time": "10:00",
                    "attendees": ["나"],
                }
            )
        )

    PERSONAL_SCHEDULES.clear()
    fresh_store_after_restart = AppSQLiteStore(db_path)

    with conversation_session_scope("after_restart"):
        listed = json.loads(week03_module.personal_list_saved_schedules.invoke({"limit": 10}))

    assert fresh_store_after_restart.list_schedules(limit=10)[0]["title"] == "재시작 후 확인할 개인 일정"
    assert listed["schedules"][0]["schedule_id"] == created["created_schedule"]["id"]
    assert listed["schedules"][0]["start_time"] == "09:30"


def test_week03_date_filtered_lookup_finds_tomorrow_after_many_old_schedules(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(week03_module, "CONFIG", replace(week03_module.CONFIG, app_db_path=db_path))
    store = AppSQLiteStore(db_path)
    for index in range(60):
        store.save_structured_request(
            {
                "kind": "personal_schedule",
                "title": f"오래된 5월 일정 {index}",
                "date": "2026-05-21",
                "start_time": "10:00",
                "end_time": "11:00",
                "members": ["나"],
            }
        )

    week03_module.save_structured_request.invoke(
        {
            "payload": {
                "kind": "personal_schedule",
                "title": "개발 미팅",
                "date": "2026-06-21",
                "start_time": "10:00",
                "end_time": "11:00",
                "members": ["나"],
                "original_text": "내일 오전 10시에 개발 미팅 잡아줘.",
            }
        }
    )

    listed = json.loads(
        week03_module.personal_list_saved_schedules.invoke(
            {
                "limit": 10,
                "date_from": "2026-06-21",
                "date_to": "2026-06-21",
            }
        )
    )

    assert listed["filters"]["date_from"] == "2026-06-21"
    assert [row["title"] for row in listed["schedules"]] == ["개발 미팅"]
    assert listed["schedules"][0]["request_kind"] == "personal_schedule"


def test_week03_personal_list_saved_schedules_hides_group_schedules_by_default(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(tmp_path / "external.sqlite3"))
    monkeypatch.setattr(week03_module, "CONFIG", replace(week03_module.CONFIG, app_db_path=db_path))
    store = AppSQLiteStore(db_path)
    store.save_structured_request(
        {
            "kind": "group_schedule",
            "title": "공유 팀 회의",
            "date": "2026-07-23",
            "start_time": "15:00",
            "end_time": "16:00",
            "members": ["민준", "서연"],
        }
    )

    default_listed = json.loads(week03_module.personal_list_saved_schedules.invoke({"limit": 10}))
    group_listed = json.loads(
        week03_module.personal_list_saved_schedules.invoke({"limit": 10, "kind": "group_schedule"})
    )

    assert default_listed["filters"]["kind"] == "personal_schedule"
    assert default_listed["schedules"] == []
    assert [row["title"] for row in group_listed["schedules"]] == ["공유 팀 회의"]


def test_week03_personal_delete_saved_schedule_removes_single_row(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(tmp_path / "external.sqlite3"))
    monkeypatch.setattr(week03_module, "CONFIG", replace(week03_module.CONFIG, app_db_path=db_path))
    store = AppSQLiteStore(db_path)
    store.save_structured_request(
        {
            "kind": "personal_schedule",
            "title": "단건 삭제 대상 일정",
            "date": "2026-07-24",
            "start_time": "13:00",
            "end_time": "14:00",
            "members": ["나"],
        }
    )
    target = store.list_schedules(limit=10)[0]

    deleted = json.loads(
        week03_module.personal_delete_saved_schedule.invoke({"schedule_id": target["schedule_id"]})
    )

    assert deleted["ok"] is True
    assert deleted["tool_name"] == "personal_delete_saved_schedule"
    assert deleted["schedule_id"] == target["schedule_id"]
    assert deleted["deleted"]["title"] == "단건 삭제 대상 일정"
    assert store.list_schedules(limit=10) == []


def test_week03_personal_delete_saved_schedule_missing_id_returns_not_found(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(week03_module, "CONFIG", replace(week03_module.CONFIG, app_db_path=db_path))
    AppSQLiteStore(db_path)

    result = json.loads(
        week03_module.personal_delete_saved_schedule.invoke({"schedule_id": "sch_does_not_exist"})
    )

    assert result["ok"] is False
    assert result["deleted"] is None
    assert result["schedule_id"] == "sch_does_not_exist"
