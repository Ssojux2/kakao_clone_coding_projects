from __future__ import annotations

"""Week 6 그룹 일정 조율에서 쓰는 시간 계산 함수 모음입니다.

모든 시간 비교는 `HH:MM` 문자열을 자정 기준 분 단위 정수로 바꿔 수행합니다.
이 모듈은 LangChain tool을 직접 알지 않고, 순수 payload 계산만 담당합니다.
"""

from datetime import date, timedelta
from typing import Any, Callable


def parse_time_minutes(value: str | None, fallback: int) -> int:
    """`HH:MM` 문자열을 자정 기준 분으로 변환합니다.

    값이 비어 있거나 `"미정"`이면 caller가 정한 fallback을 사용합니다.
    """

    if not value or value == "미정":
        return fallback
    try:
        hour_text, minute_text = value.split(":", 1)
        return int(hour_text) * 60 + int(minute_text)
    except (AttributeError, ValueError):
        return fallback


def format_time_minutes(minutes: int) -> str:
    """자정 기준 분 값을 `HH:MM` 문자열로 바꿉니다."""

    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def normalize_date_bound(value: str) -> str:
    """ISO datetime 또는 문자열에서 날짜 부분만 남깁니다."""

    return str(value).split("T", 1)[0].strip()


def date_range(date_from: str, date_to: str) -> list[str]:
    """양 끝 날짜를 포함하는 YYYY-MM-DD 목록을 반환합니다.

    범위가 거꾸로 들어와도 start/end를 바꿔 안전하게 계산합니다.
    """

    start = date.fromisoformat(normalize_date_bound(date_from))
    end = date.fromisoformat(normalize_date_bound(date_to))
    if end < start:
        start, end = end, start
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def busy_rows_overlap(rows: list[dict[str, Any]], day: str, start_minutes: int, end_minutes: int) -> list[dict[str, Any]]:
    """후보 시간과 겹치는 busy row 목록을 찾습니다."""

    blockers: list[dict[str, Any]] = []
    for row in rows:
        if row.get("date") != day:
            continue
        busy_start = parse_time_minutes(row.get("start_time"), 0)
        busy_end = parse_time_minutes(row.get("end_time"), 24 * 60)
        if start_minutes < busy_end and busy_start < end_minutes:
            blockers.append(row)
    return blockers


def slot_to_text(slot: Any) -> str:
    """후보 slot dict 또는 문자열을 사용자 답변용 시간 문자열로 바꿉니다."""

    if isinstance(slot, str):
        return slot
    if not isinstance(slot, dict):
        return str(slot)
    date_text = slot.get("date") or "날짜 미정"
    start_time = slot.get("start_time") or "시간 미정"
    end_time = slot.get("end_time")
    return f"{date_text} {start_time}-{end_time}" if end_time else f"{date_text} {start_time}"


def find_common_available_slots_payload(
    *,
    member_names: list[str],
    date_from: str,
    date_to: str,
    busy_rows: list[dict[str, Any]],
    duration_minutes: int = 60,
    workday_start: str = "09:00",
    workday_end: str = "18:00",
    limit: int = 5,
) -> dict[str, Any]:
    """busy row를 피해 공통 가능 시간 후보를 계산합니다.

    업무시간 범위를 30분 단위로 훑으면서 `duration_minutes` 길이의 slot을 만들고,
    누구의 busy row와도 겹치지 않는 후보만 `candidate_slots`에 담습니다.
    """

    start_minutes = parse_time_minutes(workday_start, 9 * 60)
    end_minutes = parse_time_minutes(workday_end, 18 * 60)
    duration = max(30, min(int(duration_minutes or 60), end_minutes - start_minutes))
    step = 30

    candidate_slots: list[dict[str, Any]] = []
    for day in date_range(date_from, date_to):
        cursor = start_minutes
        while cursor + duration <= end_minutes:
            slot_end = cursor + duration
            blockers = busy_rows_overlap(busy_rows, day, cursor, slot_end)
            if not blockers:
                candidate_slots.append(
                    {
                        "date": day,
                        "start_time": format_time_minutes(cursor),
                        "end_time": format_time_minutes(slot_end),
                        "duration_minutes": duration,
                        "reason": "수집된 busy-time과 겹치지 않는 공통 가능 시간입니다.",
                    }
                )
                if len(candidate_slots) >= limit:
                    return {
                        "ok": True,
                        "tool_name": "find_common_available_slots",
                        "members": member_names,
                        "busy_rows": busy_rows,
                        "candidate_slots": candidate_slots,
                    }
            cursor += step

    return {
        "ok": True,
        "tool_name": "find_common_available_slots",
        "members": member_names,
        "busy_rows": busy_rows,
        "candidate_slots": candidate_slots,
    }


def decide_final_slot_payload(
    *,
    candidate_slots: list[Any] | None = None,
    selected_slot: Any | None = None,
    selected_index: int | None = None,
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    duration_minutes: int = 60,
    reason: str | None = None,
    slot_finder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """후보 slot 목록과 LLM agent가 명시한 최종 선택을 payload로 만듭니다.

    후보가 없으면 `slot_finder`로 계산할 수 있지만, 최종 slot은 `selected_slot` 또는
    `selected_index`가 명시됐을 때만 채웁니다. 반환 payload는 agent 답변과 테스트가 공통으로
    쓰는 `final_slot`, `reason`, `candidates`, `needs_agent_selection`을 항상 포함합니다.
    """

    slots = list(candidate_slots or [])
    computed: dict[str, Any] | None = None
    if not slots and slot_finder and member_names and date_from and date_to:
        computed = slot_finder(
            member_names=member_names,
            date_from=date_from,
            date_to=date_to,
            duration_minutes=duration_minutes,
            limit=5,
        )
        slots = list(computed.get("candidate_slots") or [])

    selected = selected_slot
    invalid_selection = False
    if selected is None and selected_index is not None:
        try:
            index = int(selected_index)
        except (TypeError, ValueError):
            invalid_selection = True
        else:
            if 0 <= index < len(slots):
                selected = slots[index]
            else:
                invalid_selection = True

    candidates = [slot_to_text(slot) for slot in slots]
    final_slot = slot_to_text(selected) if selected else None
    if reason:
        final_reason = reason
    elif invalid_selection:
        final_reason = "선택한 후보 번호가 후보 목록 범위를 벗어났습니다."
    elif isinstance(selected, dict) and selected.get("reason"):
        final_reason = str(selected["reason"])
    elif selected:
        final_reason = "LLM agent가 후보 목록에서 명시적으로 선택한 시간입니다."
    elif candidates:
        final_reason = "후보는 계산됐지만 LLM agent가 최종 후보를 아직 명시적으로 선택하지 않았습니다."
    else:
        final_reason = "공통 가능 시간을 찾지 못했습니다."

    payload: dict[str, Any] = {
        "final_slot": final_slot,
        "reason": final_reason,
        "candidates": candidates,
        "needs_agent_selection": bool(candidates and selected is None),
    }
    if selected_index is not None:
        payload["selected_index"] = selected_index
    if selected is not None:
        payload["selected_slot"] = selected
    if computed:
        payload["members"] = computed.get("members")
        payload["busy_rows"] = computed.get("busy_rows", [])
        payload["candidate_slots"] = computed.get("candidate_slots", [])
    elif slots and any(isinstance(slot, dict) for slot in slots):
        payload["candidate_slots"] = slots
    return payload
