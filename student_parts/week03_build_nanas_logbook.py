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


# [수강생 구현 가이드]
# Week 3의 학생 구현 대상은 @tool이 붙은 SQLite 저장/조회/수정/삭제 wrapper입니다.
# 복잡한 삭제/수정 helper는 참고 코드로 남겨 두고, tool의 입력/출력 JSON 계약에 집중하세요.


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
    # [수강생 참고 코드 포인트]
    # 자연어 삭제 요청은 먼저 Week 2 구조화 결과로 바꾸고, 그중 확실한 값만 삭제 필터로 사용합니다.
    # "전체/모두" 같은 표현은 별도 helper에서 bulk delete 의도로 판단합니다.
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

    # [수강생 구현 포인트]
    # payload가 JSON 문자열로 들어올 수도 있으니 dict로 정규화한 뒤 STORE.save_structured_request에 넘깁니다.
    # 반환 payload에는 저장소가 만든 request_id, saved_rows, kind 등이 포함됩니다.
    saved = STORE.save_structured_request(_coerce_payload(payload))
    return json.dumps({"ok": True, "tool_name": "save_structured_request", **saved}, ensure_ascii=False)


@tool
def list_saved_requests(
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """SQLite에 저장된 구조화 요청 목록을 조회합니다."""

    # [수강생 구현 포인트]
    # kind/date_from/date_to를 그대로 저장소 조회 조건으로 넘기고 rows 배열을 JSON으로 반환합니다.
    rows = STORE.list_saved_requests(kind=kind, date_from=date_from, date_to=date_to)
    return json.dumps({"ok": True, "tool_name": "list_saved_requests", "rows": rows}, ensure_ascii=False)


@tool
def get_saved_request(request_id: str) -> str:
    """request_id로 구조화 요청 행 하나를 조회합니다."""

    # [수강생 구현 포인트]
    # 단일 row 조회 tool입니다. 없는 id도 row=None 형태로 반환되게 두면 agent가 후속 판단을 할 수 있습니다.
    row = STORE.get_saved_request(request_id)
    return json.dumps({"ok": True, "tool_name": "get_saved_request", "row": row}, ensure_ascii=False)


@tool
def personal_list_saved_schedules(limit: int = 50) -> str:
    """앱 DB에 저장된 일정 목록을 반환합니다. Nana가 삭제 후보를 직접 고를 때 사용합니다."""

    # [수강생 구현 포인트]
    # 수정/삭제 전에 agent가 후보 schedule_id를 고를 수 있도록 저장된 일정 목록을 공개합니다.
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
    # [수강생 참고 코드 포인트]
    # 삭제는 위험한 작업이므로 schedule_ids/date/title/start_time 같은 필터가 없으면 실패 payload를 반환합니다.
    # delete_all=True일 때만 전체 삭제를 허용하고, 앱 DB와 Week 1 in-memory store를 함께 정리합니다.
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


def update_saved_schedule_dict(
    schedule_id: str,
    title: str | None = None,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    attendees: list[str] | None = None,
    app_store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    # [수강생 참고 코드 포인트]
    # 수정 대상은 저장된 앱 DB 일정의 schedule_id로 찾습니다.
    # store.update_schedule은 공유 일정 복사본 동기화 결과까지 반환하므로 updated_schedule/shared_sync를 그대로 노출합니다.
    store = app_store or AppSQLiteStore(CONFIG.app_db_path)
    updated = store.update_schedule(
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


@tool
def personal_update_saved_schedule(
    schedule_id: str,
    title: str | None = None,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    attendees: list[str] | None = None,
) -> str:
    """앱 DB에 저장된 내 일정 원본을 수정하고 공유 일정 복사본을 같은 값으로 갱신합니다."""

    # [수강생 구현 포인트]
    # @tool wrapper에서는 dict helper를 호출하고 JSON 문자열로 감싸는 일만 담당합니다.
    return json.dumps(
        update_saved_schedule_dict(
            schedule_id=schedule_id,
            title=title,
            date=date,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees,
        ),
        ensure_ascii=False,
    )


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

    # [수강생 구현 포인트]
    # agent가 고른 schedule_ids 또는 필터를 dict helper에 전달합니다.
    # 결과에는 deleted_count와 filters를 포함해 어떤 조건으로 삭제했는지 남겨야 합니다.
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
    # [수강생 참고 코드 포인트]
    # schedule_id가 없는 삭제 요청을 위한 편의 helper입니다.
    # 구조화 결과에서 필터를 만들고, 특정하지 못하면 agent가 목록 조회를 먼저 하도록 실패 reason을 반환합니다.
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

    # [수강생 구현 포인트]
    # 이 tool은 이전 하네스 호환용입니다. 핵심 흐름은 목록 조회 후 personal_delete_saved_schedules 호출입니다.
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

    # [수강생 참고 코드 포인트]
    # Week 1-2 tool을 유지하고, 저장/조회/수정/삭제 tool을 추가합니다.
    # prompt-driven agent는 이 목록에 들어간 tool만 호출할 수 있습니다.
    return [
        *week02_tools(),
        save_structured_request,
        list_saved_requests,
        get_saved_request,
        personal_list_saved_schedules,
        personal_update_saved_schedule,
        personal_delete_saved_schedules,
        personal_delete_schedule_by_query,
    ]
