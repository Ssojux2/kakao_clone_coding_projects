from __future__ import annotations

import json

import pytest

import student_parts.week02_structure_natural_language_requests as week02_module
from fixed.config import CONFIG


@pytest.mark.integration
def test_week02_extract_schedule_request_uses_real_openai_structured_output() -> None:
    assert CONFIG.has_openai_key, "Week 2는 실제 structured output 호출이 필요합니다. .env에 PROXY_TOKEN을 설정하세요."

    result = json.loads(
        week02_module.extract_schedule_request.invoke(
            {"query": "2026-05-21 오전 10시에 개인 집중 작업 일정을 1시간 잡아줘"}
        )
    )
    structured = result["structured_request"]

    assert result["tool_name"] == "extract_schedule_request"
    assert structured["kind"] == "personal_schedule"
    assert structured["date"] == "2026-05-21"
    assert structured["start_time"] == "10:00"
    assert "개인" in structured["title"] or "집중" in structured["title"]
