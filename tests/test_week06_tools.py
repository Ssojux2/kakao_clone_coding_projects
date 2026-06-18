from __future__ import annotations

import json
from types import SimpleNamespace

import fixed.runtime_clock as runtime_clock
import fixed.agent_runtime as runtime_module
import student_parts.agent_registry as agent_registry
from fixed.agent_runtime import AgentRuntime
from fixed.stores import AppSQLiteStore
from student_parts.agent_registry import ActiveWeekAgentResult
from student_parts.week05_load_kanas_past_conversations import extract_schedules_from_history
from student_parts.week06_kanamate_decides_schedule import (
    agent_tool_names,
    decide_final_slot,
    find_common_available_slots_dict,
)


def test_week06_kana_tools_include_slot_decision_chain() -> None:
    kana_tools = set(agent_tool_names("kana_agent"))

    assert {"search_previous_conversations", "extract_schedules_from_history", "list_shared_schedules", "decide_final_slot"} <= kana_tools


def test_week06_common_slots_feed_final_slot() -> None:
    target_day = runtime_clock.next_weekday_iso(1)
    slots = find_common_available_slots_dict(
        member_names=["철수", "영희"],
        date_from=target_day,
        date_to=target_day,
        duration_minutes=60,
        limit=1,
    )["candidate_slots"]

    result = json.loads(
        decide_final_slot.invoke(
            {
                "candidate_slots": slots,
                "reason": "첫 번째 공통 가능 시간",
            }
        )
    )

    assert result["final_slot"] == f"{slots[0]['date']} {slots[0]['start_time']}-{slots[0]['end_time']}"
    assert result["reason"] == "첫 번째 공통 가능 시간"
    assert result["candidates"][0] == result["final_slot"]


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


def test_runtime_passes_active_week_and_recent_messages(tmp_path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run_active_week_agent(active_week: int, messages: list[dict[str, str]]) -> ActiveWeekAgentResult:
        seen["active_week"] = active_week
        seen["messages"] = messages
        return ActiveWeekAgentResult(answer="mock answer", trace={"events": [{"event": "mock"}]})

    monkeypatch.setattr(runtime_module, "run_active_week_agent", fake_run_active_week_agent)
    runtime = AgentRuntime(active_week=4)
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    conversation_id = runtime.ensure_conversation(None, "첫 메시지")
    for index in range(15):
        runtime.app_store.append_message(conversation_id, "user", f"이전 사용자 {index}")
        runtime.app_store.append_message(conversation_id, "assistant", f"이전 답변 {index}")

    result = runtime.run_agent("새 요청", conversation_id)

    assert seen["active_week"] == 4
    assert result.answer == "mock answer"
    assert result.trace["conversation_id"] == conversation_id
    messages = seen["messages"]
    assert isinstance(messages, list)
    assert len(messages) == 13
    assert messages[-1] == {"role": "user", "content": "새 요청"}
    assert all(message["role"] in {"user", "assistant"} for message in messages)


def test_agent_registry_imports_only_selected_week(monkeypatch) -> None:
    imported_modules: list[str] = []

    class FakeAgent:
        def invoke(self, payload: dict[str, object]) -> dict[str, object]:
            return {"messages": [{"role": "assistant", "content": "week agent ok"}]}

    class FakeModule:
        @staticmethod
        def build_week_agent() -> FakeAgent:
            return FakeAgent()

    def fake_import_module(module_name: str) -> FakeModule:
        imported_modules.append(module_name)
        return FakeModule()

    monkeypatch.setattr(agent_registry, "CONFIG", SimpleNamespace(has_openai_key=True))
    monkeypatch.setattr(agent_registry.importlib, "import_module", fake_import_module)

    result = agent_registry.run_active_week_agent(1, [{"role": "user", "content": "테스트"}])

    assert imported_modules == ["student_parts.week01_wake_up_nana"]
    assert result.answer == "week agent ok"
    assert result.trace["active_week"] == 1


def test_week05_external_schedule_tool_lists_all_times(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KANANA_EXTERNAL_DB_PATH", str(tmp_path / "external.sqlite3"))

    payload = json.loads(
        extract_schedules_from_history.invoke(
            {
                "member_names": ["철수", "영희"],
                "date_from": runtime_clock.next_weekday_iso(1),
                "date_to": runtime_clock.next_weekday_iso(3),
            }
        )
    )
    summary = payload["schedule_summary"]

    assert f"{runtime_clock.next_weekday_iso(1)} 11:00-12:00" in summary
    assert f"{runtime_clock.next_weekday_iso(2)} 13:00-14:00" in summary
    assert f"{runtime_clock.next_weekday_iso(2)} 15:00-16:00" in summary
    assert f"{runtime_clock.next_weekday_iso(3)} 14:00-15:00" in summary
    assert f"{runtime_clock.next_weekday_iso(3)} 16:00-17:00" in summary
