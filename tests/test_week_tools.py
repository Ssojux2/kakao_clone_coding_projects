from __future__ import annotations

import json
from dataclasses import replace

import fixed.runtime_clock as runtime_clock
import student_parts.week03_build_nanas_logbook as week03_module
from fixed.app_store import AppSQLiteStore
from fixed.schedule_decision import busy_rows_overlap, parse_time_minutes
from golden_cases import GOLDEN_CASES, find_case_by_input, harness_prompt_examples, sample_prompts
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES, personal_create_schedule, week01_system_prompt, week01_tools
from student_parts.week02_structure_natural_language_requests import week02_system_prompt, week02_tools
from student_parts.week03_build_nanas_logbook import delete_saved_schedules_dict, week03_system_prompt, week03_tools
from student_parts.week04_retrieve_nanas_memory import week04_system_prompt, week04_tools
from student_parts.week05_load_kanas_past_conversations import (
    extract_schedules_from_history,
    week05_system_prompt,
    week05_tools,
)
from student_parts.week06_kanamate_decides_schedule import (
    agent_tool_names,
    find_common_available_slots_dict,
    kana_system_prompt,
    nana_system_prompt,
    supervisor_system_prompt,
    week06_system_prompt,
)


def _tool_names(tools: list[object]) -> set[str]:
    return {getattr(item, "name", getattr(item, "__name__", str(item))) for item in tools}


def test_prompt_harness_is_the_shared_reference() -> None:
    examples = harness_prompt_examples()

    assert [case["input"] for case in GOLDEN_CASES] == sample_prompts()
    assert [case["id"] for case in GOLDEN_CASES] == [example["id"] for example in examples]
    assert find_case_by_input(GOLDEN_CASES[0]["input"]) == GOLDEN_CASES[0]


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
    assert "search_conversation_messages" in nana_tools
    assert "extract_schedule_request" in kana_tools
    assert "collect_member_schedules" in kana_tools
    assert "find_common_available_slots" in kana_tools
    assert "decide_final_slot" in kana_tools
    assert "personal_delete_schedule_by_query" not in nana_tools

    for case in GOLDEN_CASES:
        expected_tools = case.get("expected_tools") or [case["expected_tool"]]
        target_tools = nana_tools if case["expected_agent"] == "nana_agent" else kana_tools
        assert set(expected_tools) <= target_tools


def test_concrete_group_meeting_registration_routes_to_nana_storage() -> None:
    week05_prompt = week05_system_prompt()
    supervisor_prompt = supervisor_system_prompt()
    nana_prompt = nana_system_prompt()
    kana_prompt = kana_system_prompt()

    assert "참석자가 있어도 외부 일정 조율이 아니라 앱 DB 일정 저장 요청" in week05_prompt
    assert "structured_request를 save_structured_request에 전달해 저장" in week05_prompt
    assert "참석자가 있어도 일정 저장 요청이므로 nana_agent" in supervisor_prompt
    assert "kind가 personal_schedule이든 group_schedule이든" in nana_prompt
    assert "Nana 저장 담당" in kana_prompt


def test_week3_plus_prompts_use_sqlite_directly_for_create_and_lookup() -> None:
    prompts = [
        week03_system_prompt(),
        week04_system_prompt(),
        week05_system_prompt(),
        nana_system_prompt(),
        supervisor_system_prompt(),
    ]

    for prompt in prompts:
        assert "SQLite" in prompt
        assert "personal_list_schedules" in prompt

    assert "personal_create_schedule을 거치지 않고" in prompts[0]
    assert "personal_create_schedule을 새 일정 저장용으로 사용하지 않는다" in prompts[1]
    assert "personal_create_schedule은 Week 1-2 임시 메모리용" in prompts[2]
    assert "personal_create_schedule을 거쳐 저장하지 않는다" in prompts[3]
    assert "단순 일정 조회에 personal_list_schedules 같은 Week 1-2 인메모리 조회를 사용하지 않는다" in prompts[4]
    assert "Week 1-2 단순 조회 전용" in prompts[0]


def test_week_system_prompts_accumulate_previous_weeks() -> None:
    assert "현재 채팅 기억" in week01_system_prompt()
    assert "Week 1 Nana 일정 agent" in week02_system_prompt()
    assert "Week 2 요청 구조화 agent" in week02_system_prompt()
    assert "StructuredRequest" in week02_system_prompt()
    assert "Week 1 Nana 일정 agent" in week03_system_prompt()
    assert "Week 2 요청 구조화 agent" in week03_system_prompt()
    assert "최종 답변은 자연어" in week03_system_prompt()
    assert "앱 SQLite DB에 저장된 일정" in week03_system_prompt()
    assert "Week 3 Nana logbook agent" in week04_system_prompt()
    assert "Week 4 Nana memory agent" in week05_system_prompt()
    assert "Week 5 Kana history agent" in supervisor_system_prompt()


def test_week6_system_prompt_is_supervisor_prompt_and_subagents_are_separate() -> None:
    supervisor_prompt = supervisor_system_prompt()
    nana_prompt = nana_system_prompt()
    kana_prompt = kana_system_prompt()

    assert week06_system_prompt() == supervisor_prompt
    assert "Week 1 Nana 일정 agent" in supervisor_prompt
    assert "Week 5 Kana history agent" in supervisor_prompt
    assert "Week 6 supervisor agent" in supervisor_prompt
    assert "Nana/Kana 하위 에이전트는 각자 별도 system prompt를 사용한다" in supervisor_prompt

    assert "supervisor는 nana_agent와 kana_agent 위임 도구만 볼 수 있다" not in nana_prompt
    assert "supervisor는 nana_agent와 kana_agent 위임 도구만 볼 수 있다" not in kana_prompt
    assert "supervisor prompt를 공유하지 않는 Nana 전용 system prompt" in nana_prompt
    assert "supervisor prompt를 공유하지 않는 Kana 전용 system prompt" in kana_prompt


def test_week_tool_lists_accumulate_previous_weeks() -> None:
    week1 = _tool_names(week01_tools())
    week2 = _tool_names(week02_tools())
    week3 = _tool_names(week03_tools())
    week4 = _tool_names(week04_tools())
    week5 = _tool_names(week05_tools())

    assert week1 == {"personal_create_schedule", "personal_list_schedules", "personal_delete_schedule"}
    assert week2 == week1
    assert week1 <= week3
    assert "extract_schedule_request" in week3
    assert {"save_structured_request", "list_saved_requests", "get_saved_request", "personal_update_saved_schedule"} <= week3
    assert "personal_delete_schedule_by_query" not in week3
    assert week3 <= week4
    assert {"add_personal_reference", "search_personal_references", "search_saved_requests", "search_conversation_messages"} <= week4
    assert week4 <= week5
    assert {
        "search_previous_conversations",
        "extract_schedules_from_history",
        "list_shared_schedules",
        "collect_member_schedules",
    } <= week5


def test_week1_create_schedule_returns_memory_only_payload() -> None:
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

    schedule = result["created_schedule"]
    assert result["tool_name"] == "personal_create_schedule"
    assert "structured_request" not in result
    assert schedule["title"] == "개인 코칭"
    assert schedule["attendees"] == ["나"]
    assert schedule["id"].startswith("personal_")


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


def test_delete_by_natural_language_compatibility_tool_is_not_public() -> None:
    assert "personal_delete_schedule_by_query" not in _tool_names(week03_tools())


def test_week6_common_slot_calculation_uses_busy_rows() -> None:
    external_rows = json.loads(
        extract_schedules_from_history.invoke(
            {"member_names": ["철수", "영희"], "date_from": "2000-01-01", "date_to": "2999-12-31"}
        )
    )["rows"]
    target_day = external_rows[0]["date"]

    result = find_common_available_slots_dict(
        member_names=["철수", "영희"],
        date_from=target_day,
        date_to=target_day,
        duration_minutes=60,
        limit=3,
        busy_rows=external_rows,
        candidate_slots=[
            {
                "date": target_day,
                "start_time": "09:00",
                "end_time": "10:00",
                "duration_minutes": 60,
                "reason": "테스트 LLM payload 후보",
            }
        ],
        llm_reason="테스트 후보",
    )

    assert result["tool_name"] == "find_common_available_slots"
    assert result["members"] == ["나", "철수", "영희"]
    assert result["slot_source"] == "llm"
    assert result["candidate_slots"]
    for slot in result["candidate_slots"]:
        start_minutes = parse_time_minutes(slot["start_time"], -1)
        end_minutes = parse_time_minutes(slot["end_time"], -1)
        assert slot["date"] == target_day
        assert start_minutes >= 9 * 60
        assert end_minutes <= 18 * 60
        assert end_minutes - start_minutes >= 60
        assert not busy_rows_overlap(result["busy_rows"], target_day, start_minutes, end_minutes)


def test_runtime_clock_uses_os_start_date() -> None:
    assert runtime_clock.current_app_date_iso() == runtime_clock.current_app_date().isoformat()
