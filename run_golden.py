from __future__ import annotations

import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from golden_cases import GOLDEN_CASES
from student_parts.week06_kanamate_decides_schedule import (
    agent_tool_names,
    kana_system_prompt,
    nana_system_prompt,
    supervisor_system_prompt,
)


def main() -> int:
    supervisor_tools = set(agent_tool_names("supervisor"))
    subagent_prompts = {
        "nana_agent": nana_system_prompt(),
        "kana_agent": kana_system_prompt(),
    }
    subagent_tools = {
        "nana_agent": set(agent_tool_names("nana_agent")),
        "kana_agent": set(agent_tool_names("kana_agent")),
    }
    supervisor_prompt = supervisor_system_prompt()

    results = []
    for case in GOLDEN_CASES:
        expected_agent = case["expected_agent"]
        expected_tools = case.get("expected_tools") or [case["expected_tool"]]
        prompt = case["input"]
        agent_ok = expected_agent in supervisor_tools
        tool_ok = set(expected_tools) <= subagent_tools[expected_agent]
        prompt_ok = prompt in supervisor_prompt and prompt in subagent_prompts[expected_agent]
        results.append(
            {
                "id": case["id"],
                "expected_agent": expected_agent,
                "supervisor_tools": sorted(supervisor_tools),
                "expected_tools": expected_tools,
                "subagent_tools": sorted(subagent_tools[expected_agent]),
                "prompt_in_supervisor": prompt in supervisor_prompt,
                "prompt_in_subagent": prompt in subagent_prompts[expected_agent],
                "passed": agent_ok and tool_ok and prompt_ok,
            }
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
