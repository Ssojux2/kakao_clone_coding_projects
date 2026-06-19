from __future__ import annotations

import ast
from pathlib import Path

from scripts.make_student_distribution import TODO_TARGETS


PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_HELPER_CALLS: dict[str, dict[str, set[str]]] = {
    "student_parts/week01_wake_up_nana.py": {
        "personal_create_schedule": {"_schedule_structured_request"},
    },
    "student_parts/week03_build_nanas_logbook.py": {
        "personal_update_saved_schedule": {"update_saved_schedule_dict"},
        "personal_delete_saved_schedules": {"delete_saved_schedules_dict"},
    },
    "student_parts/week04_retrieve_nanas_memory.py": {
        "add_personal_reference": {"_reference_backend_info"},
        "search_personal_references": {"_course_reference_hits", "_safe_limit"},
        "search_saved_requests": {"_safe_limit"},
    },
    "student_parts/week05_load_kanas_past_conversations.py": {
        "extract_schedules_from_history": {"_normalize_members"},
        "collect_member_schedules": {
            "_normalize_members",
            "list_personal_schedule_dicts",
            "extract_schedules_from_history_dict",
        },
    },
    "student_parts/week06_kanamate_decides_schedule.py": {
        "decide_final_slot": {"decide_final_slot_dict"},
        "nana_agent": {"build_nana_subagent"},
        "kana_agent": {"build_kana_subagent"},
    },
}


def _top_level_functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_student_todo_tools_do_not_wrap_forbidden_local_helpers() -> None:
    for relative_path, function_targets in TODO_TARGETS.items():
        forbidden_for_file = FORBIDDEN_HELPER_CALLS.get(relative_path, {})
        if not forbidden_for_file:
            continue

        tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
        functions = _top_level_functions(tree)

        for function_name in function_targets:
            forbidden = forbidden_for_file.get(function_name)
            if not forbidden:
                continue
            calls = {
                call_name
                for call in ast.walk(functions[function_name])
                if isinstance(call, ast.Call)
                for call_name in [_call_name(call)]
                if call_name
            }
            assert calls.isdisjoint(forbidden), (
                f"{relative_path}:{function_name} should be implemented in the tool body, "
                f"not by wrapping {sorted(calls & forbidden)}"
            )
