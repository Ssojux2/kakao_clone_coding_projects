from __future__ import annotations

import json

from student_parts.week01_wake_up_nana import (
    PERSONAL_SCHEDULES,
    personal_create_schedule,
    personal_delete_schedule,
    personal_list_schedules,
)


def test_week01_personal_schedule_crud_flow() -> None:
    PERSONAL_SCHEDULES.clear()

    created = json.loads(
        personal_create_schedule.invoke(
            {
                "title": "개인 집중 작업",
                "date": "2026-05-21",
                "start_time": "10:00",
                "end_time": "11:00",
                "attendees": ["나"],
            }
        )
    )
    schedule_id = created["created_schedule"]["id"]

    listed = json.loads(personal_list_schedules.invoke({"date_from": "2026-05-21", "date_to": "2026-05-21"}))
    deleted = json.loads(personal_delete_schedule.invoke({"schedule_id": schedule_id}))

    assert created["structured_request"]["kind"] == "personal_schedule"
    assert listed["schedules"][0]["title"] == "개인 집중 작업"
    assert deleted["deleted"] is True
