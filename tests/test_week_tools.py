from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import fixed.agent_runtime as agent_runtime_module
import fixed.runtime_clock as runtime_clock
import app as app_module
import student_parts.week02_structure_natural_language_requests as week02_module
import student_parts.week06_kanamate_decides_schedule as week06_module
from fixed.agent_runtime import AgentRuntime
from fixed.stores import AppSQLiteStore
from golden_cases import GOLDEN_CASES, find_case_by_input, harness_prompt_examples, sample_prompts
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES, personal_create_schedule, week01_tools
from student_parts.week02_structure_natural_language_requests import week02_tools
from student_parts.week03_build_nanas_logbook import week03_tools
from student_parts.week04_retrieve_nanas_memory import week04_tools
from student_parts.week05_load_kanas_past_conversations import week05_tools
from student_parts.week06_kanamate_decides_schedule import (
    agent_tool_names,
    delete_saved_schedules_dict,
    delete_schedule_by_query_dict,
    kana_system_prompt,
    nana_system_prompt,
    supervisor_system_prompt,
)


class FakeStructuredRequest:
    def __init__(
        self,
        kind: str = "unknown",
        title: str | None = None,
        date: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        members: list[str] | None = None,
        priority: str | None = None,
        reason: str = "테스트 structured output",
        original_text: str = "",
    ) -> None:
        self.payload = {
            "kind": kind,
            "title": title,
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "members": members or [],
            "priority": priority,
            "reason": reason,
            "original_text": original_text,
        }

    def model_dump(self) -> dict:
        return self.payload


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


def test_structured_request_uses_llm_structured_output_agent(monkeypatch) -> None:
    monkeypatch.setattr(runtime_clock, "APP_TODAY", date(2026, 5, 20))

    class FakeAgent:
        payload: dict | None = None

        def invoke(self, payload: dict) -> dict:
            self.payload = payload
            return {
                "structured_response": {
                    "kind": "personal_schedule",
                    "title": "개인 집중 작업",
                    "date": "2026-05-21",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "members": [],
                    "priority": None,
                    "reason": "LLM structured output 테스트",
                    "original_text": "내일 오전 10시에 개인 집중 작업 일정 잡아줘",
                }
            }

    fake_agent = FakeAgent()
    monkeypatch.setattr(week02_module, "build_langchain_structured_agent", lambda: fake_agent)

    result = week02_module.extract_structured_request("내일 오전 10시에 개인 집중 작업 일정 잡아줘")

    assert result.date == "2026-05-21"
    assert result.reason == "LLM structured output 테스트"
    assert fake_agent.payload == {
        "messages": [{"role": "user", "content": "내일 오전 10시에 개인 집중 작업 일정 잡아줘"}]
    }


def test_structured_output_prompt_uses_os_current_date(monkeypatch) -> None:
    monkeypatch.setattr(runtime_clock, "APP_TODAY", date(2027, 1, 2))

    assert "2027-01-02" in week02_module.structured_output_system_prompt()


def test_expected_tools_are_exposed_to_prompt_driven_agents() -> None:
    supervisor_tools = set(agent_tool_names("supervisor"))
    nana_tools = set(agent_tool_names("nana_agent"))
    kana_tools = set(agent_tool_names("kana_agent"))

    assert supervisor_tools == {"nana_agent", "kana_agent"}
    assert "personal_list_saved_schedules" in nana_tools
    assert "personal_delete_saved_schedules" in nana_tools
    assert "personal_delete_schedule_by_query" in nana_tools
    assert "list_saved_requests" in nana_tools
    assert "get_saved_request" in nana_tools
    assert "add_personal_reference" in nana_tools
    assert "load_conversation_messages" in kana_tools
    assert "collect_member_schedules" in kana_tools
    assert "find_common_available_slots" not in kana_tools
    for case in GOLDEN_CASES:
        if case["expected_agent"] == "nana_agent":
            assert case["expected_tool"] in nana_tools
        else:
            assert case["expected_tool"] in kana_tools


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
    assert {"save_structured_request", "personal_delete_schedule_by_query"} <= week3
    assert week3 <= week4
    assert {"search_personal_references", "build_rag_context"} <= week4
    assert week4 <= week5
    assert {"extract_schedules_from_history", "collect_member_schedules"} <= week5
    assert week3 <= set(agent_tool_names("nana_agent"))
    assert {"extract_schedule_request", "collect_member_schedules"} <= set(agent_tool_names("kana_agent"))


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
    assert structured == {
        "kind": "personal_schedule",
        "title": "개인 코칭",
        "date": "2026-05-20",
        "start_time": "11:00",
        "end_time": "12:00",
        "members": ["나"],
        "priority": None,
        "reason": "1주차 개인 일정 생성 도구가 DB 저장용 structured output으로 변환했습니다.",
        "original_text": "개인 코칭",
        "source_schedule_id": result["created_schedule"]["id"],
    }

    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    saved = store.save_structured_request(structured)
    schedules = store.list_schedules()

    assert saved["kind"] == "personal_schedule"
    assert schedules[0]["title"] == "개인 코칭"
    assert schedules[0]["attendees"] == ["나"]


def test_extract_schedule_request_prefers_llm_structured_output(monkeypatch) -> None:
    monkeypatch.setattr(
        week06_module,
        "extract_structured_request",
        lambda query: FakeStructuredRequest(
            kind="todo",
            title="LLM이 고른 제목",
            date="2026-05-20",
            priority="high",
            reason="테스트 LLM",
            original_text=query,
        ),
    )

    result = json.loads(week06_module.extract_schedule_request.invoke({"query": "중요한 일 저장해줘"}))

    assert result["structured_request"]["title"] == "LLM이 고른 제목"
    assert result["structured_request"]["reason"] == "테스트 LLM"


def test_main_runtime_invokes_prompt_agent_without_week_orchestration(monkeypatch, tmp_path) -> None:
    class FakeToolCallMessage:
        type = "ai"
        content = ""
        tool_calls = [{"name": "nana_agent", "args": {"query": "개인 일정"}, "id": "call_1"}]

    class FakeToolResultMessage:
        type = "tool"
        name = "nana_agent"
        tool_call_id = "call_1"
        content = json.dumps(
            {
                "answer": "개인 일정을 저장했어요.",
                "inner_tool_names": ["extract_schedule_request", "personal_create_schedule"],
            },
            ensure_ascii=False,
        )

    class FakeFinalMessage:
        type = "ai"
        content = "개인 일정을 저장했어요."
        tool_calls: list[dict] = []

    class FakeAgent:
        def invoke(self, _payload: dict) -> dict:
            return {"messages": [FakeToolCallMessage(), FakeToolResultMessage(), FakeFinalMessage()]}

    runtime = AgentRuntime()
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    monkeypatch.setattr(agent_runtime_module, "CONFIG", SimpleNamespace(has_openai_key=True))
    monkeypatch.setattr(runtime, "_get_supervisor_agent", lambda: FakeAgent())

    result = runtime.run_agent("내일 오전 10시에 개인 집중 작업 일정 잡아줘", None)

    assert result.answer == "개인 일정을 저장했어요."
    assert result.trace["mode"] == "prompt_agent"
    assert "selected_week" not in result.trace
    assert "routing_reason" not in result.trace
    assert result.trace["supervisor_selected_agent"] == "nana_agent"
    assert "personal_create_schedule" in result.trace["inner_tool_names"]


def test_main_runtime_requires_llm_without_falling_back_to_code_router(monkeypatch, tmp_path) -> None:
    runtime = AgentRuntime()
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    monkeypatch.setattr(agent_runtime_module, "CONFIG", SimpleNamespace(has_openai_key=False))

    result = runtime.run_agent("팀원 A/B/C와 다음 주 회의 시간을 잡아줘", None)

    assert result.trace["mode"] == "prompt_agent"
    assert result.trace["error"] == "missing_openai_api_key"
    assert "selected_week" not in result.trace
    assert "routing_reason" not in result.trace


def test_new_conversation_includes_saved_schedule_context(monkeypatch, tmp_path) -> None:
    captured_payload: dict = {}

    class FakeFinalMessage:
        type = "ai"
        content = "기존 일정을 확인했어요."
        tool_calls: list[dict] = []

    class FakeAgent:
        def invoke(self, payload: dict) -> dict:
            captured_payload.update(payload)
            return {"messages": [FakeFinalMessage()]}

    runtime = AgentRuntime()
    runtime.app_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    monkeypatch.setattr(agent_runtime_module, "CONFIG", SimpleNamespace(has_openai_key=True))
    monkeypatch.setattr(runtime, "_get_supervisor_agent", lambda: FakeAgent())
    monkeypatch.setattr(
        runtime.app_store,
        "list_schedules",
        lambda limit=12: [
            {
                "title": "개인 코칭",
                "date": "2026-05-20",
                "start_time": "11:00",
                "end_time": "12:00",
                "attendees": ["나"],
            }
        ],
    )

    runtime.run_agent("새 대화에서 기존 일정 확인해줘", None)

    messages = captured_payload["messages"]
    assert messages[0]["role"] == "system"
    assert "앱 DB 저장 일정" in messages[0]["content"]
    assert "개인 코칭" in messages[0]["content"]


def test_queue_user_message_shows_only_user_text_while_waiting(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_conversation_button_updates", lambda selected_id=None: [])
    monkeypatch.setattr(app_module.runtime, "ensure_conversation", lambda conversation_id, first_message: "conv_active")

    history, trace, conversation_id, _textbox, pending_message, _send_button = app_module.queue_user_message(
        "내일 오전 10시에 개인 집중 작업 일정 잡아줘",
        [],
        "",
    )

    assert conversation_id == "conv_active"
    assert pending_message == "내일 오전 10시에 개인 집중 작업 일정 잡아줘"
    assert trace["mode"] == "pending"
    assert history == [{"role": "user", "content": "내일 오전 10시에 개인 집중 작업 일정 잡아줘"}]


def test_new_chat_notice_hides_saved_database_schedules_from_ui(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.runtime.app_store,
        "list_schedules",
        lambda limit=8: [
            {
                "title": "개인 코칭",
                "date": "2026-05-20",
                "start_time": "11:00",
                "end_time": "12:00",
                "attendees": ["나"],
            }
        ],
    )

    notice = app_module._chat_notice()

    assert notice == []


def test_delete_conversation_removes_messages(tmp_path) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    conversation = store.create_conversation("삭제할 대화")
    conversation_id = conversation["conversation_id"]
    store.append_message(conversation_id, "user", "안녕")
    store.append_message(conversation_id, "assistant", "반가워")

    result = store.delete_conversation(conversation_id)

    assert result == {"conversation_id": conversation_id, "deleted": True}
    assert store.load_conversation(conversation_id) == []
    assert all(row["conversation_id"] != conversation_id for row in store.list_conversations())


def test_delete_chat_clears_selected_conversation(monkeypatch) -> None:
    deleted: list[str | None] = []
    monkeypatch.setattr(app_module.runtime, "delete_conversation", lambda conversation_id: deleted.append(conversation_id))
    monkeypatch.setattr(app_module, "_conversation_button_updates", lambda selected_id=None: ["buttons"])

    history, trace, conversation_id, buttons = app_module.delete_chat("conv_selected")

    assert deleted == ["conv_selected"]
    assert history == []
    assert trace == {}
    assert conversation_id == ""
    assert buttons == "buttons"


def test_delete_schedule_by_query_without_schedule_id(monkeypatch, tmp_path) -> None:
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
    monkeypatch.setattr(
        week06_module,
        "extract_structured_request",
        lambda query: FakeStructuredRequest(
            kind="personal_schedule",
            title="개인 코칭",
            date="2026-05-20",
            start_time="11:00",
            end_time="12:00",
            members=["나"],
            original_text=query,
        ),
    )

    result = delete_schedule_by_query_dict("2026-05-20 오전 11시 개인 코칭 일정 삭제해줘", app_store=store)

    assert result["ok"] is True
    assert result["deleted"][0]["source"] == "app_db"
    assert result["deleted"][0]["schedule"]["title"] == "개인 코칭"
    assert store.list_schedules() == []


def test_delete_all_schedules_by_query(monkeypatch, tmp_path) -> None:
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
    store.save_structured_request(
        {
            "kind": "group_schedule",
            "title": "팀 회의",
            "date": "2026-05-21",
            "start_time": "15:00",
            "end_time": "16:00",
            "members": ["민준", "서연"],
            "reason": "테스트 일정",
            "original_text": "2026-05-21 오후 3시에 팀 회의 잡아줘",
        }
    )
    store.save_structured_request(
        {
            "kind": "todo",
            "title": "보고서 정리",
            "date": "2026-05-22",
            "priority": "high",
            "reason": "테스트 할 일",
            "original_text": "보고서 정리 할 일 추가해줘",
        }
    )
    monkeypatch.setattr(
        week06_module,
        "extract_structured_request",
        lambda query: FakeStructuredRequest(kind="unknown", original_text=query),
    )

    result = delete_schedule_by_query_dict("전체 일정을 삭제해줘", app_store=store)

    assert result["ok"] is True
    assert result["delete_all"] is True
    assert result["deleted_count"] == 2
    assert store.list_schedules() == []
    assert store.list_saved_requests(kind="personal_schedule") == []
    assert store.list_saved_requests(kind="group_schedule") == []
    assert len(store.list_saved_requests(kind="todo")) == 1


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


def test_bulk_delete_matching_schedules_with_natural_count_query(monkeypatch, tmp_path) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    for _ in range(12):
        store.save_structured_request(
            {
                "kind": "group_schedule",
                "title": "팀 회의",
                "date": "2026-05-15",
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
    monkeypatch.setattr(
        week06_module,
        "extract_structured_request",
        lambda query: FakeStructuredRequest(
            kind="group_schedule",
            title="팀 회의",
            date="2026-05-15",
            members=["민준", "서연"],
            original_text=query,
        ),
    )

    result = delete_schedule_by_query_dict("5월 15일 팀회의 12건 모두 삭제해줘.", app_store=store)

    remaining = store.list_schedules(limit=20)
    assert result["ok"] is True
    assert result["bulk_delete"] is True
    assert result["deleted_count"] == 12
    assert len(remaining) == 1
    assert remaining[0]["title"] == "개인 코칭"


def test_bulk_delete_matching_schedules_with_summary_line_query(monkeypatch, tmp_path) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    for _ in range(12):
        store.save_structured_request(
            {
                "kind": "group_schedule",
                "title": "팀 회의",
                "date": "2026-05-15",
                "members": ["민준", "서연"],
                "reason": "테스트 일정",
                "original_text": "5월 15일 팀 회의 잡아줘",
            }
        )
    store.save_structured_request(
        {
            "kind": "group_schedule",
            "title": "팀 회의",
            "date": "2026-05-16",
            "members": ["민준", "서연"],
            "reason": "남아야 하는 일정",
            "original_text": "5월 16일 팀 회의 잡아줘",
        }
    )
    monkeypatch.setattr(
        week06_module,
        "extract_structured_request",
        lambda query: FakeStructuredRequest(
            kind="group_schedule",
            title="팀 회의",
            date="2026-05-15",
            members=["민준", "서연"],
            original_text=query,
        ),
    )

    result = delete_schedule_by_query_dict(
        "2026-05-15 시간 미정 | 팀 회의 (총 12건) 삭제해줘.",
        app_store=store,
    )

    remaining = store.list_schedules(limit=20)
    assert result["ok"] is True
    assert result["bulk_delete"] is True
    assert result["deleted_count"] == 12
    assert len(remaining) == 1
    assert remaining[0]["date"] == "2026-05-16"
