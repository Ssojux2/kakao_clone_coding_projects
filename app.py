from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

import gradio as gr

from fixed.config import CONFIG, STATIC_DIR
from fixed.agent_runtime import AgentRuntime


runtime = AgentRuntime()
CSS_PATH = STATIC_DIR / "app.css"
MAX_CONVERSATION_BUTTONS = 12
ENTER_TO_SEND_HEAD = """
<script>
function setKananaTextareaValue(textarea, value) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
  setter.call(textarea, value);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.dispatchEvent(new Event("change", { bubbles: true }));
}

document.addEventListener("keydown", function(event) {
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) return;
  if (!target.closest("#kanana-input")) return;
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;

  event.preventDefault();
  event.stopPropagation();

  const sendRoot = document.querySelector("#kanana-send");
  const sendButton =
    sendRoot?.matches("button") ? sendRoot : sendRoot?.querySelector("button");

  if (sendButton && !sendButton.disabled) {
    sendButton.dispatchEvent(new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      view: window
    }));
  }
}, true);
</script>
"""
DELETE_CONVERSATION_CONFIRM_JS = """
function(conversationId) {
  if (!conversationId) {
    alert("삭제할 저장된 대화를 먼저 선택해 주세요.");
    return [""];
  }
  const confirmed = confirm("선택한 저장된 대화를 영구 삭제할까요?\\n이 작업은 되돌릴 수 없습니다.");
  return [confirmed ? conversationId : ""];
}
"""


def _trace_message(trace: dict[str, Any]) -> str:
    events = trace.get("events", [])
    lines = []
    for event in events[-8:]:
        label = event.get("event")
        tool_name = event.get("tool_name")
        if tool_name:
            lines.append(f"- `{label}` · `{tool_name}`")
        else:
            lines.append(f"- `{label}`")
    return "\n".join(lines) if lines else "- trace 없음"


def _saved_schedule_lines(limit: int = 8) -> list[str]:
    rows = runtime.app_store.list_schedules(limit=limit)
    lines: list[str] = []
    for row in rows:
        date = row.get("date") or "날짜 미정"
        start_time = row.get("start_time") or "시간 미정"
        end_time = row.get("end_time") or ""
        time_range = f"{start_time}-{end_time}" if end_time else start_time
        title = row.get("title") or "제목 없음"
        attendees = row.get("attendees") or []
        attendee_text = f" · 참석자: {', '.join(attendees)}" if attendees else ""
        lines.append(f"- {date} {time_range} · {title}{attendee_text}")
    return lines


def _chat_notice() -> list[dict[str, str]]:
    return []


def _conversation_rows() -> list[dict[str, str]]:
    rows = runtime.app_store.list_conversations()
    return [
        {
            "conversation_id": row["conversation_id"],
            "title": row["title"] or "새 대화",
            "preview": (row.get("last_message") or "").replace("\n", " ")[:54],
        }
        for row in rows[:MAX_CONVERSATION_BUTTONS]
    ]


def _conversation_button_updates(selected_id: str | None = None) -> list[Any]:
    rows = _conversation_rows()
    updates: list[Any] = []
    for index in range(MAX_CONVERSATION_BUTTONS):
        if index < len(rows):
            row = rows[index]
            label = row["title"]
            if row["conversation_id"] == selected_id:
                label = f"● {label}"
            updates.append(gr.update(value=label, visible=True))
        else:
            updates.append(gr.update(value="", visible=False))
    return updates


def queue_user_message(
    message: str,
    history: list[dict[str, Any]] | None,
    conversation_id: str | None,
) -> tuple:
    history = history or []
    message = (message or "").strip()
    if not message:
        return (
            history,
            {},
            conversation_id or "",
            gr.update(value="", interactive=True),
            "",
            gr.update(interactive=True),
            *_conversation_button_updates(conversation_id),
        )

    active_conversation_id = runtime.ensure_conversation(conversation_id or None, message)
    history = [
        *history,
        {"role": "user", "content": message},
    ]
    return (
        history,
        {"mode": "pending"},
        active_conversation_id,
        gr.update(value="", interactive=False),
        message,
        gr.update(interactive=False),
        *_conversation_button_updates(active_conversation_id),
    )


def finish_agent_response(
    pending_message: str,
    history: list[dict[str, Any]] | None,
    conversation_id: str | None,
) -> tuple:
    history = history or []
    pending_message = (pending_message or "").strip()
    if not pending_message:
        return (
            history,
            {},
            conversation_id or "",
            gr.update(interactive=True),
            "",
            gr.update(interactive=True),
            *_conversation_button_updates(conversation_id),
        )

    result = runtime.run_agent(pending_message, conversation_id or None)
    history = [*history, {"role": "assistant", "content": result.answer}]
    return (
        history,
        result.trace,
        result.conversation_id,
        gr.update(interactive=True),
        "",
        gr.update(interactive=True),
        *_conversation_button_updates(result.conversation_id),
    )


def new_chat() -> tuple:
    return (_chat_notice(), {}, "", *_conversation_button_updates(None))


def load_chat(conversation_id: str | None) -> tuple:
    if not conversation_id:
        return (_chat_notice(), "", *_conversation_button_updates(None))
    return (runtime.load_messages_for_chatbot(conversation_id), conversation_id, *_conversation_button_updates(conversation_id))


def archive_chat(conversation_id: str | None) -> tuple:
    runtime.archive_conversation(conversation_id)
    return (_chat_notice(), {}, "", *_conversation_button_updates(None))


def delete_chat(conversation_id: str | None) -> tuple:
    if conversation_id:
        runtime.delete_conversation(conversation_id)
    return (_chat_notice(), {}, "", *_conversation_button_updates(None))


def conversation_id_at(index: int) -> str:
    rows = _conversation_rows()
    if 0 <= index < len(rows):
        return rows[index]["conversation_id"]
    return ""


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Kanana Schedule Agent") as demo:
        conversation_id = gr.Textbox(value="", visible=False, elem_id="selected-conversation-id", container=False)
        pending_message = gr.State("")
        gr.HTML(
            f"""
            <div class="kanana-topbar">
              <div class="brand-lockup">
                <span>Smart Schedule Agent · Week {CONFIG.active_week}</span>
              </div>
            </div>
            """
        )
        with gr.Tabs(elem_id="main-tabs"):
            with gr.Tab("채팅"):
                with gr.Row(elem_id="kanana-shell"):
                    with gr.Column(scale=1, min_width=250, elem_classes=["sidebar"]):
                        new_btn = gr.Button("새 대화", elem_classes=["primary-action"])
                        gr.HTML("<div class='conversation-list-title'>대화</div>", container=False)
                        conversation_buttons = [
                            gr.Button(
                                "",
                                visible=False,
                                elem_classes=["conversation-list-item"],
                            )
                            for _ in range(MAX_CONVERSATION_BUTTONS)
                        ]
                        archive_btn = gr.Button("현재 대화 보관", elem_classes=["ghost-action"])
                        delete_btn = gr.Button("저장된 대화 삭제", elem_classes=["danger-action"])
                    with gr.Column(scale=4, min_width=560, elem_classes=["chat-panel"]):
                        chatbot = gr.Chatbot(
                            value=_chat_notice(),
                            height=680,
                            show_label=False,
                            elem_id="kanana-chatbot",
                            placeholder="무엇을 도와드릴까요?",
                        )
                        with gr.Row(elem_classes=["composer"]):
                            textbox = gr.Textbox(
                                placeholder="팀원 A/B/C와 다음 주 회의 시간을 잡아줘",
                                show_label=False,
                                lines=2,
                                elem_id="kanana-input",
                            )
                            send_btn = gr.Button("↑", elem_id="kanana-send", elem_classes=["send-button"])
            with gr.Tab("상세"):
                with gr.Row(elem_classes=["details-layout"]):
                    with gr.Column(scale=1, min_width=720, elem_classes=["detail-card", "trace-detail-card"]):
                        gr.HTML("<div class='trace-title'>마지막 에이전트 실행 Trace</div>")
                        trace_json = gr.JSON(
                            label="trace 페이로드",
                            value={},
                            elem_id="trace-json",
                            open=True,
                            min_height=620,
                            max_height=780,
                        )

        send_outputs = [chatbot, trace_json, conversation_id, textbox, pending_message, send_btn, *conversation_buttons]
        finish_outputs = [chatbot, trace_json, conversation_id, textbox, pending_message, send_btn, *conversation_buttons]
        send_btn.click(
            queue_user_message,
            inputs=[textbox, chatbot, conversation_id],
            outputs=send_outputs,
            queue=False,
        ).then(
            finish_agent_response,
            inputs=[pending_message, chatbot, conversation_id],
            outputs=finish_outputs,
            show_progress="minimal",
        )
        new_btn.click(new_chat, outputs=[chatbot, trace_json, conversation_id, *conversation_buttons])
        archive_btn.click(archive_chat, inputs=[conversation_id], outputs=[chatbot, trace_json, conversation_id, *conversation_buttons])
        delete_btn.click(
            delete_chat,
            inputs=[conversation_id],
            outputs=[chatbot, trace_json, conversation_id, *conversation_buttons],
            js=DELETE_CONVERSATION_CONFIRM_JS,
            queue=False,
        )
        for index, conversation_button in enumerate(conversation_buttons):
            conversation_button.click(
                lambda idx=index: conversation_id_at(idx),
                outputs=[conversation_id],
                show_progress="hidden",
            ).then(
                load_chat,
                inputs=[conversation_id],
                outputs=[chatbot, conversation_id, *conversation_buttons],
                show_progress="hidden",
            )
        demo.load(lambda: _conversation_button_updates(None), outputs=conversation_buttons)
    return demo


if __name__ == "__main__":
    if not CONFIG.has_openai_key:
        print("주의: 프롬프트 기반 에이전트 채팅에는 .env의 OPENAI_API_KEY가 필요합니다.")
    build_demo().launch(css_paths=[str(CSS_PATH)], head=ENTER_TO_SEND_HEAD)
