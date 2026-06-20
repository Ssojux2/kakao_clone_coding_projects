from __future__ import annotations

import json
from contextvars import Context
from types import SimpleNamespace

import fixed.runtime_clock as runtime_clock
import fixed.agent_runtime as runtime_module
import fixed.week_agent_registry as agent_registry
from fixed.agent_runtime import AgentRuntime
from fixed.app_store import AppSQLiteStore
from fixed.session_scope import current_session_scope
from fixed.week_agent_registry import ActiveWeekAgentResult, ActiveWeekAgentStreamEvent
from student_parts.week05_load_kanas_past_conversations import extract_schedules_from_history
from student_parts.week06_kanamate_decides_schedule import (
    agent_tool_names,
    decide_final_slot,
    find_common_available_slots_dict,
)


def test_week06_kana_tools_include_slot_decision_chain() -> None:
    kana_tools = set(agent_tool_names("kana_agent"))

    assert {
        "search_previous_conversations",
        "extract_schedules_from_history",
        "list_shared_schedules",
        "find_common_available_slots",
        "decide_final_slot",
    } <= kana_tools


def test_week06_final_slot_requires_explicit_agent_selection() -> None:
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
            }
        )
    )

    assert result["final_slot"] is None
    assert result["needs_agent_selection"] is True
    assert result["candidates"][0] == f"{slots[0]['date']} {slots[0]['start_time']}-{slots[0]['end_time']}"


def test_week06_selected_index_confirms_final_slot() -> None:
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
                "selected_index": 0,
                "reason": "LLM이 첫 번째 후보를 선택함",
            }
        )
    )

    assert result["final_slot"] == f"{slots[0]['date']} {slots[0]['start_time']}-{slots[0]['end_time']}"
    assert result["needs_agent_selection"] is False
    assert result["reason"] == "LLM이 첫 번째 후보를 선택함"


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


def test_week06_common_slots_keep_empty_external_members() -> None:
    target_day = runtime_clock.next_weekday_iso(1)

    result = find_common_available_slots_dict(
        member_names=[],
        date_from=target_day,
        date_to=target_day,
        duration_minutes=60,
        limit=1,
    )

    assert result["members"] == ["나"]
    assert all(row["member_name"] == "나" for row in result["busy_rows"])


def test_runtime_passes_active_week_and_full_current_conversation(tmp_path, monkeypatch) -> None:
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
    assert len(messages) == 31
    assert messages[0] == {"role": "user", "content": "이전 사용자 0"}
    assert messages[1] == {"role": "assistant", "content": "이전 답변 0"}
    assert messages[-1] == {"role": "user", "content": "새 요청"}
    assert all(message["role"] in {"user", "assistant"} for message in messages)


def test_runtime_new_chat_does_not_pass_previous_conversation(tmp_path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run_active_week_agent(active_week: int, messages: list[dict[str, str]]) -> ActiveWeekAgentResult:
        seen["messages"] = messages
        seen["session_scope"] = current_session_scope()
        return ActiveWeekAgentResult(answer="new chat answer", trace={"events": []})

    monkeypatch.setattr(runtime_module, "run_active_week_agent", fake_run_active_week_agent)
    runtime = AgentRuntime(active_week=2)
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    old_conversation_id = runtime.ensure_conversation(None, "이전 대화")
    runtime.app_store.append_message(old_conversation_id, "user", "이전 사용자")
    runtime.app_store.append_message(old_conversation_id, "assistant", "이전 답변")

    result = runtime.run_agent("새 대화 첫 요청", None)

    assert result.conversation_id != old_conversation_id
    assert seen["session_scope"] == result.conversation_id
    assert seen["messages"] == [{"role": "user", "content": "새 대화 첫 요청"}]


def test_week3_new_chat_passes_only_ui_message_without_runtime_system_prompt(tmp_path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run_active_week_agent(active_week: int, messages: list[dict[str, str]]) -> ActiveWeekAgentResult:
        seen["active_week"] = active_week
        seen["messages"] = messages
        return ActiveWeekAgentResult(answer="week3 answer", trace={"events": []})

    monkeypatch.setattr(runtime_module, "run_active_week_agent", fake_run_active_week_agent)
    runtime = AgentRuntime(active_week=3)
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    old_conversation_id = runtime.ensure_conversation(None, "이전 대화")
    runtime.app_store.append_message(old_conversation_id, "user", "이전 사용자")
    runtime.app_store.append_message(old_conversation_id, "assistant", "이전 답변")

    runtime.run_agent("저장된 일정 보여줘", None)

    assert seen["active_week"] == 3
    assert seen["messages"] == [{"role": "user", "content": "저장된 일정 보여줘"}]


def test_runtime_stream_scope_does_not_cross_generator_yield_context(tmp_path, monkeypatch) -> None:
    seen_scopes: list[str] = []

    def fake_stream_active_week_agent(active_week: int, messages: list[dict[str, str]]) -> object:
        seen_scopes.append(current_session_scope())
        yield ActiveWeekAgentStreamEvent(status_text="답변을 진행중입니다")
        seen_scopes.append(current_session_scope())
        yield ActiveWeekAgentStreamEvent(result=ActiveWeekAgentResult(answer="stream answer", trace={"events": []}))

    monkeypatch.setattr(runtime_module, "stream_active_week_agent", fake_stream_active_week_agent)
    runtime = AgentRuntime(active_week=2)
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    stream = runtime.stream_agent("스트림 테스트", None)

    first_event = Context().run(lambda: next(stream))
    Context().run(stream.close)

    assert first_event.status_text == "답변을 진행중입니다"
    assert len(seen_scopes) == 1
    assert seen_scopes[0].startswith("conv_")


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
