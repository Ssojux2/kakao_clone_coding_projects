from __future__ import annotations

"""student_parts에서 재사용하는 JSON payload 빌더 모음입니다.

학생 구현 파일은 LangChain `@tool` 함수의 입출력 계약을 보여 주는 곳이고,
실제 저장소 조작이나 공통 payload 조립은 이 모듈로 모아 둡니다. 덕분에 Week 3~6의
도구 본문은 "입력 정리 -> helper 호출 -> JSON 문자열 반환" 흐름을 명확히 유지합니다.
"""

import json
from typing import Any, Callable

from fixed.app_store import AppSQLiteStore
from fixed.config import CONFIG
from fixed.mcp_client import call_local_mcp_tool_sync
from fixed.external_people_store import (
    external_schedule_summary,
    normalize_external_member_names,
    normalize_external_schedule_date_bounds,
)
from fixed.reference_store import PersonalReferenceStore


def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


def coerce_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    """dict 또는 JSON 문자열 payload를 저장소가 받을 수 있는 dict로 맞춥니다."""

    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def save_structured_request_payload(
    payload: dict[str, Any] | str,
    *,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """structured request를 앱 DB에 저장하고 tool 결과 payload를 만듭니다."""

    selected_store = store or AppSQLiteStore(CONFIG.app_db_path)
    saved = selected_store.save_structured_request(coerce_payload(payload))
    return {"ok": True, "tool_name": "save_structured_request", **saved}


def list_saved_requests_payload(
    *,
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """저장된 structured request 목록을 조회하는 tool payload를 만듭니다."""

    selected_store = store or AppSQLiteStore(CONFIG.app_db_path)
    rows = selected_store.list_saved_requests(kind=kind, date_from=date_from, date_to=date_to)
    return {"ok": True, "tool_name": "list_saved_requests", "rows": rows}


def get_saved_request_payload(request_id: str, *, store: AppSQLiteStore | None = None) -> dict[str, Any]:
    """request_id 하나로 저장 요청을 조회하는 tool payload를 만듭니다."""

    selected_store = store or AppSQLiteStore(CONFIG.app_db_path)
    return {"ok": True, "tool_name": "get_saved_request", "row": selected_store.get_saved_request(request_id)}


def list_saved_schedules_payload(limit: int = 50, *, store: AppSQLiteStore | None = None) -> dict[str, Any]:
    """수정/삭제 후보로 보여 줄 저장 일정 목록 payload를 만듭니다."""

    selected_store = store or AppSQLiteStore(CONFIG.app_db_path)
    return {
        "ok": True,
        "tool_name": "personal_list_saved_schedules",
        "schedules": selected_store.list_schedules(limit=limit),
    }


def update_saved_schedule_payload(
    schedule_id: str,
    *,
    title: str | None = None,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    attendees: list[str] | None = None,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """저장 일정 하나를 수정하고 성공/실패 tool payload를 반환합니다.

    저장소가 개인 일정 공유 복사본까지 갱신하므로 결과에는 `shared_sync`도 포함됩니다.
    """

    selected_store = store or AppSQLiteStore(CONFIG.app_db_path)
    updated = selected_store.update_schedule(
        schedule_id=schedule_id,
        title=title,
        date=date,
        start_time=start_time,
        end_time=end_time,
        attendees=attendees,
    )
    if updated is None:
        return {
            "ok": False,
            "tool_name": "personal_update_saved_schedule",
            "reason": "수정할 일정 ID를 찾지 못했습니다.",
            "schedule_id": schedule_id,
            "updated_schedule": None,
            "shared_sync": None,
        }
    return {
        "ok": True,
        "tool_name": "personal_update_saved_schedule",
        "schedule_id": schedule_id,
        "updated_schedule": updated["schedule"],
        "shared_sync": updated["shared_sync"],
    }


def delete_saved_schedules_payload(
    *,
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """필터에 맞는 저장 일정을 삭제하는 tool payload를 만듭니다.

    실수로 전체 삭제가 일어나지 않게 `delete_all=True`가 아닌 경우에는 일정 ID나
    날짜/제목/시간 필터 중 하나가 반드시 필요합니다.
    """

    selected_store = store or AppSQLiteStore(CONFIG.app_db_path)
    filters = {
        "schedule_ids": schedule_ids,
        "date": date,
        "title": title,
        "start_time": start_time,
        "time_unspecified": time_unspecified,
    }
    has_filter = schedule_ids is not None or any([date, title, start_time, time_unspecified])
    if not delete_all and not has_filter:
        return {
            "ok": False,
            "tool_name": "personal_delete_saved_schedules",
            "reason": "삭제할 일정 ID나 날짜/제목/시간 필터가 필요합니다.",
            "delete_all": False,
            "bulk_delete": False,
            "deleted_count": 0,
            "filters": filters,
            "deleted": [],
        }

    if delete_all:
        deleted_rows = selected_store.delete_all_schedules()
    else:
        deleted_rows = selected_store.delete_schedules_by_filter(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
        )
    deleted = [{"source": "app_db", "schedule": row} for row in deleted_rows]
    return {
        "ok": bool(deleted),
        "tool_name": "personal_delete_saved_schedules",
        "delete_all": delete_all,
        "bulk_delete": bool(not delete_all and deleted),
        "deleted_count": len(deleted),
        "filters": filters,
        "deleted": deleted,
    }


def delete_schedule_by_query_payload(
    query: str,
    *,
    extract_structured_request: Callable[[str], Any],
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """자연어 삭제 요청을 구조화한 뒤 일정 삭제 필터로 변환합니다.

    Week 3/6의 호환 도구가 사용합니다. 제목이 너무 일반적인 값이면 title 필터를 빼고,
    날짜와 시작 시간처럼 더 안전한 단서 위주로 삭제 대상을 좁힙니다.
    """

    structured = extract_structured_request(query).model_dump()
    title = str(structured.get("title") or "").strip()
    filters = {
        key: value
        for key, value in {
            "date": structured.get("date"),
            "title": None if title in {"", "개인 일정", "그룹 일정", "제목 없음"} else title,
            "start_time": structured.get("start_time"),
        }.items()
        if value
    }
    result = delete_saved_schedules_payload(store=store, **filters)
    result["tool_name"] = "personal_delete_schedule_by_query"
    result["structured_request"] = structured
    if not result["ok"] and not filters:
        result["reason"] = "삭제할 일정을 충분히 특정하지 못했습니다. 먼저 저장 일정 목록을 확인해 주세요."
    return result


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
    """SQLite 저장 요청을 검색하고 결과가 없으면 최근 저장 목록으로 fallback합니다."""

    limit = safe_limit(top_k, default=3, maximum=50)
    rows = sqlite_store.search_saved_requests(query=query, limit=limit)
    if not rows:
        rows = sqlite_store.list_saved_requests(limit=limit)
    return rows


def collect_member_schedules_payload(
    *,
    member_names: list[str],
    date_from: str,
    date_to: str,
    personal_schedules: list[dict[str, Any]],
) -> dict[str, Any]:
    """내 일정과 외부 멤버 일정을 같은 row 구조로 합칩니다.

    `personal_schedules`는 앱 내부 Nana 일정 목록이고, 외부 멤버 일정은 MCP
    `extract_schedules_from_history` 도구를 통해 가져옵니다. 반환 payload는 Week 6의
    공통 가능 시간 계산이 바로 사용할 수 있는 `members`, `rows`, `schedule_summary`를 담습니다.
    """

    normalized_members = normalize_external_member_names(member_names)
    normalized_date_from, normalized_date_to = normalize_external_schedule_date_bounds(
        normalized_members,
        date_from,
        date_to,
    )
    my_rows: list[dict[str, Any]] = []
    for row in personal_schedules:
        schedule_date = row.get("date")
        if not schedule_date:
            continue
        if normalized_date_from and schedule_date < normalized_date_from:
            continue
        if normalized_date_to and schedule_date > normalized_date_to:
            continue
        end_time = row.get("end_time")
        my_rows.append(
            {
                "member_name": "나",
                "title": row.get("title"),
                "date": schedule_date,
                "start_time": row.get("start_time"),
                "end_time": end_time if end_time != "미정" else "18:00",
                "notes": "Nana 개인 일정",
            }
        )

    external_payload = json.loads(
        call_local_mcp_tool_sync(
            "extract_schedules_from_history",
            {
                "member_names": normalized_members,
                "date_from": normalized_date_from,
                "date_to": normalized_date_to,
            },
        )
    )
    rows = [*my_rows, *external_payload.get("rows", [])]
    return {
        "ok": True,
        "tool_name": "collect_member_schedules",
        "members": ["나", *normalized_members],
        "rows": rows,
        "schedule_summary": external_schedule_summary(rows),
    }
