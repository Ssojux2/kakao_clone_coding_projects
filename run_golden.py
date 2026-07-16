from __future__ import annotations

import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from golden_cases import GOLDEN_CASES
from student_parts.week06_kanamate_decides_schedule import agent_tool_names


def main() -> int:
    supervisor_tools = set(agent_tool_names("supervisor"))
    subagent_tools = {
        "nana_agent": set(agent_tool_names("nana_agent")),
        "kana_agent": set(agent_tool_names("kana_agent")),
    }

    results = []
    for case in GOLDEN_CASES:
        expected_agent = case["expected_agent"]
        expected_tools = case.get("expected_tools") or [case["expected_tool"]]
        agent_ok = expected_agent in supervisor_tools
        tool_ok = set(expected_tools) <= subagent_tools[expected_agent]
        # tier=extra 케이스는 추가 과제 tool이 아직 등록되지 않았으면 실패 대신 skip으로 기록합니다.
        skipped_extra = case.get("tier") == "extra" and agent_ok and not tool_ok
        results.append(
            {
                "id": case["id"],
                "expected_agent": expected_agent,
                "supervisor_tools": sorted(supervisor_tools),
                "expected_tools": expected_tools,
                "subagent_tools": sorted(subagent_tools[expected_agent]),
                "skipped_extra": skipped_extra,
                "passed": agent_ok and (tool_ok or skipped_extra),
            }
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
