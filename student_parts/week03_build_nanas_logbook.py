from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.stores import AppSQLiteStore
from student_parts.week02_structure_natural_language_requests import extract_structured_request, week02_tools


STORE = AppSQLiteStore(CONFIG.app_db_path)
_WEEK03_AGENT: Any | None = None


# [수강생 구현 가이드]
#
# 목표
#   Week 2에서 만든 structured_request를 SQLite에 저장하고 다시 조회/수정/삭제합니다.
#   여기서부터 Nana는 메모리 리스트가 아니라 앱 DB에 남는 "기록장"을 갖게 됩니다.
#
# 구현 대상
#   1. save_structured_request
#      - payload가 dict 또는 JSON 문자열로 들어올 수 있으므로 _coerce_payload로 dict로 맞춥니다.
#      - STORE.save_structured_request(payload)를 호출합니다.
#      - 저장 결과의 request_id, kind, saved_rows를 ok/tool_name과 함께 JSON으로 반환합니다.
#
#   2. list_saved_requests / get_saved_request
#      - list는 kind/date_from/date_to 필터를 STORE.list_saved_requests에 그대로 넘깁니다.
#      - get은 request_id 하나로 STORE.get_saved_request를 호출합니다.
#      - 조회 결과가 없어도 예외를 던지지 말고 rows=[] 또는 row=None 형태를 유지합니다.
#
#   3. personal_list_saved_schedules
#      - 수정/삭제 전에 agent가 후보 schedule_id를 볼 수 있게 저장된 일정 목록을 반환합니다.
#      - 너무 많은 row가 prompt에 들어가지 않도록 limit 인자를 그대로 사용합니다.
#
#   4. personal_update_saved_schedule
#      - update_saved_schedule_dict(...) helper를 호출하고 그 dict를 JSON 문자열로 감쌉니다.
#      - None으로 들어온 필드는 "수정하지 않음"이라는 뜻입니다.
#
#   5. personal_delete_saved_schedules
#      - schedule_ids, date, title, start_time, time_unspecified, delete_all 조건을 받습니다.
#      - 조건 없이 삭제하지 않도록 helper의 안전 규칙을 그대로 사용합니다.
#      - deleted_count, filters, deleted를 유지해야 trace에서 무엇이 지워졌는지 확인할 수 있습니다.
#
# 반환 규칙
#   모든 @tool은 JSON 문자열을 반환합니다.
#   ok와 tool_name은 기본으로 넣고, 조회는 rows/row, 삭제는 deleted_count/filters/deleted를 유지하세요.
#
# 참고 코드
#   week03_tools()는 Week 1-2 도구에 SQLite 도구를 누적해 공개합니다.
#   personal_delete_schedule_by_query는 기존 하네스 호환 helper라서 학생 핵심 구현 대상이 아닙니다.
#
# 검증 방법
#   ./run.sh --week3에서 "내일 10시 개인 코칭 저장해줘"처럼 입력합니다.
#   trace에서 extract_schedule_request 이후 save_structured_request가 호출되는지 봅니다.
#   조회/수정/삭제 요청에서는 먼저 후보를 조회하고, ID 또는 필터 기반 tool로 이어지는지 확인합니다.


def _coerce_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


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
    # JSON 문자열이 아니라 dict 결과가 필요한 내부 호출과 테스트에서 재사용하는 버전입니다.
    # tool wrapper와 같은 payload 계약을 유지하면서 입력 검증, 삭제, 결과 생성을 한곳에서 수행합니다.
    store = app_store or AppSQLiteStore(CONFIG.app_db_path)
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
        app_deleted = store.delete_all_schedules()
    else:
        app_deleted = store.delete_schedules_by_filter(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
        )
    deleted = [{"source": "app_db", "schedule": row} for row in app_deleted]

    return {
        "ok": bool(deleted),
        "tool_name": "personal_delete_saved_schedules",
        "delete_all": delete_all,
        "bulk_delete": bool(not delete_all and deleted),
        "deleted_count": len(deleted),
        "filters": filters,
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

    store = AppSQLiteStore(CONFIG.app_db_path)
    filters = {
        "schedule_ids": schedule_ids,
        "date": date,
        "title": title,
        "start_time": start_time,
        "time_unspecified": time_unspecified,
    }
    has_filter = schedule_ids is not None or any([date, title, start_time, time_unspecified])

    if not delete_all and not has_filter:
        return json.dumps(
            {
                "ok": False,
                "tool_name": "personal_delete_saved_schedules",
                "reason": "삭제할 일정 ID나 날짜/제목/시간 필터가 필요합니다.",
                "delete_all": False,
                "bulk_delete": False,
                "deleted_count": 0,
                "filters": filters,
                "deleted": [],
            },
            ensure_ascii=False,
        )

    if delete_all:
        deleted_rows = store.delete_all_schedules()
    else:
        deleted_rows = store.delete_schedules_by_filter(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
        )
    deleted = [{"source": "app_db", "schedule": row} for row in deleted_rows]

    return json.dumps(
        {
            "ok": bool(deleted),
            "tool_name": "personal_delete_saved_schedules",
            "delete_all": delete_all,
            "bulk_delete": bool(not delete_all and deleted),
            "deleted_count": len(deleted),
            "filters": filters,
            "deleted": deleted,
        },
        ensure_ascii=False,
    )


def delete_schedule_by_query_dict(query: str, app_store: AppSQLiteStore | None = None) -> dict[str, Any]:
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
    result = delete_saved_schedules_dict(app_store=app_store, **filters)
    result["tool_name"] = "personal_delete_schedule_by_query"
    result["structured_request"] = structured
    if not result["ok"] and not filters:
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
        personal_update_saved_schedule,
        personal_delete_saved_schedules,
        personal_delete_schedule_by_query,
    ]


def week03_system_prompt() -> str:
    """3주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return (
        "너는 Kanana의 Week 3 Nana logbook agent다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "사용자의 자연어 요청은 필요하면 extract_schedule_request로 구조화한다. "
        "새 일정, 할 일, 알림을 저장해야 하면 structured_request를 save_structured_request에 전달한다. "
        "저장된 요청 조회는 list_saved_requests/get_saved_request를 사용한다. "
        "저장 일정 수정/삭제는 personal_list_saved_schedules로 후보를 확인한 뒤 "
        "personal_update_saved_schedule 또는 personal_delete_saved_schedules를 사용한다. "
        "Week 3에서는 개인 RAG와 외부 멤버 일정 조율을 처리하지 않는다. "
        "도구 결과에 없는 사실은 만들지 않는다."
    )


def build_week03_agent() -> object:
    """Week 1-3 누적 tool 목록을 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK03_AGENT
    if _WEEK03_AGENT is None:
        _WEEK03_AGENT = create_agent(
            model=chat_model(),
            tools=week03_tools(),
            system_prompt=week03_system_prompt(),
        )
    return _WEEK03_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week03_agent()
