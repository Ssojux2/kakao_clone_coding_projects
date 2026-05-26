from __future__ import annotations

import json
from typing import Any

from langchain.tools import tool

from fixed.config import CONFIG
from fixed.stores import AppSQLiteStore, PersonalReferenceStore
from student_parts.week03_build_nanas_logbook import week03_tools


REFERENCE_STORE = PersonalReferenceStore(CONFIG.chroma_dir)
SQLITE_STORE = AppSQLiteStore(CONFIG.app_db_path)


@tool
def add_personal_reference(title: str, content: str, tags: list[str] | None = None) -> str:
    """개인 참고자료를 ChromaDB에 추가합니다."""

    # [4주차][학생 구현]
    # 개인 참고자료를 ChromaDB 컬렉션에 문서와 메타데이터로 저장하세요.
    #
    # [참고 답안]
    item = REFERENCE_STORE.add_personal_reference(title=title, content=content, tags=tags or [])
    return json.dumps({"ok": True, "tool_name": "add_personal_reference", "reference": item}, ensure_ascii=False)


@tool
def search_personal_references(query: str, limit: int = 3) -> str:
    """ChromaDB에 저장된 개인 참고자료를 검색합니다."""

    # [4주차][학생 구현]
    # 사용자의 질문을 검색어로 삼아 ChromaDB에서 관련 참고자료 결과를 반환하세요.
    #
    # [참고 답안]
    hits = REFERENCE_STORE.search_personal_references(query=query, limit=limit)
    return json.dumps({"ok": True, "tool_name": "search_personal_references", "hits": hits}, ensure_ascii=False)


@tool
def search_saved_requests(query: str, kind: str | None = None, limit: int = 5) -> str:
    """SQLite에 저장된 구조화 출력 결과를 검색합니다."""

    # [4주차][학생 구현]
    # ChromaDB 참고자료와 별도로 SQLite에 저장된 structured_requests 행을 검색하세요.
    #
    # [참고 답안]
    hits = SQLITE_STORE.search_saved_requests(query=query, kind=kind, limit=limit)
    return json.dumps({"ok": True, "tool_name": "search_saved_requests", "hits": hits}, ensure_ascii=False)


@tool
def build_rag_context(reference_hits: list[dict[str, Any]], sqlite_hits: list[dict[str, Any]]) -> str:
    """ChromaDB와 SQLite 검색 결과로 간결한 RAG 문맥을 만듭니다."""

    # [4주차][학생 구현]
    # ChromaDB 검색 결과와 SQLite 검색 결과를 모델 답변에 첨부하기 좋은 문맥 문자열로 합치세요.
    #
    # [참고 답안]
    lines = ["[개인 참고자료]"]
    for hit in reference_hits:
        lines.append(f"- {hit.get('title', '참고자료')}: {hit.get('content')}")
    lines.append("[SQLite 저장 요청]")
    for hit in sqlite_hits:
        title = hit.get("title") or "제목 없음"
        lines.append(f"- {hit.get('kind')} | {title} | {hit.get('date')} {hit.get('start_time') or ''}")
    context = "\n".join(lines)
    return json.dumps({"ok": True, "tool_name": "build_rag_context", "context": context}, ensure_ascii=False)


def search_personal_references_dict(query: str, limit: int = 3) -> list[dict[str, Any]]:
    return json.loads(search_personal_references.invoke({"query": query, "limit": limit}))["hits"]


def search_saved_requests_dict(query: str, kind: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    return json.loads(search_saved_requests.invoke({"query": query, "kind": kind, "limit": limit}))["hits"]


def build_rag_context_dict(reference_hits: list[dict[str, Any]], sqlite_hits: list[dict[str, Any]]) -> str:
    return json.loads(
        build_rag_context.invoke({"reference_hits": reference_hits, "sqlite_hits": sqlite_hits})
    )["context"]


def week04_tools() -> list[Any]:
    """3주차까지의 도구에 4주차 RAG 도구를 누적한 목록입니다."""

    return [
        *week03_tools(),
        add_personal_reference,
        search_personal_references,
        search_saved_requests,
        build_rag_context,
    ]
