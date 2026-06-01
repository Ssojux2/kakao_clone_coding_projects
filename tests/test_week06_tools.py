from __future__ import annotations

import json

import fixed.runtime_clock as runtime_clock
from student_parts.week06_kanamate_decides_schedule import (
    agent_tool_names,
    find_common_available_slots_dict,
    propose_group_schedule,
)


def test_week06_kana_tools_include_slot_decision_chain() -> None:
    kana_tools = set(agent_tool_names("kana_agent"))

    assert {"collect_member_schedules", "find_common_available_slots", "propose_group_schedule"} <= kana_tools


def test_week06_common_slots_feed_final_decision() -> None:
    target_day = runtime_clock.next_weekday_iso(1)
    slots = find_common_available_slots_dict(
        member_names=["A", "B", "C"],
        date_from=target_day,
        date_to=target_day,
        duration_minutes=60,
        limit=1,
    )["candidate_slots"]

    result = json.loads(
        propose_group_schedule.invoke(
            {
                "title": "팀 회의",
                "member_names": ["A", "B", "C"],
                "candidate_slots": slots,
                "selected_slot": slots[0],
                "reason": "첫 번째 공통 가능 시간",
            }
        )
    )

    assert result["final_decision"]["status"] == "confirmed"
    assert result["final_decision"]["selected_slot"] == slots[0]
