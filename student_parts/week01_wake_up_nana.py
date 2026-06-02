from __future__ import annotations

import json
from typing import Any

from langchain.tools import tool

from fixed.runtime_clock import next_weekday_iso
from fixed.stores import new_id, now_iso


PERSONAL_SCHEDULES: list[dict[str, Any]] = []


# [수강생 구현 가이드]
# Week 1의 핵심 실습은 아래 3개의 @tool 함수입니다.
# LangChain tool은 문자열을 반환하는 것이 가장 안전하므로, 모든 결과는 dict를 만든 뒤 JSON 문자열로 감싸세요.
# 이후 Week 3 저장 도구가 바로 사용할 수 있도록 생성 tool은 structured_request도 함께 반환해야 합니다.


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _schedule_structured_request(schedule: dict[str, Any]) -> dict[str, Any]:
    """DB 저장 도구에 그대로 전달할 수 있는 일정 구조화 페이로드를 만듭니다."""

    # [수강생 참고 코드 포인트]
    # personal_create_schedule에서 만든 schedule dict를 Week 3의 save_structured_request payload 모양으로 바꿉니다.
    # kind/title/date/start_time/end_time/members는 저장소가 정규화할 때 직접 읽는 필드라 이름을 맞춰야 합니다.
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

    # [수강생 구현 포인트]
    # 1. 입력 인자를 하나의 schedule dict로 묶습니다.
    # 2. new_id()/now_iso()로 id와 생성 시각을 채웁니다.
    # 3. PERSONAL_SCHEDULES에 append한 뒤 created_schedule과 structured_request를 함께 반환합니다.
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

    # [수강생 구현 포인트]
    # date_from/date_to가 없으면 해당 조건은 건너뛰고, 있으면 YYYY-MM-DD 문자열 비교로 범위를 필터링합니다.
    # 반환 payload에는 tool_name과 schedules 배열이 반드시 들어가야 trace와 테스트에서 읽을 수 있습니다.
    schedules = [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if (not date_from or schedule["date"] >= date_from) and (not date_to or schedule["date"] <= date_to)
    ]
    return _json({"ok": True, "tool_name": "personal_list_schedules", "schedules": schedules})


@tool
def personal_delete_schedule(schedule_id: str) -> str:
    """일정 ID에 해당하는 개인 일정을 삭제합니다."""

    # [수강생 구현 포인트]
    # 삭제 전후 길이를 비교하면 실제 삭제 여부를 bool로 만들 수 있습니다.
    # 리스트 객체 자체는 유지해야 다른 import 지점에서도 같은 in-memory store를 바라봅니다.
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

    # [수강생 참고 코드 포인트]
    # Agent에게 공개할 tool만 이 목록에 넣습니다. Week 2 이후 파일들은 이 목록을 누적해서 사용합니다.
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
