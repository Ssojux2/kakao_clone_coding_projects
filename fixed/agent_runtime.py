from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fixed.config import CONFIG
from fixed.stores import AppSQLiteStore


@dataclass
class RuntimeResult:
    answer: str
    trace: dict[str, Any]
    conversation_id: str


class AgentRuntime:
    """프롬프트 기반 supervisor 에이전트를 실행하는 얇은 런타임 어댑터입니다.

    이 클래스는 의도적으로 주차, 에이전트, 도구를 고르지 않습니다.
    채팅 메시지를 저장하고, LangChain supervisor를 호출한 뒤,
    반환된 메시지를 UI가 표시할 trace 페이로드로 변환하는 역할만 합니다.
    """

    def __init__(self) -> None:
        self.app_store = AppSQLiteStore(CONFIG.app_db_path)
        self._supervisor_agent: Any | None = None

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
        is_new_conversation = not previous_messages
        self.app_store.append_message(conversation_id, "user", user_message)

        if not CONFIG.has_openai_key:
            answer = (
                "프롬프트 기반 에이전트 실행에는 .env의 OPENAI_API_KEY가 필요합니다. "
                "키를 추가하면 supervisor 에이전트가 nana_agent/kana_agent 도구를 직접 선택해 실행합니다."
            )
            trace = {
                "mode": "prompt_agent",
                "error": "missing_openai_api_key",
                "conversation_id": conversation_id,
            }
            self.app_store.append_message(conversation_id, "assistant", answer)
            return RuntimeResult(answer=answer, trace=trace, conversation_id=conversation_id)

        messages = [
            {"role": row["role"], "content": row["content"]}
            for row in previous_messages
            if row["role"] in {"user", "assistant"}
        ]
        if is_new_conversation:
            schedule_context = self._saved_schedule_context()
            if schedule_context:
                messages.insert(0, {"role": "system", "content": schedule_context})
        messages.append({"role": "user", "content": user_message})

        try:
            result = self._get_supervisor_agent().invoke({"messages": messages})
            answer = self._extract_final_text(result)
            trace = self._extract_langchain_trace(result)
        except Exception as exc:
            answer = f"OpenAI agent 실행 중 오류가 발생했습니다: {type(exc).__name__}: {exc}"
            trace = {"events": [], "error": str(exc), "error_type": type(exc).__name__}

        trace["mode"] = "prompt_agent"
        trace["conversation_id"] = conversation_id
        self.app_store.append_message(conversation_id, "assistant", answer)
        return RuntimeResult(answer=answer, trace=trace, conversation_id=conversation_id)

    def _saved_schedule_context(self, limit: int = 12) -> str:
        rows = self.app_store.list_schedules(limit=limit)
        if not rows:
            return ""
        lines = [
            "새 대화를 시작할 때 참고해야 할 앱 DB 저장 일정이다. "
            "사용자가 기존 일정, 중복 여부, 가능한 시간, '그 일정'을 언급하면 아래 내용을 근거로 삼아라."
        ]
        for row in rows:
            date = row.get("date") or "날짜 미정"
            start_time = row.get("start_time") or "시간 미정"
            end_time = row.get("end_time") or ""
            time_range = f"{start_time}-{end_time}" if end_time else start_time
            attendees = row.get("attendees") or []
            attendee_text = f" / 참석자: {', '.join(attendees)}" if attendees else ""
            lines.append(f"- {date} {time_range} | {row.get('title') or '제목 없음'}{attendee_text}")
        return "\n".join(lines)

    def _get_supervisor_agent(self) -> Any:
        if self._supervisor_agent is None:
            from student_parts.week06_kanamate_decides_schedule import build_langchain_supervisor_agent

            self._supervisor_agent = build_langchain_supervisor_agent()
        return self._supervisor_agent

    def _extract_final_text(self, result: dict[str, Any]) -> str:
        messages = result.get("messages", []) if isinstance(result, dict) else []
        for message in reversed(messages):
            content = getattr(message, "content", None)
            if not content and isinstance(message, dict):
                content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
                ]
                if any(text_parts):
                    return "\n".join(part for part in text_parts if part).strip()
        return "응답을 생성하지 못했습니다."

    def _extract_langchain_trace(self, result: dict[str, Any]) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        messages = result.get("messages", []) if isinstance(result, dict) else []
        for message in messages:
            tool_calls = getattr(message, "tool_calls", None) or []
            for call in tool_calls:
                events.append(
                    {
                        "event": "tool_call",
                        "tool_name": call.get("name"),
                        "arguments": call.get("args"),
                        "id": call.get("id"),
                    }
                )
            if getattr(message, "type", "") == "tool":
                content = getattr(message, "content", "")
                parsed_content: Any = content
                try:
                    parsed_content = json.loads(content)
                except Exception:
                    pass
                events.append(
                    {
                        "event": "tool_result",
                        "tool_name": getattr(message, "name", None),
                        "content": parsed_content,
                        "id": getattr(message, "tool_call_id", None),
                    }
                )

        inner_tool_names: list[str] = []
        final_decision_payload: dict[str, Any] | None = None
        selected_agent: str | None = None
        for event in events:
            if event.get("event") == "tool_call" and event.get("tool_name") in {"nana_agent", "kana_agent"}:
                selected_agent = event["tool_name"]
            content = event.get("content")
            if isinstance(content, dict):
                inner_tool_names.extend(content.get("inner_tool_names") or [])
                if content.get("final_decision_payload"):
                    final_decision_payload = content["final_decision_payload"]

        return {
            "events": events,
            "supervisor_selected_agent": selected_agent,
            "inner_tool_names": inner_tool_names,
            "final_decision_payload": final_decision_payload,
        }
