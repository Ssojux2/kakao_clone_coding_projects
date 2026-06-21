from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.app_store import AppSQLiteStore
from student_parts.week01_wake_up_nana import (
    join_system_prompt,
    personal_create_schedule as week01_personal_create_schedule,
    week01_tools,
)
from student_parts.week02_structure_natural_language_requests import (
    StructuredRequest,
    extract_schedule_request,
    extract_structured_request,
    week02_prompt_parts,
)


_WEEK03_AGENT: Any | None = None

SQLITE_MEMORY_PROMPT = (
    "Week 3 이상에서는 새 대화를 시작해도 앱 SQLite DB에 저장된 일정, 할 일, 알림은 사라지지 않는다. "
    "Week 3 이상에서 새 일정, 할 일, 알림을 만들 때는 Week 1의 인메모리 생성 도구가 아니라 "
    "구조화 결과를 SQLite 저장 도구에 바로 전달한다. "
    "사용자가 저장된 일정/할 일/알림을 묻거나 '내 일정 보여줘', '저장된 것 알려줘'처럼 요청하면 "
    "현재 채팅 전사나 Week 1-2 임시 메모리에 없다는 이유로 모른다고 답하지 말고 SQLite 조회 도구 결과를 근거로 답한다. "
    "personal_list_schedules 같은 Week 1 임시 조회 도구는 Week 1-2 단순 조회 전용이며 Week 3 이상에서는 SQLite 일정 조회 도구를 사용한다. "
    "대화 전사는 같은 conversation_id 안의 임시 맥락이고, SQLite row는 새 대화에서도 접근 가능한 저장 데이터다."
)


# [수강생 구현 가이드]
#
# 목표
#   Week 2에서 만든 structured_request를 SQLite에 저장하고 다시 조회/수정/삭제합니다.
#   여기서부터 Nana는 메모리 리스트가 아니라 앱 DB에 남는 "기록장"을 갖게 됩니다.
#
# 구현 위치와 사용할 코드
#   - 이 파일(student_parts/week03_build_nanas_logbook.py)의 SQLite tool 함수들을 구현합니다.
#   - 실제 DB 접근은 fixed/app_store.py의 AppSQLiteStore를 사용하고, 이 파일의 _store()가
#     CONFIG.app_db_path 기준 store 객체를 만들어 줍니다.
#   - dict/JSON 문자열/자연어 입력 정리는 coerce_payload(), normalize_structured_request_payload()를 사용합니다.
#   - save/list/get helper는 save_structured_request_payload(), list_saved_requests_payload(),
#     get_saved_request_payload()처럼 payload를 먼저 만드는 함수에 구현합니다.
#   - 일정 목록/수정/삭제는 list_saved_schedules_payload(), update_saved_schedule_payload(),
#     delete_saved_schedules_payload()에서 AppSQLiteStore.list_schedules/update_schedule/delete_* 메서드를 호출합니다.
#   - 자연어 구조화는 student_parts/week02_structure_natural_language_requests.py의
#     extract_schedule_request tool 또는 extract_structured_request() helper를 사용합니다.
#   - Week 3부터 SQLite 저장은 normalize_structured_request_payload()를 거쳐
#     StructuredRequest 스키마로 정리한 payload만 AppSQLiteStore.save_structured_request(...)에 전달합니다.
#   - Week 1 호환 personal_create_schedule은 week01_personal_create_schedule과
#     structured_request_from_week01_schedule()을 거쳐 SQLite 저장 payload로 변환합니다.
#
# 구현 대상
#   1. save_structured_request
#      - payload가 dict, JSON 문자열, 자연어 문자열로 들어올 수 있으므로 coerce_payload로 먼저 정리합니다.
#      - extract_schedule_request의 전체 tool 결과가 들어오면 payload["structured_request"]만 꺼내 저장합니다.
#      - kind가 없는 자연어 입력이면 extract_structured_request(payload)를 호출해 StructuredRequest로 정리합니다.
#      - StructuredRequest.model_validate(...)로 저장 직전 스키마를 한 번 더 검증한 뒤
#        현재 CONFIG.app_db_path의 SQLite DB에 저장합니다.
#      - 저장 결과의 request_id, kind, saved_rows를 ok/tool_name과 함께 JSON으로 반환합니다.
#
#   2. list_saved_requests / get_saved_request
#      - list는 kind/date_from/date_to 필터를 조회 helper에 그대로 넘깁니다.
#      - get은 request_id 하나로 단건 조회 helper를 호출합니다.
#      - 조회 결과가 없어도 예외를 던지지 말고 rows=[] 또는 row=None 형태를 유지합니다.
#
#   3. personal_list_saved_schedules
#      - 수정/삭제 전에 agent가 후보 schedule_id를 볼 수 있게 저장된 일정 목록을 반환합니다.
#      - 날짜가 명확한 조회는 date_from/date_to로 범위를 좁힙니다.
#      - 너무 많은 row가 prompt에 들어가지 않도록 limit 인자를 그대로 사용합니다.
#
#   4. personal_update_saved_schedule
#      - AppSQLiteStore.update_schedule(...) 결과를 이 tool 안에서 JSON payload로 완성합니다.
#      - None으로 들어온 필드는 "수정하지 않음"이라는 뜻입니다.
#
#   5. personal_delete_saved_schedules
#      - schedule_ids, date, title, start_time, time_unspecified, delete_all 조건을 받습니다.
#      - 조건 없이 삭제하지 않도록 이 tool 안에서 안전 규칙을 확인합니다.
#      - deleted_count, filters, deleted를 유지해야 trace에서 무엇이 지워졌는지 확인할 수 있습니다.
#
# 반환 규칙
#   모든 @tool은 JSON 문자열을 반환합니다.
#   ok와 tool_name은 기본으로 넣고, 조회는 rows/row, 삭제는 deleted_count/filters/deleted를 유지하세요.
#
# 참고 코드
#   week03_tools()는 Week 1-2 도구에 SQLite 도구를 누적해 공개합니다.
#   삭제 요청은 먼저 personal_list_saved_schedules로 후보를 확인한 뒤
#   personal_delete_saved_schedules에 schedule_ids 또는 명시 필터를 넘기는 흐름으로 처리합니다.
#
# 검증 방법
#   ./run.sh --week3에서 "내일 10시 개인 코칭 저장해줘"처럼 입력합니다.
#   trace에서 extract_schedule_request 이후 save_structured_request가 호출되는지 봅니다.
#   조회/수정/삭제 요청에서는 먼저 후보를 조회하고, ID 또는 필터 기반 tool로 이어지는지 확인합니다.


def _store() -> AppSQLiteStore:
    return AppSQLiteStore(CONFIG.app_db_path)


def _tool_name(item: Any) -> str:
    return getattr(item, "name", getattr(item, "__name__", str(item)))


def json_payload(payload: dict[str, Any]) -> str:
    """도구 반환용 dict를 한글이 깨지지 않는 JSON 문자열로 변환합니다."""

    return json.dumps(payload, ensure_ascii=False)


def coerce_payload(payload: dict[str, Any] | str) -> dict[str, Any] | str:
    """dict, JSON 문자열, 자연어 문자열 payload를 저장 전 단계 값으로 맞춥니다."""

    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return payload
        return decoded if isinstance(decoded, dict) else payload
    return payload


def normalize_structured_request_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    """SQLite 저장 전 입력을 StructuredRequest 스키마 기준 payload로 정리합니다."""

    coerced = coerce_payload(payload)
    if isinstance(coerced, str):
        return extract_structured_request(coerced).model_dump()

    raw_payload = coerced.get("structured_request")
    if isinstance(raw_payload, dict):
        source = raw_payload
    elif "kind" not in coerced and isinstance(coerced.get("query") or coerced.get("text"), str):
        return extract_structured_request(str(coerced.get("query") or coerced.get("text"))).model_dump()
    else:
        source = coerced

    structured = StructuredRequest.model_validate(source).model_dump()
    source_schedule_id = source.get("source_schedule_id")
    if source_schedule_id:
        structured["source_schedule_id"] = source_schedule_id
    return structured


def save_structured_request_payload(
    payload: dict[str, Any] | str,
    *,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """입력을 StructuredRequest payload로 정리한 뒤 앱 DB에 저장합니다."""

    selected_store = store or _store()
    structured_payload = normalize_structured_request_payload(payload)
    saved = selected_store.save_structured_request(structured_payload)
    return {"ok": True, "tool_name": "save_structured_request", **saved}


def list_saved_requests_payload(
    *,
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """저장된 structured request 목록을 조회하는 tool payload를 만듭니다."""

    selected_store = store or _store()
    rows = selected_store.list_saved_requests(kind=kind, date_from=date_from, date_to=date_to)
    return {"ok": True, "tool_name": "list_saved_requests", "rows": rows}


def get_saved_request_payload(request_id: str, *, store: AppSQLiteStore | None = None) -> dict[str, Any]:
    """request_id 하나로 저장 요청을 조회하는 tool payload를 만듭니다."""

    selected_store = store or _store()
    return {"ok": True, "tool_name": "get_saved_request", "row": selected_store.get_saved_request(request_id)}


def list_saved_schedules_payload(
    limit: int = 50,
    *,
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    store: AppSQLiteStore | None = None,
) -> dict[str, Any]:
    """수정/삭제 후보로 보여 줄 저장 일정 목록 payload를 만듭니다."""

    selected_store = store or _store()
    effective_kind = kind or "personal_schedule"
    return {
        "ok": True,
        "tool_name": "personal_list_saved_schedules",
        "filters": {
            "kind": effective_kind,
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
        },
        "schedules": selected_store.list_schedules(
            limit=limit,
            kind=effective_kind,
            date_from=date_from,
            date_to=date_to,
        ),
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
    """저장 일정 하나를 수정하고 성공/실패 tool payload를 반환합니다."""

    selected_store = store or _store()
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
    """필터에 맞는 저장 일정을 삭제하는 tool payload를 만듭니다."""

    selected_store = store or _store()
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


def structured_request_from_week01_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    """Week 1 임시 일정 dict를 Week 3 SQLite 저장 payload로 변환합니다."""

    attendees = schedule.get("attendees") or []
    return {
        "kind": "personal_schedule",
        "title": schedule.get("title"),
        "date": schedule.get("date"),
        "start_time": schedule.get("start_time"),
        "end_time": schedule.get("end_time"),
        "members": attendees,
        "priority": None,
        "reason": "Week 3 personal_create_schedule 호환 도구가 Week 1 임시 일정을 저장 payload로 변환했습니다.",
        "original_text": schedule.get("title") or "",
        "source_schedule_id": schedule.get("id"),
    }


@tool("personal_create_schedule")
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 생성하고 Week 3+ 앱 SQLite DB에도 저장합니다."""

    created = json.loads(
        week01_personal_create_schedule.invoke(
            {
                "title": title,
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
                "attendees": attendees,
            }
        )
    )
    structured_request = structured_request_from_week01_schedule(created["created_schedule"])
    saved = save_structured_request_payload(structured_request, store=_store())
    return json_payload(
        {
            **created,
            "structured_request": structured_request,
            "sqlite_save": saved,
        }
    )


@tool
def save_structured_request(payload: dict[str, Any] | str) -> str:
    """입력을 StructuredRequest로 정리한 뒤 정규화된 SQLite 테이블에 저장합니다."""

    return json_payload(save_structured_request_payload(coerce_payload(payload), store=_store()))


@tool
def list_saved_requests(
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """SQLite에 저장된 구조화 요청 목록을 조회합니다."""

    return json_payload(
        list_saved_requests_payload(kind=kind, date_from=date_from, date_to=date_to, store=_store())
    )


@tool
def get_saved_request(request_id: str) -> str:
    """request_id로 구조화 요청 행 하나를 조회합니다."""

    return json_payload(get_saved_request_payload(request_id, store=_store()))


@tool
def personal_list_saved_schedules(
    limit: int = 50,
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """앱 DB에 저장된 일정 목록을 날짜/종류 필터로 반환합니다. Nana가 조회/수정/삭제 후보를 볼 때 사용합니다."""

    return json_payload(
        list_saved_schedules_payload(
            limit=limit,
            kind=kind,
            date_from=date_from,
            date_to=date_to,
            store=_store(),
        )
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
    return delete_saved_schedules_payload(
        schedule_ids=schedule_ids,
        date=date,
        title=title,
        start_time=start_time,
        time_unspecified=time_unspecified,
        delete_all=delete_all,
        store=app_store or _store(),
    )


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

    return json_payload(
        update_saved_schedule_payload(
            schedule_id=schedule_id,
            title=title,
            date=date,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees,
            store=_store(),
        )
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

    return json_payload(
        delete_saved_schedules_payload(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
            delete_all=delete_all,
            store=_store(),
        )
    )


def week03_tools() -> list[Any]:
    """Week 1 도구, Week 2 구조화 helper, SQLite 저장/조회/삭제 도구를 조립합니다."""

    base_tools = [
        personal_create_schedule if _tool_name(item) == "personal_create_schedule" else item for item in week01_tools()
    ]
    return [
        *base_tools,
        extract_schedule_request,
        save_structured_request,
        list_saved_requests,
        get_saved_request,
        personal_list_saved_schedules,
        personal_update_saved_schedule,
        personal_delete_saved_schedules,
    ]


def week03_system_prompt() -> str:
    """3주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return join_system_prompt(week03_prompt_parts())


def week03_prompt_parts() -> list[str]:
    """1~3주차 system prompt 조각을 누적합니다."""

    return [
        *week02_prompt_parts(),
        "Week 2 요청 구조화 agent는 대화를 StructuredRequest로 직접 반환해 구조화 결과를 확인했다. "
        "Week 3부터는 최종 답변은 자연어로 작성하되, 새 일정/할 일/알림 저장 요청은 "
        "extract_schedule_request tool 결과의 structured_request를 SQLite 저장 도구에 넘긴다.",
        SQLITE_MEMORY_PROMPT,
        "너는 Kanana의 Week 3 Nana logbook agent다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "사용자의 자연어 요청은 필요하면 extract_schedule_request로 구조화한다. "
        "Week 3부터는 SQLite 저장 도구가 있으므로 새 일정, 할 일, 알림 생성은 "
        "personal_create_schedule을 거치지 않고 extract_schedule_request 결과의 structured_request를 "
        "바로 save_structured_request에 전달한다. "
        "저장된 요청 조회는 list_saved_requests/get_saved_request를 사용한다. "
        "저장된 일정 목록이나 내 일정 조회 요청은 personal_list_saved_schedules로 앱 SQLite 일정 row를 확인한다. "
        "특정 날짜나 기간을 묻는 조회는 date_from/date_to를 YYYY-MM-DD로 채워 후보를 좁힌다. "
        "personal_list_schedules는 Week 1-2 현재 대화 임시 메모리 조회 전용이므로 Week 3의 단순 일정 조회에는 사용하지 않는다. "
        "새 대화에서 이전에 저장한 중요한 일정/할 일/알림을 참고해야 할 때는 대화 전사가 아니라 SQLite 조회 도구 결과만 근거로 삼는다. "
        "저장 일정 수정/삭제는 personal_list_saved_schedules로 후보를 확인한 뒤 "
        "personal_update_saved_schedule 또는 personal_delete_saved_schedules를 사용한다. "
        "Week 3에서는 개인 RAG와 외부 멤버 일정 조율을 처리하지 않는다. "
        "도구 결과에 없는 사실은 만들지 않는다."
    ]


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
