from __future__ import annotations

import json
import re
from typing import Any

from langchain.tools import tool

from fixed.config import CONFIG
from fixed.stores import AppSQLiteStore
from student_parts.week01_wake_up_nana import list_personal_schedule_dicts, personal_delete_schedule
from student_parts.week02_structure_natural_language_requests import extract_structured_request, week02_tools


STORE = AppSQLiteStore(CONFIG.app_db_path)
_DELETE_ALL_WORDS = ("전체", "전부", "모든", "모두", "all", "every")


def _coerce_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _compact(value: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value or "").lower()


def _query_mentions_date(query: str) -> bool:
    return bool(
        re.search(r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}", query)
        or re.search(r"\d{1,2}월\s*\d{1,2}일", query)
        or any(word in query for word in ["오늘", "내일", "모레", "다음 주", "다음주"])
    )


def _query_wants_all_schedules(query: str) -> bool:
    compact = _compact(query)
    return any(word in compact for word in _DELETE_ALL_WORDS) or bool(re.search(r"(?:총\s*)?\d+\s*건", query))


def _title_filter_from_structured(structured: dict[str, Any]) -> str | None:
    title = str(structured.get("title") or "").strip()
    compact_title = _compact(title)
    if not title or title in {"개인 일정", "그룹 일정", "제목 없음"}:
        return None
    if any(word in compact_title for word in ["삭제", "지워", "취소", "전체", "전부", "모든", "모두"]):
        return None
    return title


def _delete_filter_from_query(query: str) -> tuple[dict[str, Any], dict[str, Any]]:
    structured_model = extract_structured_request(query)
    structured = structured_model.model_dump()
    filters: dict[str, Any] = {}
    if _query_mentions_date(query) and structured.get("date"):
        filters["date"] = structured["date"]
    if structured.get("start_time"):
        filters["start_time"] = structured["start_time"]
    if "시간미정" in _compact(query):
        filters["time_unspecified"] = True
    title = _title_filter_from_structured(structured)
    if title:
        filters["title"] = title
    return structured, filters


def _schedule_filter_payload(
    schedule_ids: list[str] | None,
    date: str | None,
    title: str | None,
    start_time: str | None,
    time_unspecified: bool,
) -> dict[str, Any]:
    return {
        "schedule_ids": schedule_ids,
        "date": date,
        "title": title,
        "start_time": start_time,
        "time_unspecified": time_unspecified,
    }


def _memory_schedule_matches(
    schedule: dict[str, Any],
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
) -> bool:
    if schedule_ids is not None and schedule["id"] not in schedule_ids:
        return False
    if date and schedule.get("date") != date:
        return False
    if title and _compact(title) not in _compact(schedule.get("title")):
        return False
    if start_time and schedule.get("start_time") != start_time:
        return False
    if time_unspecified and schedule.get("start_time") not in {None, "", "미정"}:
        return False
    return True


def _delete_memory_schedules(
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
) -> list[dict[str, Any]]:
    rows = list(list_personal_schedule_dicts())
    if not delete_all:
        rows = [
            row
            for row in rows
            if _memory_schedule_matches(
                row,
                schedule_ids=schedule_ids,
                date=date,
                title=title,
                start_time=start_time,
                time_unspecified=time_unspecified,
            )
        ]
    deleted: list[dict[str, Any]] = []
    for row in rows:
        result = json.loads(personal_delete_schedule.invoke({"schedule_id": row["id"]}))
        if result.get("deleted"):
            deleted.append(row)
    return deleted


@tool
def save_structured_request(payload: dict[str, Any] | str) -> str:
    """2주차 구조화 출력 페이로드를 정규화된 SQLite 테이블에 저장합니다."""

    saved = STORE.save_structured_request(_coerce_payload(payload))
    return json.dumps({"ok": True, "tool_name": "save_structured_request", **saved}, ensure_ascii=False)


@tool
def list_saved_requests(
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """SQLite에 저장된 구조화 요청 목록을 조회합니다."""

    rows = STORE.list_saved_requests(kind=kind, date_from=date_from, date_to=date_to)
    return json.dumps({"ok": True, "tool_name": "list_saved_requests", "rows": rows}, ensure_ascii=False)


@tool
def get_saved_request(request_id: str) -> str:
    """request_id로 구조화 요청 행 하나를 조회합니다."""

    row = STORE.get_saved_request(request_id)
    return json.dumps({"ok": True, "tool_name": "get_saved_request", "row": row}, ensure_ascii=False)


@tool
def personal_list_saved_schedules(limit: int = 50) -> str:
    """앱 DB에 저장된 일정 목록을 반환합니다. Nana가 삭제 후보를 직접 고를 때 사용합니다."""

    store = AppSQLiteStore(CONFIG.app_db_path)
    return json.dumps(
        {
            "ok": True,
            "tool_name": "personal_list_saved_schedules",
            "schedules": store.list_schedules(limit=limit),
        },
        ensure_ascii=False,
    )


def delete_saved_schedules_dict(
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
    app_store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    store = app_store or AppSQLiteStore(CONFIG.app_db_path)
    has_filter = schedule_ids is not None or any([date, title, start_time, time_unspecified])
    if not delete_all and not has_filter:
        filters = _schedule_filter_payload(schedule_ids, date, title, start_time, time_unspecified)
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
        app_deleted = store.delete_all_schedules()
    else:
        app_deleted = store.delete_schedules_by_filter(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
        )
    memory_deleted = _delete_memory_schedules(
        schedule_ids=schedule_ids,
        date=date,
        title=title,
        start_time=start_time,
        time_unspecified=time_unspecified,
        delete_all=delete_all,
    )

    deleted = [
        *({"source": "app_db", "schedule": row} for row in app_deleted),
        *({"source": "memory", "schedule": row} for row in memory_deleted),
    ]

    return {
        "ok": bool(deleted),
        "tool_name": "personal_delete_saved_schedules",
        "delete_all": delete_all,
        "bulk_delete": bool(not delete_all and deleted),
        "deleted_count": len(deleted),
        "filters": _schedule_filter_payload(schedule_ids, date, title, start_time, time_unspecified),
        "deleted": deleted,
    }


@tool
def personal_delete_saved_schedules(
    schedule_ids: list[str] | None = None,
    date: str | None = None,
    title: str | None = None,
    start_time: str | None = None,
    time_unspecified: bool = False,
    delete_all: bool = False,
) -> str:
    """Nana가 고른 일정 ID나 날짜/제목/시간 필터로 저장 일정을 삭제합니다."""

    return json.dumps(
        delete_saved_schedules_dict(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
            delete_all=delete_all,
        ),
        ensure_ascii=False,
    )


def delete_schedule_by_query_dict(query: str, app_store: AppSQLiteStore | None = None) -> dict[str, Any]:
    structured, filters = _delete_filter_from_query(query)
    delete_all = _query_wants_all_schedules(query) and not filters
    result = delete_saved_schedules_dict(delete_all=delete_all, app_store=app_store, **filters)
    result["tool_name"] = "personal_delete_schedule_by_query"
    result["structured_request"] = structured
    if not result["ok"] and not filters and not delete_all:
        result["reason"] = "삭제할 일정을 충분히 특정하지 못했습니다. 먼저 저장 일정 목록을 확인해 주세요."
    return result


@tool
def personal_delete_schedule_by_query(query: str) -> str:
    """일정 ID가 없어도 사용자 프롬프트의 날짜, 시간, 제목 단서로 개인 일정을 찾아 삭제합니다."""

    return json.dumps(delete_schedule_by_query_dict(query), ensure_ascii=False)


def save_structured_request_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(save_structured_request.invoke({"payload": payload}))


def list_saved_request_dicts(
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    return json.loads(
        list_saved_requests.invoke({"kind": kind, "date_from": date_from, "date_to": date_to})
    )["rows"]


def week03_tools() -> list[Any]:
    """2주차까지의 도구에 SQLite 저장/조회/삭제 도구를 누적한 목록입니다."""

    return [
        *week02_tools(),
        save_structured_request,
        list_saved_requests,
        get_saved_request,
        personal_list_saved_schedules,
        personal_delete_saved_schedules,
        personal_delete_schedule_by_query,
    ]
