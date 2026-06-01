from __future__ import annotations

import json
from typing import Any

from langchain.tools import tool

from fixed.runtime_clock import next_weekday_iso
from fixed.stores import new_id, now_iso


PERSONAL_SCHEDULES: list[dict[str, Any]] = []


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _schedule_structured_request(schedule: dict[str, Any]) -> dict[str, Any]:
    """DB 저장 도구에 그대로 전달할 수 있는 일정 구조화 페이로드를 만듭니다."""

    return {
        "kind": "personal_schedule",
        "title": schedule["title"],
        "date": schedule["date"],
        "start_time": schedule["start_time"],
        "end_time": schedule["end_time"],
        "members": schedule["attendees"],
        "priority": None,
        "reason": "1주차 개인 일정 생성 도구가 DB 저장용 structured output으로 변환했습니다.",
        "original_text": schedule["title"],
        "source_schedule_id": schedule["id"],
    }


@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 생성하고 저장된 일정 페이로드를 반환합니다."""

    schedule = {
        "id": new_id("personal"),
        "owner": "me",
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees or [],
        "created_at": now_iso(),
    }
    PERSONAL_SCHEDULES.append(schedule)
    return _json(
        {
            "ok": True,
            "tool_name": "personal_create_schedule",
            "created_schedule": schedule,
            "structured_request": _schedule_structured_request(schedule),
        }
    )


@tool
def personal_list_schedules(date_from: str | None = None, date_to: str | None = None) -> str:
    """선택한 시작일과 종료일 범위에 포함되는 Nana의 개인 일정을 조회합니다."""

    schedules = [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if (not date_from or schedule["date"] >= date_from) and (not date_to or schedule["date"] <= date_to)
    ]
    return _json({"ok": True, "tool_name": "personal_list_schedules", "schedules": schedules})


@tool
def personal_delete_schedule(schedule_id: str) -> str:
    """일정 ID에 해당하는 개인 일정을 삭제합니다."""

    before = len(PERSONAL_SCHEDULES)
    PERSONAL_SCHEDULES[:] = [schedule for schedule in PERSONAL_SCHEDULES if schedule["id"] != schedule_id]
    deleted = len(PERSONAL_SCHEDULES) != before
    return _json(
        {
            "ok": True,
            "tool_name": "personal_delete_schedule",
            "schedule_id": schedule_id,
            "deleted": deleted,
        }
    )


def week01_tools() -> list[Any]:
    """1주차에서 직접 구현한 개인 일정 CRUD 도구 목록입니다."""

    return [personal_create_schedule, personal_list_schedules, personal_delete_schedule]


def list_personal_schedule_dicts(date_from: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
    """6주차 시간 후보 계산에서 사용하는 비-도구 헬퍼입니다."""

    schedules = json.loads(personal_list_schedules.invoke({"date_from": date_from, "date_to": date_to}))
    return schedules["schedules"]


def ensure_demo_personal_schedule() -> None:
    if PERSONAL_SCHEDULES:
        return
    personal_create_schedule.invoke(
        {
            "title": "개인 집중 작업",
            "date": next_weekday_iso(2),
            "start_time": "09:00",
            "end_time": "10:00",
            "attendees": [],
        }
    )
