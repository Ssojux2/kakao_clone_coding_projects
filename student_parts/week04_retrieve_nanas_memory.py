from __future__ import annotations

import json
from typing import Any

from langchain.tools import tool

from fixed.config import CONFIG
from fixed.stores import AppSQLiteStore, PersonalReferenceStore
from student_parts.week03_build_nanas_logbook import week03_tools


REFERENCE_STORE = PersonalReferenceStore(CONFIG.chroma_dir)
SQLITE_STORE = AppSQLiteStore(CONFIG.app_db_path)


def _safe_limit(limit: int, default: int = 5, maximum: int = 50) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _decode_attendees(raw_attendees: str | None) -> list[str]:
    try:
        decoded = json.loads(raw_attendees or "[]")
    except Exception:
        return []
    return decoded if isinstance(decoded, list) else []


def _reference_backend_info() -> dict[str, Any]:
    return REFERENCE_STORE.backend_info()


@tool
def add_personal_reference(title: str, content: str, tags: list[str] | None = None) -> str:
    """개인 참고자료를 ChromaDB에 추가합니다."""

    item = REFERENCE_STORE.add_personal_reference(title=title, content=content, tags=tags or [])
    return json.dumps(
        {
            "ok": True,
            "tool_name": "add_personal_reference",
            "reference_backend": _reference_backend_info(),
            "reference": item,
        },
        ensure_ascii=False,
    )


@tool
def search_nana_memory(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    attendee: str | None = None,
    limit: int = 5,
) -> str:
    """개인 참고자료와 SQLite 저장 일정을 한 번에 검색하고 일정 chunk를 반환합니다."""

    normalized_limit = _safe_limit(limit, default=5, maximum=20)
    reference_hits = REFERENCE_STORE.search_personal_references(query=query, limit=min(normalized_limit, 5))

    clauses: list[str] = []
    params: list[Any] = []
    if query.strip():
        clauses.append("(title LIKE ? OR date LIKE ? OR start_time LIKE ? OR end_time LIKE ? OR attendees_json LIKE ?)")
        token = f"%{query.strip()}%"
        params.extend([token, token, token, token, token])
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to)
    if attendee:
        clauses.append("attendees_json LIKE ?")
        params.append(f"%{attendee}%")

    sql = """
        SELECT schedule_id, request_id, owner, title, date, start_time, end_time,
               attendees_json, source, created_at
        FROM schedules
    """
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += """
        ORDER BY (date IS NULL), date ASC, (start_time IS NULL), start_time ASC, created_at DESC
        LIMIT ?
    """
    params.append(normalized_limit)

    with SQLITE_STORE.connect() as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

    schedule_chunks: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        raw_attendees = row.pop("attendees_json", "[]")
        attendees = _decode_attendees(raw_attendees)
        schedule_id = row.get("schedule_id") or f"schedule_{index}"
        start_time = row.get("start_time") or "시간 미정"
        end_time = row.get("end_time")
        time_range = f"{start_time}-{end_time}" if end_time else start_time
        attendee_text = ", ".join(attendees) if attendees else "참석자 미정"
        date = row.get("date") or "날짜 미정"
        title = row.get("title") or "제목 없음"
        schedule_chunks.append(
            {
                "chunk_id": f"schedule:{schedule_id}:0",
                "schedule_id": schedule_id,
                "title": title,
                "date": row.get("date"),
                "time_range": time_range,
                "attendees": attendees,
                "content": f"{date} {time_range} | {title} | 참석자: {attendee_text}",
                "metadata": {
                    "request_id": row.get("request_id"),
                    "owner": row.get("owner"),
                    "source": row.get("source"),
                    "created_at": row.get("created_at"),
                },
            }
        )

    lines = ["[개인 참고자료]"]
    for hit in reference_hits:
        lines.append(f"- {hit.get('title', '참고자료')}: {hit.get('content')}")
    lines.append("[SQLite 일정 chunk]")
    if not schedule_chunks:
        lines.append("- 검색된 저장 일정이 없습니다.")
    for chunk in schedule_chunks:
        source = (chunk.get("metadata") or {}).get("source") or "unknown"
        lines.append(f"- {chunk.get('chunk_id')} | {chunk.get('content')} | source={source}")
    context = "\n".join(lines)
    return json.dumps(
        {
            "ok": True,
            "tool_name": "search_nana_memory",
            "reference_backend": _reference_backend_info(),
            "reference_hits": reference_hits,
            "schedule_chunks": schedule_chunks,
            "context": context,
        },
        ensure_ascii=False,
    )


def search_nana_memory_dict(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    attendee: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    return json.loads(
        search_nana_memory.invoke(
            {
                "query": query,
                "date_from": date_from,
                "date_to": date_to,
                "attendee": attendee,
                "limit": limit,
            }
        )
    )


def week04_tools() -> list[Any]:
    """3주차까지의 도구에 4주차 RAG 도구를 누적한 목록입니다."""

    return [
        *week03_tools(),
        add_personal_reference,
        search_nana_memory,
    ]
