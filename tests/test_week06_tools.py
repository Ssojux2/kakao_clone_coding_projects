from __future__ import annotations

import json

import fixed.runtime_clock as runtime_clock
from fixed.agent_runtime import AgentRuntime
from fixed.stores import AppSQLiteStore
from student_parts.week06_kanamate_decides_schedule import (
    agent_tool_names,
    find_common_available_slots_dict,
    propose_group_schedule,
)


def test_week06_kana_tools_include_slot_decision_chain() -> None:
    kana_tools = set(agent_tool_names("kana_agent"))

    assert {"collect_member_schedules", "find_common_available_slots", "propose_group_schedule"} <= kana_tools


def test_week06_common_slots_feed_final_decision() -> None:
    target_day = runtime_clock.next_weekday_iso(1)
    slots = find_common_available_slots_dict(
        member_names=["철수", "영희"],
        date_from=target_day,
        date_to=target_day,
        duration_minutes=60,
        limit=1,
    )["candidate_slots"]

    result = json.loads(
        propose_group_schedule.invoke(
            {
                "title": "팀 회의",
                "member_names": ["철수", "영희"],
                "candidate_slots": slots,
                "selected_slot": slots[0],
                "reason": "첫 번째 공통 가능 시간",
            }
        )
    )

    assert result["final_decision"]["status"] == "confirmed"
    assert result["final_decision"]["selected_slot"] == slots[0]


def test_week06_common_slots_accept_iso_datetime_date_bounds() -> None:
    target_day = runtime_clock.next_weekday_iso(3)

    result = find_common_available_slots_dict(
        member_names=["철수", "영희"],
        date_from=f"{target_day}T10:00:00",
        date_to=f"{target_day}T10:00:00",
        duration_minutes=60,
        limit=3,
    )

    assert result["tool_name"] == "find_common_available_slots"
    assert all(slot["date"] == target_day for slot in result["candidate_slots"])
    assert all(row["date"] == target_day for row in result["busy_rows"] if row["member_name"] != "나")


def test_week06_runtime_direct_external_lookup_lists_all_times(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(tmp_path / "external.sqlite3"))
    runtime = AgentRuntime()
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")

    result = runtime.run_agent("외부 팀원들 일정 조회해줘", None)

    assert result.trace["mode"] == "mcp_direct_external_schedule_lookup"
    assert f"{runtime_clock.next_weekday_iso(1)} 11:00-12:00" in result.answer
    assert f"{runtime_clock.next_weekday_iso(2)} 13:00-14:00" in result.answer
    assert f"{runtime_clock.next_weekday_iso(2)} 15:00-16:00" in result.answer
    assert f"{runtime_clock.next_weekday_iso(3)} 14:00-15:00" in result.answer
    assert f"{runtime_clock.next_weekday_iso(3)} 16:00-17:00" in result.answer
    assert "영희의 일정은 확인되지 않았습니다" not in result.answer


def test_week06_runtime_shared_schedule_lookup_understands_other_people_wording(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(tmp_path / "shared_wording.sqlite3"))
    runtime = AgentRuntime()
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")

    result = runtime.run_agent("다른 사람들이 일정이 어떻게 돼 공유 일정에서 확인해줘.", None)

    assert result.trace["mode"] == "mcp_direct_external_schedule_lookup"
    assert "현재 공유 일정 저장소 기준 일정입니다." in result.answer
    assert "철수 | 영업 미팅" in result.answer
    assert "영희 | 리서치 리뷰" in result.answer


def test_week06_runtime_shared_schedule_lookup_includes_my_synced_schedule(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(tmp_path / "shared_with_me.sqlite3"))
    runtime = AgentRuntime()
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    target_day = runtime_clock.next_weekday_iso(1)
    runtime.app_store.save_structured_request(
        {
            "kind": "personal_schedule",
            "title": "전략 회의",
            "date": target_day,
            "start_time": "10:00",
            "end_time": "11:00",
            "members": ["나"],
        }
    )

    result = runtime.run_agent("공유 일정 조회해줘.", None)

    assert result.trace["mode"] == "mcp_direct_external_schedule_lookup"
    assert f"나 | 전략 회의 | {target_day} 10:00-11:00" in result.answer
    assert "철수 | 영업 미팅" in result.answer
