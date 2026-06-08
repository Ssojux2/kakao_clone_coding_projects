from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from fixed.config import CONFIG
from fixed.runtime_clock import current_app_date_iso, next_weekday_iso
from fixed.stores import AppSQLiteStore, DEFAULT_EXTERNAL_MEMBERS, PERSONAL_SHARED_MEMBER_NAME


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

        direct_lookup = self._run_external_schedule_lookup(user_message)
        if direct_lookup is not None:
            self.app_store.append_message(conversation_id, "assistant", direct_lookup.answer)
            direct_lookup.trace["conversation_id"] = conversation_id
            return RuntimeResult(answer=direct_lookup.answer, trace=direct_lookup.trace, conversation_id=conversation_id)

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

    def _run_external_schedule_lookup(self, user_message: str) -> RuntimeResult | None:
        if not self._is_external_schedule_lookup(user_message):
            return None

        from student_parts.week05_load_kanas_past_conversations import extract_schedules_from_history

        members = self._external_lookup_members(user_message)
        date_from, date_to = self._external_lookup_date_bounds(user_message)
        payload_text = extract_schedules_from_history.invoke(
            {"member_names": members, "date_from": date_from, "date_to": date_to}
        )
        payload = json.loads(payload_text)
        answer = self._format_external_schedule_lookup_answer(payload, date_from, date_to)
        return RuntimeResult(
            answer=answer,
            trace={
                "mode": "mcp_direct_external_schedule_lookup",
                "events": [
                    {
                        "event": "tool_call",
                        "tool_name": "extract_schedules_from_history",
                        "arguments": {"member_names": members, "date_from": date_from, "date_to": date_to},
                    },
                    {
                        "event": "tool_result",
                        "tool_name": "extract_schedules_from_history",
                        "content": payload,
                    },
                ],
                "supervisor_selected_agent": "kana_agent",
                "inner_tool_names": ["extract_schedules_from_history"],
                "final_slot_payload": None,
                "final_decision_payload": None,
            },
            conversation_id="",
        )

    def _is_external_schedule_lookup(self, user_message: str) -> bool:
        text = (user_message or "").replace(" ", "")
        shared_schedule_terms = ["공유", "다른사람", "사람들", "팀원", "동료", "멤버"]
        mentions_external_people = (
            "외부" in text
            or any(term in text for term in shared_schedule_terms)
            or any(member in text for member in DEFAULT_EXTERNAL_MEMBERS)
        )
        asks_schedule = "일정" in text
        asks_lookup = any(token in text for token in ["조회", "확인", "알려", "보여", "정리", "어떻게"])
        asks_coordination = any(token in text for token in ["잡아", "예약", "추가", "등록", "가능", "후보", "비어"])
        return mentions_external_people and asks_schedule and asks_lookup and not asks_coordination

    def _external_lookup_members(self, user_message: str) -> list[str]:
        selected = [member for member in DEFAULT_EXTERNAL_MEMBERS if member in user_message]
        compact_text = user_message.replace(" ", "")
        if PERSONAL_SHARED_MEMBER_NAME in user_message or "내" in compact_text:
            selected.insert(0, PERSONAL_SHARED_MEMBER_NAME)
        if selected:
            return selected
        if "공유" in compact_text:
            return [PERSONAL_SHARED_MEMBER_NAME, *DEFAULT_EXTERNAL_MEMBERS]
        return []

    def _external_lookup_date_bounds(self, user_message: str) -> tuple[str, str]:
        explicit_dates = re.findall(r"\d{4}-\d{2}-\d{2}", user_message)
        if len(explicit_dates) >= 2:
            return explicit_dates[0], explicit_dates[1]
        if len(explicit_dates) == 1:
            return explicit_dates[0], explicit_dates[0]

        weekday_dates = []
        for label, weekday in [("화요일", 1), ("수요일", 2), ("목요일", 3)]:
            if label in user_message:
                weekday_dates.append(next_weekday_iso(weekday))
        if weekday_dates:
            return min(weekday_dates), max(weekday_dates)
        if "다음주" in user_message.replace(" ", ""):
            return next_weekday_iso(1), next_weekday_iso(3)
        if "공유" in user_message:
            return current_app_date_iso(), next_weekday_iso(3)
        return next_weekday_iso(1), next_weekday_iso(3)

    def _format_external_schedule_lookup_answer(
        self,
        payload: dict[str, Any],
        date_from: str,
        date_to: str,
    ) -> str:
        rows = payload.get("rows") or []
        if not rows:
            return f"현재 공유 일정 저장소에서 {date_from}~{date_to} 범위에 조회된 일정이 없습니다."

        summary = payload.get("schedule_summary") or ""
        if not summary:
            summary = "\n".join(
                "- {member_name} | {title} | {date} {start_time}-{end_time} | {notes}".format(
                    member_name=row.get("member_name") or "이름 미정",
                    title=row.get("title") or "제목 없음",
                    date=row.get("date") or "날짜 미정",
                    start_time=row.get("start_time") or "시간 미정",
                    end_time=row.get("end_time") or "시간 미정",
                    notes=row.get("notes") or "비고 없음",
                )
                for row in rows
            )
        return f"현재 공유 일정 저장소 기준 일정입니다.\n조회 범위: {date_from}~{date_to}\n\n{summary}"

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
        final_slot_payload: dict[str, Any] | None = None
        final_decision_payload: dict[str, Any] | None = None
        selected_agent: str | None = None
        for event in events:
            if event.get("event") == "tool_call" and event.get("tool_name") in {"nana_agent", "kana_agent"}:
                selected_agent = event["tool_name"]
            content = event.get("content")
            if isinstance(content, dict):
                inner_tool_names.extend(content.get("inner_tool_names") or [])
                if content.get("final_slot_payload"):
                    final_slot_payload = content["final_slot_payload"]
                elif "final_slot" in content:
                    final_slot_payload = content
                if content.get("final_decision_payload"):
                    final_decision_payload = content["final_decision_payload"]

        return {
            "events": events,
            "supervisor_selected_agent": selected_agent,
            "inner_tool_names": inner_tool_names,
            "final_slot_payload": final_slot_payload,
            "final_decision_payload": final_decision_payload,
        }
