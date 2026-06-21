from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.app_store import AppSQLiteStore
from fixed.reference_store import PersonalReferenceStore
from student_parts.week01_wake_up_nana import join_system_prompt
from student_parts.week03_build_nanas_logbook import week03_prompt_parts, week03_tools


REFERENCE_STORE = PersonalReferenceStore(CONFIG.chroma_dir)
SQLITE_STORE = AppSQLiteStore(CONFIG.app_db_path)
_WEEK04_AGENT: Any | None = None


# [수강생 구현 가이드]
#
# 목표
#   Nana가 "내가 적어 둔 참고자료"와 "SQLite에 저장된 일정/할 일 기록"을 구분해서 검색하게 합니다.
#   Week 4의 핵심은 RAG를 하나의 마법 함수로 보지 않고, 데이터 출처별 검색 tool을 분리하는 것입니다.
#
# 구현 위치와 사용할 코드
#   - 이 파일(student_parts/week04_retrieve_nanas_memory.py)의 개인 참고자료/RAG tool을 구현합니다.
#   - 개인 참고자료 저장소는 fixed/reference_store.py의 PersonalReferenceStore이며,
#     이 파일 상단의 REFERENCE_STORE가 CONFIG.chroma_dir 기준 인스턴스입니다.
#   - SQLite 저장 요청 검색은 fixed/app_store.py의 AppSQLiteStore를 사용하고,
#     이 파일 상단의 SQLITE_STORE가 CONFIG.app_db_path 기준 인스턴스입니다.
#   - add_personal_reference_payload(), search_personal_reference_hits(),
#     search_saved_request_rows(), search_conversation_message_rows()에 실제 호출/정규화 로직을 둡니다.
#   - tool 함수 add_personal_reference/search_personal_references/search_saved_requests는
#     위 helper 결과를 json_payload()로 감싼 JSON 문자열로 반환합니다.
#   - top_k/limit 보정은 이 파일의 safe_limit()를 사용해 tool 안에서 처리합니다.
#   - week04_tools()는 student_parts/week03_build_nanas_logbook.py의 week03_tools() 위에
#     Week 4 RAG tool을 누적해 agent에 공개합니다.
#
# 구현 대상
#   1. add_personal_reference
#      - title/content/tags를 REFERENCE_STORE.add_personal_reference에 넘깁니다.
#      - tags가 None이면 빈 list로 바꿉니다.
#      - 이 tool 안에서 reference_backend와 reference가 있는 JSON payload를 완성합니다.
#
#   2. search_personal_references
#      - query와 top_k로 ChromaDB 개인 참고자료를 검색합니다.
#      - top_k는 이 tool 안에서 안전한 범위로 정리합니다.
#      - course repo 기준 계약에 맞게 top-level {"hits": [...]} JSON을 반환합니다.
#      - hit에는 id, content, distance, metadata(title/tags)가 들어가야 답변 근거로 쓰기 쉽습니다.
#
#   3. search_saved_requests
#      - SQLITE_STORE.search_saved_requests(query, limit)를 호출합니다.
#      - top_k는 이 tool 안에서 안전한 범위로 정리합니다.
#      - 검색 결과가 없으면 rows=[]를 그대로 반환합니다.
#      - course repo 기준 계약에 맞게 top-level {"rows": [...]} JSON을 반환합니다.
#
# 출처 구분
#   search_personal_references는 ChromaDB + OpenAI embedding 기반 reference 검색입니다.
#   search_saved_requests는 SQLite structured_requests/schedules 계열 기록 검색입니다.
#   LLM이 질문 성격에 따라 둘 중 하나 또는 둘 다 선택하도록 prompt가 준비되어 있습니다.
#
# 참고 코드
#   search_nana_memory는 reference_backend와 context를 함께 확인하는 compatibility helper입니다.
#   학생 핵심 구현 대상은 add/search_personal_references/search_saved_requests 3개입니다.
#   week04_tools()는 Week 1-3 도구에 이 RAG 도구들을 누적합니다.
#
# 검증 방법
#   참고자료를 추가한 뒤 관련 질문을 입력하고 trace에서 search_personal_references 호출을 확인합니다.
#   저장된 일정/할 일 질문은 search_saved_requests가 호출되는지 확인합니다.
#   결과 JSON의 top-level 키가 각각 hits, rows인지 꼭 확인하세요.


def _decode_attendees(raw_attendees: str | None) -> list[str]:
    try:
        decoded = json.loads(raw_attendees or "[]")
    except Exception:
        return []
    return decoded if isinstance(decoded, list) else []


def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


def safe_limit(limit: int, default: int = 5, maximum: int = 50) -> int:
    """사용자/LLM이 넘긴 limit 값을 안전한 양의 정수 범위로 보정합니다."""

    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def add_personal_reference_payload(
    reference_store: PersonalReferenceStore,
    *,
    title: str,
    content: str,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """개인 참고자료를 vector store에 추가하고 backend 정보가 포함된 payload를 만듭니다."""

    item = reference_store.add_personal_reference(title=title, content=content, tags=tags or [])
    return {
        "ok": True,
        "tool_name": "add_personal_reference",
        "reference_backend": reference_store.backend_info(),
        "reference": item,
    }


def search_personal_reference_hits(
    reference_store: PersonalReferenceStore,
    *,
    query: str,
    top_k: int = 2,
) -> list[dict[str, Any]]:
    """ChromaDB 검색 결과를 tool이 바로 반환하기 쉬운 hit 구조로 정리합니다."""

    hits = reference_store.search_personal_references(query=query, limit=safe_limit(top_k, default=2, maximum=20))
    return [
        {
            "id": hit.get("id"),
            "content": hit.get("content"),
            "distance": hit.get("distance"),
            "metadata": {
                "title": hit.get("title", ""),
                "tags": hit.get("tags", ""),
            },
        }
        for hit in hits
    ]


def search_saved_request_rows(
    sqlite_store: AppSQLiteStore,
    *,
    query: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """SQLite 저장 요청을 검색하고 실제 검색 결과만 반환합니다."""

    limit = safe_limit(top_k, default=3, maximum=50)
    return sqlite_store.search_saved_requests(query=query, limit=limit)


def search_conversation_message_rows(
    sqlite_store: AppSQLiteStore,
    *,
    query: str,
    top_k: int = 5,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    """앱 SQLite에 저장된 일반 채팅 메시지를 검색합니다."""

    limit = safe_limit(top_k, default=5, maximum=50)
    return sqlite_store.search_conversation_messages(
        query=query,
        conversation_id=conversation_id,
        limit=limit,
    )


@tool
def add_personal_reference(title: str, content: str, tags: list[str] | None = None) -> str:
    """개인 참고자료를 ChromaDB에 추가합니다."""

    return json_payload(
        add_personal_reference_payload(REFERENCE_STORE, title=title, content=content, tags=tags)
    )


@tool
def search_personal_references(query: str, top_k: int = 2) -> str:
    """개인 참고자료를 ChromaDB와 OpenAI embedding 기반으로 검색합니다."""

    return json_payload({"hits": search_personal_reference_hits(REFERENCE_STORE, query=query, top_k=top_k)})


@tool
def search_saved_requests(query: str, top_k: int = 3) -> str:
    """SQLite에 저장된 구조화 일정/할 일/알림 row를 검색합니다. query에는 LLM이 고른 일정/할 일/알림 핵심어를 넣습니다."""

    return json_payload({"rows": search_saved_request_rows(SQLITE_STORE, query=query, top_k=top_k)})


@tool
def search_conversation_messages(
    query: str,
    top_k: int = 5,
    conversation_id: str | None = None,
) -> str:
    """앱 SQLite에 저장된 일반 채팅 메시지 목록을 검색합니다. query에는 LLM이 고른 짧은 핵심 명사나 구를 넣습니다."""

    return json_payload(
        {
            "rows": search_conversation_message_rows(
                SQLITE_STORE,
                query=query,
                top_k=top_k,
                conversation_id=conversation_id,
            )
        }
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

    normalized_limit = safe_limit(limit, default=5, maximum=20)
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
            "reference_backend": REFERENCE_STORE.backend_info(),
            "reference_hits": reference_hits,
            "schedule_chunks": schedule_chunks,
            "context": context,
        },
        ensure_ascii=False,
    )

def week04_tools() -> list[Any]:
    """3주차까지의 도구에 4주차 RAG 도구를 누적한 목록입니다."""

    return [
        *week03_tools(),
        add_personal_reference,
        search_personal_references,
        search_saved_requests,
        search_conversation_messages,
    ]


def week04_system_prompt() -> str:
    """4주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week04_prompt_parts())


def week04_prompt_parts() -> list[str]:
    """1~4주차 system prompt 조각을 누적합니다."""

    return [
        *week03_prompt_parts(),
        "너는 Kanana의 Week 4 Nana memory agent다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "개인 일정/할 일/알림 생성과 저장은 extract_schedule_request로 구조화한 뒤 "
        "structured_request를 바로 save_structured_request에 전달한다. "
        "Week 4에서는 personal_create_schedule을 새 일정 저장용으로 사용하지 않는다. "
        "개인 참고자료를 추가해야 할 때만 add_personal_reference를 사용한다. "
        "검색 tool의 query는 코드에서 토큰화하지 않으므로, 질문 전체가 아니라 네가 직접 고른 짧은 핵심 검색 문자열을 넣는다. "
        "사용자가 직전 질문에 이어 '지난 대화 검색해서 찾아줘'처럼 말하면 직전 질문의 대상 명사를 query로 삼는다. "
        "예를 들어 '내가 가지고 있는 양의 색은 뭐야?' 다음 검색 요청은 search_conversation_messages(query='양')처럼 호출한다. "
        "개인 참고자료 질문은 search_personal_references의 hits를 근거로 답한다. "
        "저장된 일정, 할 일, 알림 질문은 search_saved_requests의 rows를 근거로 답한다. "
        "사용자가 '내가 했던 대화 목록', '이전 채팅', '방금 다른 대화에서 말한 내용'처럼 "
        "일정/할 일/알림이 아닌 일반 채팅 발화에서 답을 찾으라고 하면 search_conversation_messages의 rows를 근거로 답한다. "
        "일반 채팅 발화 검색 결과가 비어 있으면 search_saved_requests로 넘어가지 말고, 같은 search_conversation_messages에 더 짧은 핵심어로 다시 검색한다. "
        "search_conversation_messages 결과에는 현재 질문이나 assistant의 추측/부정 답변도 섞일 수 있으므로 "
        "사용자 role의 단언형 메시지를 우선 근거로 삼고, 질문문만으로 사실을 확정하지 않는다. "
        "일정 목록이나 내 일정 조회 요청은 Week 3의 personal_list_saved_schedules로 앱 SQLite 일정 row를 확인할 수 있다. "
        "특정 날짜나 기간의 일정 조회는 personal_list_saved_schedules의 date_from/date_to를 YYYY-MM-DD로 채워 조회한다. "
        "personal_list_schedules는 Week 1-2 현재 대화 임시 메모리 조회 전용이므로 Week 4의 단순 일정 조회에는 사용하지 않는다. "
        "새 대화에서도 SQLite 저장 row는 유지되므로 현재 채팅 전사에 없다는 이유로 모른다고 답하지 않는다. "
        "Week 4에서는 외부 멤버 이전 대화나 그룹 일정 최종 조율을 처리하지 않는다. "
        "도구 결과에 없는 사실은 만들지 않는다."
    ]


def build_week04_agent() -> object:
    """Week 1-4 누적 tool 목록을 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK04_AGENT
    if _WEEK04_AGENT is None:
        _WEEK04_AGENT = create_agent(
            model=chat_model(),
            tools=week04_tools(),
            system_prompt=week04_system_prompt(),
        )
    return _WEEK04_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week04_agent()
