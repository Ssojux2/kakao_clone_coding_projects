from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fixed.config import CONFIG
from fixed.stores import AppSQLiteStore
from student_parts.agent_registry import run_active_week_agent, stream_active_week_agent


RECENT_HISTORY_LIMIT = 12


@dataclass
class RuntimeResult:
    answer: str
    trace: dict[str, Any]
    conversation_id: str


@dataclass
class RuntimeStreamEvent:
    status_text: str | None = None
    result: RuntimeResult | None = None


class AgentRuntime:
    """UI와 student_parts agent 사이를 잇는 얇은 런타임 어댑터입니다.

    이 클래스는 채팅 메시지를 저장하고, 선택된 주차의 student agent에
    최근 대화 메시지를 전달한 뒤, 반환된 답변과 trace를 다시 저장합니다.
    주차별 prompt, tool 목록, agent 선택, trace 해석은 student_parts가 맡습니다.
    """

    def __init__(self, active_week: int | None = None) -> None:
        self.app_store = AppSQLiteStore(CONFIG.app_db_path)
        self.active_week = active_week if active_week is not None else CONFIG.active_week

    def ensure_conversation(self, conversation_id: str | None, first_message: str) -> str:
        if conversation_id:
            return conversation_id
        created = self.app_store.create_conversation(first_message[:40] or "새 대화")
        return created["conversation_id"]

    def load_messages_for_chatbot(self, conversation_id: str) -> list[dict[str, str]]:
        rows = self.app_store.load_conversation(conversation_id)
        return [{"role": row["role"], "content": row["content"]} for row in rows if row["role"] in {"user", "assistant"}]

    def archive_conversation(self, conversation_id: str | None) -> None:
        if conversation_id:
            self.app_store.archive_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str | None) -> None:
        self.app_store.delete_conversation(conversation_id)

    def run_agent(self, user_message: str, conversation_id: str | None) -> RuntimeResult:
        conversation_id = self.ensure_conversation(conversation_id, user_message)
        previous_messages = self.app_store.load_conversation(conversation_id)
        self.app_store.append_message(conversation_id, "user", user_message)

        messages = self._agent_messages(previous_messages, user_message)
        result = run_active_week_agent(self.active_week, messages)
        trace = dict(result.trace)
        trace["conversation_id"] = conversation_id

        self.app_store.append_message(conversation_id, "assistant", result.answer)
        return RuntimeResult(answer=result.answer, trace=trace, conversation_id=conversation_id)

    def stream_agent(self, user_message: str, conversation_id: str | None) -> Iterator[RuntimeStreamEvent]:
        conversation_id = self.ensure_conversation(conversation_id, user_message)
        previous_messages = self.app_store.load_conversation(conversation_id)
        self.app_store.append_message(conversation_id, "user", user_message)

        messages = self._agent_messages(previous_messages, user_message)
        for event in stream_active_week_agent(self.active_week, messages):
            if event.status_text:
                yield RuntimeStreamEvent(status_text=event.status_text)
            if event.result:
                trace = dict(event.result.trace)
                trace["conversation_id"] = conversation_id
                result = RuntimeResult(answer=event.result.answer, trace=trace, conversation_id=conversation_id)
                self.app_store.append_message(conversation_id, "assistant", result.answer)
                yield RuntimeStreamEvent(result=result)
                return

        trace = {
            "mode": "active_week_agent",
            "active_week": self.active_week,
            "conversation_id": conversation_id,
            "events": [],
            "error": "stream_completed_without_result",
        }
        result = RuntimeResult(answer="응답을 생성하지 못했습니다.", trace=trace, conversation_id=conversation_id)
        self.app_store.append_message(conversation_id, "assistant", result.answer)
        yield RuntimeStreamEvent(result=result)

    def _agent_messages(self, previous_messages: list[dict[str, Any]], user_message: str) -> list[dict[str, str]]:
        messages = [
            {"role": row["role"], "content": row["content"]}
            for row in previous_messages
            if row["role"] in {"user", "assistant"}
        ]
        messages = messages[-RECENT_HISTORY_LIMIT:]
        messages.append({"role": "user", "content": user_message})
        return messages
