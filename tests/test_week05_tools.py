from __future__ import annotations

import json

import student_parts.week05_load_kanas_past_conversations as week05_module


def test_week05_external_history_tools_return_member_schedules() -> None:
    conversations = json.loads(
        week05_module.search_previous_conversations.invoke({"query": "다음 주", "member_names": ["민준"], "limit": 3})
    )
    schedules = json.loads(
        week05_module.extract_schedules_from_history.invoke(
            {"member_names": ["민준", "서연", "지훈"], "date_from": "2000-01-01", "date_to": "2999-12-31"}
        )
    )

    assert conversations["rows"][0]["member_name"] == "민준"
    assert {row["member_name"] for row in schedules["rows"]} == {"민준", "서연", "지훈"}


def test_week05_collect_member_schedules_normalizes_aliases() -> None:
    result = json.loads(
        week05_module.collect_member_schedules.invoke(
            {"member_names": ["A", "B", "C"], "date_from": "2000-01-01", "date_to": "2999-12-31"}
        )
    )

    assert result["members"] == ["나", "민준", "서연", "지훈"]
    assert {row["member_name"] for row in result["rows"] if row["member_name"] != "나"} == {"민준", "서연", "지훈"}
