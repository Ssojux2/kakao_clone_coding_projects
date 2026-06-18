from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from fixed.config import CONFIG
from fixed.stores import ExternalPeopleSQLiteStore, external_schedule_summary, normalize_external_member_names


DB_PATH = Path(os.getenv("KANANA_EXTERNAL_DB_PATH", str(CONFIG.external_db_path)))
STORE = ExternalPeopleSQLiteStore(DB_PATH)
mcp = FastMCP("kanana-sqlite-history")


@mcp.tool()
def search_previous_conversations(query: str, member_names: list[str] | None = None, limit: int = 5) -> str:
    """외부 Kanana SQLite 데이터베이스에서 이전 대화를 검색합니다."""

    normalized_members = normalize_external_member_names(member_names) if member_names is not None else None
    rows = STORE.search_previous_conversations(query=query, member_names=normalized_members, limit=limit)
    return json.dumps({"ok": True, "tool_name": "search_previous_conversations", "rows": rows}, ensure_ascii=False)


@mcp.tool()
def load_conversation_messages(conversation_id: str) -> str:
    """특정 이전 대화의 모든 메시지를 불러옵니다."""

    rows = STORE.load_conversation_messages(conversation_id=conversation_id)
    return json.dumps({"ok": True, "tool_name": "load_conversation_messages", "rows": rows}, ensure_ascii=False)


@mcp.tool()
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """이전 대화 기록에서 멤버별 일정을 추출하고 날짜/시간 포함 요약을 반환합니다."""

    rows = STORE.extract_schedules_from_history(
        member_names=normalize_external_member_names(member_names),
        date_from=date_from,
        date_to=date_to,
    )
    return json.dumps(
        {
            "ok": True,
            "tool_name": "extract_schedules_from_history",
            "rows": rows,
            "schedule_summary": external_schedule_summary(rows),
        },
        ensure_ascii=False,
    )


@mcp.tool()
def create_shared_schedule(
    member_name: str,
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    notes: str | None = None,
    source_conversation_id: str | None = None,
    schedule_id: str | None = None,
) -> str:
    """공유 일정 저장소에 일정을 등록하거나 같은 schedule_id의 일정을 갱신합니다."""

    row = STORE.create_shared_schedule(
        member_name=member_name,
        title=title,
        date=date,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
        source_conversation_id=source_conversation_id,
        schedule_id=schedule_id,
    )
    return json.dumps(
        {
            "ok": True,
            "tool_name": "create_shared_schedule",
            "shared_schedule": row,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def delete_shared_schedule(
    schedule_id: str | None = None,
    source_conversation_id: str | None = None,
) -> str:
    """공유 일정 저장소에서 schedule_id 또는 앱 원본 request_id로 연결된 일정을 삭제합니다."""

    deleted = STORE.delete_shared_schedules(
        schedule_id=schedule_id,
        source_conversation_id=source_conversation_id,
    )
    return json.dumps(
        {
            "ok": True,
            "tool_name": "delete_shared_schedule",
            "deleted_count": len(deleted),
            "deleted": deleted,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def list_shared_schedules(
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_conversation_id: str | None = None,
    limit: int = 50,
) -> str:
    """공유 일정 저장소에 등록된 일정을 필터링해 조회합니다."""

    rows = STORE.list_shared_schedules(
        member_names=member_names,
        date_from=date_from,
        date_to=date_to,
        source_conversation_id=source_conversation_id,
        limit=limit,
    )
    return json.dumps(
        {
            "ok": True,
            "tool_name": "list_shared_schedules",
            "rows": rows,
            "schedule_summary": external_schedule_summary(rows),
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
