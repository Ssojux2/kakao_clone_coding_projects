from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace

import fixed.runtime_clock as runtime_clock
import student_parts.week05_load_kanas_past_conversations as week05_module
from fixed.app_store import AppSQLiteStore
from fixed.external_people_store import ExternalPeopleSQLiteStore
from fixed.session_scope import conversation_session_scope
from fixed.store_base import new_id


def _mcp_text(result: object) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n".join(
            item["text"]
            for item in result
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return json.dumps(result, ensure_ascii=False)


def test_week05_external_store_refreshes_stale_demo_schedules(tmp_path) -> None:
    db_path = tmp_path / "external.sqlite3"
    ExternalPeopleSQLiteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE external_schedules SET date = '2026-05-19'")

    refreshed = ExternalPeopleSQLiteStore(db_path)
    rows = refreshed.extract_schedules_from_history(
        member_names=[],
        date_from=runtime_clock.next_weekday_iso(1),
        date_to=runtime_clock.next_weekday_iso(3),
    )

    assert len(rows) == 5
    assert {row["date"] for row in rows} == {
        runtime_clock.next_weekday_iso(1),
        runtime_clock.next_weekday_iso(2),
        runtime_clock.next_weekday_iso(3),
    }
    assert {row["member_name"] for row in rows} == {"철수", "영희"}


def test_week05_mcp_stdio_server_loads_tools_and_returns_current_schedules(tmp_path) -> None:
    async def run() -> dict[str, object]:
        tools = {
            tool.name: tool
            for tool in await week05_module.load_langchain_mcp_tools(db_path=tmp_path / "mcp.sqlite3")
        }
        result = await tools["extract_schedules_from_history"].ainvoke(
            {
                "member_names": [],
                "date_from": runtime_clock.next_weekday_iso(1),
                "date_to": runtime_clock.next_weekday_iso(3),
            }
        )
        return {"tool_names": set(tools), "payload": json.loads(_mcp_text(result))}

    output = asyncio.run(run())
    payload = output["payload"]

    assert output["tool_names"] == {
        "search_previous_conversations",
        "load_conversation_messages",
        "extract_schedules_from_history",
        "create_shared_schedule",
        "delete_shared_schedule",
        "list_shared_schedules",
    }
    assert len(payload["rows"]) == 5
    assert {row["member_name"] for row in payload["rows"]} == {"철수", "영희"}


def test_week05_mcp_shared_schedule_tool_registers_my_schedule(tmp_path) -> None:
    db_path = tmp_path / "mcp_shared.sqlite3"

    created = json.loads(
        week05_module.call_mcp_tool_sync(
            "create_shared_schedule",
            {
                "member_name": "나",
                "title": "개인 집중 작업",
                "date": "2026-06-12",
                "start_time": "10:00",
                "end_time": "11:00",
                "notes": "테스트 공유 일정",
                "source_conversation_id": "app:req_test",
                "schedule_id": "shared_test",
            },
            db_path=db_path,
        )
    )
    rows = ExternalPeopleSQLiteStore(db_path).extract_schedules_from_history(
        member_names=["나"],
        date_from="2026-06-12",
        date_to="2026-06-12",
    )
    listed = json.loads(
        week05_module.call_mcp_tool_sync(
            "list_shared_schedules",
            {
                "date_from": "2026-06-12",
                "date_to": "2026-06-12",
            },
            db_path=db_path,
        )
    )

    assert created["shared_schedule"]["sync_status"] == "created"
    assert rows == [
        {
            "member_name": "나",
            "title": "개인 집중 작업",
            "date": "2026-06-12",
            "start_time": "10:00",
            "end_time": "11:00",
            "notes": "테스트 공유 일정",
            "source_conversation_id": "app:req_test",
        }
    ]
    assert listed["rows"] == [
        {
            "schedule_id": "shared_test",
            "member_name": "나",
            "title": "개인 집중 작업",
            "date": "2026-06-12",
            "start_time": "10:00",
            "end_time": "11:00",
            "notes": "테스트 공유 일정",
            "source_conversation_id": "app:req_test",
        }
    ]
    assert "나 | 개인 집중 작업 | 2026-06-12 10:00-11:00" in listed["schedule_summary"]


def test_week05_personal_schedule_save_syncs_to_shared_mcp_store(tmp_path, monkeypatch) -> None:
    shared_db_path = tmp_path / "shared.sqlite3"
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(shared_db_path))
    store = AppSQLiteStore(tmp_path / "app.sqlite3")

    saved = store.save_structured_request(
        {
            "kind": "personal_schedule",
            "title": "개인 코칭",
            "date": "2026-06-12",
            "start_time": "11:00",
            "end_time": "12:00",
            "members": ["나"],
            "reason": "테스트 일정",
            "original_text": "2026-06-12 오전 11시에 개인 코칭 일정 잡아줘",
        }
    )
    rows = ExternalPeopleSQLiteStore(shared_db_path).extract_schedules_from_history(
        member_names=["나"],
        date_from="2026-06-12",
        date_to="2026-06-12",
    )

    assert saved["shared_sync"]["ok"] is True
    assert rows[0]["title"] == "개인 코칭"
    assert rows[0]["source_conversation_id"] == f"app:{saved['request_id']}"


def test_week05_personal_schedule_delete_removes_shared_copy(tmp_path, monkeypatch) -> None:
    shared_db_path = tmp_path / "shared_delete.sqlite3"
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(shared_db_path))
    store = AppSQLiteStore(tmp_path / "app.sqlite3")

    saved = store.save_structured_request(
        {
            "kind": "personal_schedule",
            "title": "삭제될 개인 일정",
            "date": "2026-06-13",
            "start_time": "09:00",
            "end_time": "10:00",
            "members": ["나"],
        }
    )
    schedule_id = next(row["id"] for row in saved["saved_rows"] if row["table"] == "schedules")

    deleted = store.delete_schedule(schedule_id)
    rows = ExternalPeopleSQLiteStore(shared_db_path).extract_schedules_from_history(
        member_names=["나"],
        date_from="2026-06-13",
        date_to="2026-06-13",
    )

    assert deleted["title"] == "삭제될 개인 일정"
    assert rows == []


def test_week05_personal_schedule_update_changes_shared_copy(tmp_path, monkeypatch) -> None:
    shared_db_path = tmp_path / "shared_update.sqlite3"
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(shared_db_path))
    store = AppSQLiteStore(tmp_path / "app.sqlite3")

    saved = store.save_structured_request(
        {
            "kind": "personal_schedule",
            "title": "전략 회의",
            "date": "2026-06-03",
            "start_time": "10:00",
            "end_time": "11:00",
            "members": ["나"],
        }
    )
    schedule_id = next(row["id"] for row in saved["saved_rows"] if row["table"] == "schedules")

    updated = store.update_schedule(
        schedule_id=schedule_id,
        title="전략 회의 수정",
        date="2026-06-04",
        start_time="14:00",
        end_time="15:00",
    )
    old_rows = ExternalPeopleSQLiteStore(shared_db_path).extract_schedules_from_history(
        member_names=["나"],
        date_from="2026-06-03",
        date_to="2026-06-03",
    )
    new_rows = ExternalPeopleSQLiteStore(shared_db_path).extract_schedules_from_history(
        member_names=["나"],
        date_from="2026-06-04",
        date_to="2026-06-04",
    )

    assert updated["shared_sync"]["status"] == "updated"
    assert old_rows == []
    assert new_rows[0]["title"] == "전략 회의 수정"
    assert new_rows[0]["start_time"] == "14:00"


def test_week05_mcp_shared_schedule_tool_deletes_by_app_source(tmp_path) -> None:
    db_path = tmp_path / "mcp_delete_shared.sqlite3"
    week05_module.call_mcp_tool_sync(
        "create_shared_schedule",
        {
            "member_name": "나",
            "title": "삭제 대상 공유 일정",
            "date": "2026-06-12",
            "start_time": "10:00",
            "end_time": "11:00",
            "source_conversation_id": "app:req_delete",
            "schedule_id": "shared_delete_test",
        },
        db_path=db_path,
    )

    deleted = json.loads(
        week05_module.call_mcp_tool_sync(
            "delete_shared_schedule",
            {"source_conversation_id": "app:req_delete"},
            db_path=db_path,
        )
    )
    rows = ExternalPeopleSQLiteStore(db_path).extract_schedules_from_history(
        member_names=["나"],
        date_from="2026-06-12",
        date_to="2026-06-12",
    )

    assert deleted["deleted_count"] == 1
    assert rows == []


def test_week05_mcp_stdio_server_returns_cheolsu_younghee_schedules(tmp_path) -> None:
    async def run() -> dict[str, object]:
        tools = {
            tool.name: tool
            for tool in await week05_module.load_langchain_mcp_tools(db_path=tmp_path / "mcp_people.sqlite3")
        }
        result = await tools["extract_schedules_from_history"].ainvoke(
            {
                "member_names": ["철수", "영희"],
                "date_from": runtime_clock.next_weekday_iso(1),
                "date_to": runtime_clock.next_weekday_iso(3),
            }
        )
        return json.loads(_mcp_text(result))

    payload = asyncio.run(run())

    assert len(payload["rows"]) == 5
    assert {row["member_name"] for row in payload["rows"]} == {"철수", "영희"}
    assert {row["title"] for row in payload["rows"]} == {"영업 미팅", "파트너 콜", "리서치 리뷰", "마케팅 싱크", "콘텐츠 점검"}
    assert "철수 | 영업 미팅 |" in payload["schedule_summary"]
    assert f"{runtime_clock.next_weekday_iso(1)} 11:00-12:00" in payload["schedule_summary"]
    assert "영희 | 리서치 리뷰 |" in payload["schedule_summary"]
    assert f"{runtime_clock.next_weekday_iso(2)} 13:00-14:00" in payload["schedule_summary"]
    assert "영희 | 마케팅 싱크 |" in payload["schedule_summary"]
    assert f"{runtime_clock.next_weekday_iso(2)} 15:00-16:00" in payload["schedule_summary"]
    assert "영희 | 콘텐츠 점검 |" in payload["schedule_summary"]
    assert f"{runtime_clock.next_weekday_iso(3)} 16:00-17:00" in payload["schedule_summary"]


def test_week05_default_external_lookup_expands_next_tuesday_to_thursday(tmp_path) -> None:
    async def run() -> dict[str, object]:
        tools = {
            tool.name: tool
            for tool in await week05_module.load_langchain_mcp_tools(db_path=tmp_path / "mcp_default.sqlite3")
        }
        result = await tools["extract_schedules_from_history"].ainvoke(
            {
                "member_names": ["철수", "영희"],
                "date_from": runtime_clock.next_weekday_iso(1),
                "date_to": runtime_clock.next_weekday_iso(1),
            }
        )
        return json.loads(_mcp_text(result))

    payload = asyncio.run(run())

    assert len(payload["rows"]) == 5
    assert {row["member_name"] for row in payload["rows"]} == {"철수", "영희"}
    assert {row["date"] for row in payload["rows"]} == {
        runtime_clock.next_weekday_iso(1),
        runtime_clock.next_weekday_iso(2),
        runtime_clock.next_weekday_iso(3),
    }


def test_week05_sync_mcp_helper_works_inside_running_event_loop(tmp_path) -> None:
    async def run() -> str:
        return week05_module.call_mcp_tool_sync(
            "extract_schedules_from_history",
            {
                "member_names": ["철수"],
                "date_from": runtime_clock.next_weekday_iso(1),
                "date_to": runtime_clock.next_weekday_iso(3),
            },
            db_path=tmp_path / "loop.sqlite3",
        )

    payload = json.loads(asyncio.run(run()))

    assert payload["tool_name"] == "extract_schedules_from_history"
    assert {row["member_name"] for row in payload["rows"]} == {"철수"}


def test_week05_external_history_tools_return_member_schedules() -> None:
    conversations = json.loads(
        week05_module.search_previous_conversations.invoke({"query": "다음 주", "member_names": ["철수"], "limit": 3})
    )
    schedules = json.loads(
        week05_module.extract_schedules_from_history.invoke(
            {"member_names": [], "date_from": "2000-01-01", "date_to": "2999-12-31"}
        )
    )

    assert conversations["rows"][0]["member_name"] == "철수"
    assert {row["member_name"] for row in schedules["rows"]} == {"철수", "영희"}


def test_week05_collect_member_schedules_uses_default_external_members() -> None:
    result = json.loads(
        week05_module.collect_member_schedules.invoke(
            {"member_names": [], "date_from": "2000-01-01", "date_to": "2999-12-31"}
        )
    )

    assert result["members"] == ["나", "철수", "영희"]
    assert {row["member_name"] for row in result["rows"] if row["member_name"] != "나"} == {"철수", "영희"}
    assert "철수 | 영업 미팅 |" in result["schedule_summary"]
    assert "영희 | 마케팅 싱크 |" in result["schedule_summary"]
    assert "15:00-16:00" in result["schedule_summary"]
    assert "영희 | 콘텐츠 점검 |" in result["schedule_summary"]
    assert "16:00-17:00" in result["schedule_summary"]


def test_week05_collect_member_schedules_reads_saved_sqlite_not_other_chat_memory(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(week05_module, "CONFIG", replace(week05_module.CONFIG, app_db_path=db_path))
    week05_module.PERSONAL_SCHEDULES.clear()
    week05_module.PERSONAL_SCHEDULES.append(
        {
            "id": "personal_other_chat",
            "title": "다른 대화 임시 일정",
            "date": "2026-06-12",
            "start_time": "09:00",
            "end_time": "10:00",
            "attendees": ["나"],
            "session_id": "other_chat",
        }
    )
    AppSQLiteStore(db_path).save_structured_request(
        {
            "kind": "group_schedule",
            "title": "SQLite 저장 일정",
            "date": "2026-06-12",
            "start_time": "11:00",
            "end_time": "12:00",
            "members": ["나"],
        }
    )

    with conversation_session_scope("new_chat"):
        result = json.loads(
            week05_module.collect_member_schedules.invoke(
                {"member_names": [], "date_from": "2026-06-12", "date_to": "2026-06-12"}
            )
        )

    my_titles = {row["title"] for row in result["rows"] if row["member_name"] == "나"}
    week05_module.PERSONAL_SCHEDULES.clear()

    assert "SQLite 저장 일정" in my_titles
    assert "다른 대화 임시 일정" not in my_titles


def test_week05_collect_member_schedules_reads_external_rows_through_mcp_env(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "env.sqlite3"
    ExternalPeopleSQLiteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO external_schedules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("extsch"),
                "현수",
                "MCP 전용 일정",
                runtime_clock.next_weekday_iso(1),
                "16:00",
                "17:00",
                "ext_hs",
                "환경 변수로 주입한 MCP DB에만 있는 일정",
            ),
        )
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(db_path))

    result = json.loads(
        week05_module.collect_member_schedules.invoke(
            {
                "member_names": ["현수"],
                "date_from": runtime_clock.next_weekday_iso(1),
                "date_to": runtime_clock.next_weekday_iso(3),
            }
        )
    )
    external_rows = [row for row in result["rows"] if row["member_name"] != "나"]

    assert len(external_rows) == 1
    assert any(row["title"] == "MCP 전용 일정" for row in external_rows)
