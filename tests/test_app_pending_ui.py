from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import app
import student_parts.agent_registry as agent_registry
from fixed.agent_runtime import RuntimeResult, RuntimeStreamEvent
from langchain_core.messages import AIMessage, ToolMessage


class FakeStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def list_conversations(self) -> list[dict[str, str]]:
        return self.rows


def test_stream_active_week_agent_yields_tool_progress(monkeypatch) -> None:
    class FakeAgent:
        def stream(self, payload: dict[str, object], stream_mode: str) -> list[dict[str, object]]:
            assert stream_mode == "updates"
            return [
                {
                    "model": {
                        "messages": [
                            AIMessage(
                                content="",
                                tool_calls=[{"name": "sample_tool", "args": {"x": 1}, "id": "call_1"}],
                            )
                        ]
                    }
                },
                {
                    "tools": {
                        "messages": [
                            ToolMessage(content='{"ok": true}', name="sample_tool", tool_call_id="call_1")
                        ]
                    }
                },
                {"model": {"messages": [AIMessage(content="완료했습니다.")]}},
            ]

    class FakeModule:
        @staticmethod
        def build_week_agent() -> FakeAgent:
            return FakeAgent()

    monkeypatch.setattr(agent_registry, "CONFIG", SimpleNamespace(has_openai_key=True))
    monkeypatch.setattr(agent_registry.importlib, "import_module", lambda module_name: FakeModule())

    events = list(agent_registry.stream_active_week_agent(1, [{"role": "user", "content": "테스트"}]))

    assert [event.status_text for event in events if event.status_text] == [
        "답변을 진행중입니다",
        "현재 sample_tool 실행 중",
    ]
    final_result = events[-1].result
    assert final_result is not None
    assert final_result.answer == "완료했습니다."
    assert [event["tool_name"] for event in final_result.trace["events"]] == ["sample_tool", "sample_tool"]


def test_queue_user_message_adds_pending_status(monkeypatch) -> None:
    fake_store = FakeStore()
    fake_store.rows = [{"conversation_id": "c1", "title": "테스트", "last_message": "안녕"}]
    monkeypatch.setattr(app, "runtime", SimpleNamespace(app_store=fake_store, ensure_conversation=lambda *_: "c1"))

    result = app.queue_user_message("안녕", [], "")

    history = result[0]
    assert history == [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "...\n\n<small>답변을 진행중입니다</small>"},
    ]


def test_finish_agent_response_updates_pending_message(monkeypatch) -> None:
    fake_store = FakeStore()

    class FakeRuntime:
        app_store = fake_store

        @staticmethod
        def stream_agent(user_message: str, conversation_id: str | None) -> list[RuntimeStreamEvent]:
            return [
                RuntimeStreamEvent(status_text="답변을 진행중입니다"),
                RuntimeStreamEvent(status_text="현재 sample_tool 실행 중"),
                RuntimeStreamEvent(
                    result=RuntimeResult(
                        answer="최종 답변",
                        trace={"events": [{"event": "tool_call", "tool_name": "sample_tool"}]},
                        conversation_id=conversation_id or "c1",
                    )
                ),
            ]

    monkeypatch.setattr(app, "runtime", FakeRuntime())
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "...\n\n<small>답변을 진행중입니다</small>"},
    ]

    updates = list(app.finish_agent_response("안녕", history, "c1"))

    tool_update_history = updates[1][0]
    assert tool_update_history[-1] == {
        "role": "assistant",
        "content": "...\n\n<small>현재 sample_tool 실행 중</small>",
    }
    final_history = updates[-1][0]
    assert final_history == [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "최종 답변"},
    ]


def test_pending_message_detection_allows_gradio_roundtrip_whitespace() -> None:
    message = {"role": "assistant", "content": "...\n\n&lt;small&gt;현재 sample_tool 실행 중&lt;/small&gt;\n"}

    assert app._is_pending_assistant_message(message)


def test_finish_agent_response_appends_answer_without_pending_placeholder(monkeypatch) -> None:
    fake_store = FakeStore()

    class FakeRuntime:
        app_store = fake_store

        @staticmethod
        def stream_agent(user_message: str, conversation_id: str | None) -> list[RuntimeStreamEvent]:
            return [
                RuntimeStreamEvent(
                    result=RuntimeResult(
                        answer="최종 답변",
                        trace={"events": []},
                        conversation_id=conversation_id or "c1",
                    )
                )
            ]

    monkeypatch.setattr(app, "runtime", FakeRuntime())
    history = [{"role": "user", "content": "안녕"}]

    updates = list(app.finish_agent_response("안녕", history, "c1"))

    assert updates[-1][0] == [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "최종 답변"},
    ]
