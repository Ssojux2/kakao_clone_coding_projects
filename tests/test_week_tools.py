from __future__ import annotations

import json
from dataclasses import replace

import fixed.runtime_clock as runtime_clock
import student_parts.week03_build_nanas_logbook as week03_module
from fixed.stores import AppSQLiteStore
from golden_cases import GOLDEN_CASES, find_case_by_input, harness_prompt_examples, sample_prompts
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES, personal_create_schedule, week01_tools
from student_parts.week02_structure_natural_language_requests import week02_tools
from student_parts.week03_build_nanas_logbook import delete_saved_schedules_dict, week03_tools
from student_parts.week04_retrieve_nanas_memory import week04_tools
from student_parts.week05_load_kanas_past_conversations import extract_schedules_from_history_dict, week05_tools
from student_parts.week06_kanamate_decides_schedule import (
    agent_tool_names,
    find_common_available_slots_dict,
    kana_system_prompt,
    nana_system_prompt,
    supervisor_system_prompt,
)


def _tool_names(tools: list[object]) -> set[str]:
    return {getattr(item, "name", getattr(item, "__name__", str(item))) for item in tools}


def test_prompt_harness_is_the_shared_reference() -> None:
    examples = harness_prompt_examples()

    assert [case["input"] for case in GOLDEN_CASES] == sample_prompts()
    assert [case["id"] for case in GOLDEN_CASES] == [example["id"] for example in examples]
    assert find_case_by_input(GOLDEN_CASES[0]["input"]) == GOLDEN_CASES[0]


def test_harness_prompts_are_embedded_in_agent_prompts() -> None:
    supervisor_prompt = supervisor_system_prompt()
    nana_prompt = nana_system_prompt()
    kana_prompt = kana_system_prompt()

    for case in GOLDEN_CASES:
        assert case["input"] in supervisor_prompt
        if case["expected_agent"] == "nana_agent":
            assert case["input"] in nana_prompt
        else:
            assert case["input"] in kana_prompt


def test_expected_tools_are_exposed_to_prompt_driven_agents() -> None:
    supervisor_tools = set(agent_tool_names("supervisor"))
    nana_tools = set(agent_tool_names("nana_agent"))
    kana_tools = set(agent_tool_names("kana_agent"))

    assert supervisor_tools == {"nana_agent", "kana_agent"}
    assert "personal_create_schedule" in nana_tools
    assert "save_structured_request" in nana_tools
    assert "personal_update_saved_schedule" in nana_tools
    assert "search_personal_references" in nana_tools
    assert "search_saved_requests" in nana_tools
    assert "extract_schedule_request" in kana_tools
    assert "collect_member_schedules" in kana_tools
    assert "decide_final_slot" in kana_tools

    for case in GOLDEN_CASES:
        expected_tools = case.get("expected_tools") or [case["expected_tool"]]
        target_tools = nana_tools if case["expected_agent"] == "nana_agent" else kana_tools
        assert set(expected_tools) <= target_tools


def test_week_tool_lists_accumulate_previous_weeks() -> None:
    week1 = _tool_names(week01_tools())
    week2 = _tool_names(week02_tools())
    week3 = _tool_names(week03_tools())
    week4 = _tool_names(week04_tools())
    week5 = _tool_names(week05_tools())

    assert week1 == {"personal_create_schedule", "personal_list_schedules", "personal_delete_schedule"}
    assert week1 <= week2
    assert "extract_schedule_request" in week2
    assert week2 <= week3
    assert {"save_structured_request", "list_saved_requests", "get_saved_request", "personal_update_saved_schedule"} <= week3
    assert week3 <= week4
    assert {"add_personal_reference", "search_personal_references", "search_saved_requests"} <= week4
    assert week4 <= week5
    assert {"search_previous_conversations", "extract_schedules_from_history", "collect_member_schedules"} <= week5


def test_week1_create_schedule_returns_db_ready_structured_output(tmp_path) -> None:
    PERSONAL_SCHEDULES.clear()

    result = json.loads(
        personal_create_schedule.invoke(
            {
                "title": "개인 코칭",
                "date": "2026-05-20",
                "start_time": "11:00",
                "end_time": "12:00",
                "attendees": ["나"],
            }
        )
    )

    structured = result["structured_request"]
    assert structured["kind"] == "personal_schedule"
    assert structured["title"] == "개인 코칭"
    assert structured["source_schedule_id"] == result["created_schedule"]["id"]

    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    saved = store.save_structured_request(structured)
    schedules = store.list_schedules()

    assert saved["kind"] == "personal_schedule"
    assert schedules[0]["title"] == "개인 코칭"
    assert schedules[0]["attendees"] == ["나"]


def test_delete_saved_schedules_requires_filter_unless_delete_all(tmp_path) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    store.save_structured_request(
        {
            "kind": "personal_schedule",
            "title": "개인 코칭",
            "date": "2026-05-20",
            "start_time": "11:00",
            "end_time": "12:00",
            "members": ["나"],
            "reason": "테스트 일정",
            "original_text": "2026-05-20 오전 11시에 개인 코칭 일정 잡아줘",
        }
    )

    result = delete_saved_schedules_dict(app_store=store)

    assert result["ok"] is False
    assert result["deleted_count"] == 0
    assert len(store.list_schedules()) == 1


def test_delete_saved_schedules_by_filter_removes_matching_rows(tmp_path) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    store.save_structured_request(
        {
            "kind": "group_schedule",
            "title": "팀 회의",
            "date": "2026-05-15",
            "start_time": "15:00",
            "end_time": "16:00",
            "members": ["민준", "서연"],
            "reason": "테스트 일정",
            "original_text": "5월 15일 팀 회의 잡아줘",
        }
    )
    store.save_structured_request(
        {
            "kind": "personal_schedule",
            "title": "개인 코칭",
            "date": "2026-05-15",
            "start_time": "11:00",
            "end_time": "12:00",
            "members": ["나"],
            "reason": "남아야 하는 일정",
            "original_text": "5월 15일 오전 11시에 개인 코칭 일정 잡아줘",
        }
    )

    result = delete_saved_schedules_dict(date="2026-05-15", title="팀 회의", app_store=store)
    remaining = store.list_schedules(limit=20)

    assert result["ok"] is True
    assert result["deleted_count"] == 1
    assert len(remaining) == 1
    assert remaining[0]["title"] == "개인 코칭"


def test_personal_delete_saved_schedules_tool_deletes_by_schedule_id(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(week03_module, "CONFIG", replace(week03_module.CONFIG, app_db_path=db_path))
    store = AppSQLiteStore(db_path)
    saved = store.save_structured_request(
        {
            "kind": "group_schedule",
            "title": "도입 회의",
            "date": "2026-05-16",
            "start_time": "10:00",
            "end_time": "11:00",
            "members": ["민준", "서연"],
            "reason": "삭제 tool 테스트",
            "original_text": "5월 16일 도입 회의 잡아줘",
        }
    )
    schedule_id = next(row["id"] for row in saved["saved_rows"] if row["table"] == "schedules")

    result = json.loads(week03_module.personal_delete_saved_schedules.invoke({"schedule_ids": [schedule_id]}))

    assert result["ok"] is True
    assert result["deleted_count"] == 1
    assert result["filters"]["schedule_ids"] == [schedule_id]
    assert result["deleted"][0]["source"] == "app_db"
    assert store.list_schedules(limit=20) == []


def test_delete_saved_schedules_delete_all_removes_rows(tmp_path) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    for title in ["팀 회의", "제품 리뷰"]:
        store.save_structured_request(
            {
                "kind": "group_schedule",
                "title": title,
                "date": "2026-05-17",
                "start_time": "15:00",
                "end_time": "16:00",
                "members": ["민준", "서연"],
                "reason": "전체 삭제 테스트",
                "original_text": title,
            }
        )

    result = delete_saved_schedules_dict(delete_all=True, app_store=store)

    assert result["ok"] is True
    assert result["delete_all"] is True
    assert result["deleted_count"] == 2
    assert store.list_schedules(limit=20) == []


def test_delete_schedule_by_query_uses_structured_fields_without_regex(tmp_path, monkeypatch) -> None:
    class FakeStructuredRequest:
        def model_dump(self) -> dict[str, object]:
            return {
                "kind": "group_schedule",
                "title": "팀 회의",
                "date": "2026-05-18",
                "start_time": "15:00",
                "end_time": "16:00",
                "members": ["민준", "서연"],
                "priority": None,
                "reason": "테스트 구조화 결과",
                "original_text": "팀 회의 삭제해줘",
            }

    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    store.save_structured_request(
        {
            "kind": "group_schedule",
            "title": "팀 회의",
            "date": "2026-05-18",
            "start_time": "15:00",
            "end_time": "16:00",
            "members": ["민준", "서연"],
            "reason": "삭제 대상",
            "original_text": "5월 18일 팀 회의 잡아줘",
        }
    )
    store.save_structured_request(
        {
            "kind": "group_schedule",
            "title": "팀 회의",
            "date": "2026-05-19",
            "start_time": "15:00",
            "end_time": "16:00",
            "members": ["민준", "서연"],
            "reason": "남아야 하는 일정",
            "original_text": "5월 19일 팀 회의 잡아줘",
        }
    )
    monkeypatch.setattr(week03_module, "extract_structured_request", lambda query: FakeStructuredRequest())

    result = week03_module.delete_schedule_by_query_dict("팀 회의 삭제해줘", app_store=store)
    remaining = store.list_schedules(limit=20)

    assert result["tool_name"] == "personal_delete_schedule_by_query"
    assert result["structured_request"]["title"] == "팀 회의"
    assert result["deleted_count"] == 1
    assert result["filters"] == {
        "schedule_ids": None,
        "date": "2026-05-18",
        "title": "팀 회의",
        "start_time": "15:00",
        "time_unspecified": False,
    }
    assert len(remaining) == 1
    assert remaining[0]["date"] == "2026-05-19"


def test_week6_common_slot_calculation_uses_busy_rows() -> None:
    external_rows = extract_schedules_from_history_dict(["철수", "영희"], "2000-01-01", "2999-12-31")
    target_day = external_rows[0]["date"]

    result = find_common_available_slots_dict(
        member_names=["철수", "영희"],
        date_from=target_day,
        date_to=target_day,
        duration_minutes=60,
        limit=3,
    )

    assert result["tool_name"] == "find_common_available_slots"
    assert result["members"] == ["나", "철수", "영희"]
    assert result["candidate_slots"][0] == {
        "date": target_day,
        "start_time": "09:00",
        "end_time": "10:00",
        "duration_minutes": 60,
        "reason": "수집된 busy-time과 겹치지 않는 공통 가능 시간입니다.",
    }
    assert all(slot["start_time"] != "11:00" for slot in result["candidate_slots"])


def test_runtime_clock_uses_os_start_date() -> None:
    assert runtime_clock.current_app_date_iso() == runtime_clock.current_app_date().isoformat()
