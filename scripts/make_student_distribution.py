from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = PROJECT_ROOT / "dist" / "kanana_student"

EXCLUDED_NAMES = {
    ".git",
    ".env",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "data",
    "dist",
}

TODO_TARGETS: dict[str, dict[str, str]] = {
    "student_parts/week01_wake_up_nana.py": {
        "personal_create_schedule": "Week 1: 개인 일정 생성 payload를 만들고 in-memory store에 저장하세요.",
        "personal_list_schedules": "Week 1: date_from/date_to 조건으로 개인 일정을 필터링하세요.",
        "personal_delete_schedule": "Week 1: schedule_id가 일치하는 일정을 삭제하고 결과 payload를 반환하세요.",
    },
    "student_parts/week02_structure_natural_language_requests.py": {
        "extract_schedule_request": "Week 2: structured output 결과를 일정 앱용 JSON tool payload로 감싸세요.",
    },
    "student_parts/week03_build_nanas_logbook.py": {
        "save_structured_request": "Week 3: 2주차 structured payload를 SQLite 저장소에 저장하는 tool을 구현하세요.",
        "list_saved_requests": "Week 3: kind/date_from/date_to 필터로 저장 요청을 조회하세요.",
        "get_saved_request": "Week 3: request_id 하나로 저장 요청 row를 조회하세요.",
        "personal_list_saved_schedules": "Week 3: 저장된 일정 후보 목록을 조회하는 tool을 구현하세요.",
        "personal_update_saved_schedule": "Week 3: 이 tool 안에서 저장 일정 수정 payload를 완성하세요.",
        "personal_delete_saved_schedules": "Week 3: 이 tool 안에서 저장 일정 삭제 payload를 완성하세요.",
    },
    "student_parts/week04_retrieve_nanas_memory.py": {
        "add_personal_reference": "Week 4: 개인 참고자료를 ChromaDB에 저장하세요.",
        "search_personal_references": "Week 4: ChromaDB 개인 참고자료 검색 결과를 hits payload로 반환하세요.",
        "search_saved_requests": "Week 4: SQLite 저장 요청 검색 결과를 rows payload로 반환하세요.",
    },
    "student_parts/week05_load_kanas_past_conversations.py": {
        "search_previous_conversations": "Week 5: 외부 SQLite/MCP 대화 검색 tool을 구현하세요.",
        "load_conversation_messages": "Week 5: conversation_id로 이전 대화 메시지를 시간순 조회하세요.",
        "extract_schedules_from_history": "Week 5: 멤버와 날짜 범위로 외부 일정 row를 추출하세요.",
        "create_shared_schedule": "Week 5: 외부 MCP 공유 일정 생성/갱신 tool wrapper를 구현하세요.",
        "delete_shared_schedule": "Week 5: 외부 MCP 공유 일정 삭제 tool wrapper를 구현하세요.",
        "list_shared_schedules": "Week 5: 외부 MCP 공유 일정 조회 tool wrapper를 구현하세요.",
        "collect_member_schedules": "Week 5: 내 일정과 외부 멤버 일정을 그룹 조율용 busy-time으로 합치세요.",
    },
    "student_parts/week06_kanamate_decides_schedule.py": {
        "decide_final_slot": "Week 6: 선택된 후보 시간을 final_slot payload로 포장하세요.",
        "nana_agent": "Week 6: supervisor가 위임한 개인 일정 요청을 Nana sub-agent로 실행하세요.",
        "kana_agent": "Week 6: supervisor가 위임한 그룹 일정 요청을 Kana sub-agent로 실행하세요.",
    },
}

TODO_STEPS: dict[str, dict[str, list[str]]] = {
    "student_parts/week01_wake_up_nana.py": {
        "personal_create_schedule": [
            "title/date/start_time/end_time/attendees로 schedule dict를 만드세요.",
            'id는 new_id("personal"), created_at은 now_iso()로 채우세요.',
            "PERSONAL_SCHEDULES에 append한 뒤 structured_request를 함께 반환하세요.",
        ],
        "personal_list_schedules": [
            "PERSONAL_SCHEDULES를 순회하며 date_from/date_to 조건을 적용하세요.",
            "원본 리스트는 수정하지 말고 필터링된 schedules만 payload에 담으세요.",
        ],
        "personal_delete_schedule": [
            "삭제 전 PERSONAL_SCHEDULES 길이를 저장하세요.",
            "schedule_id가 다른 항목만 남기도록 PERSONAL_SCHEDULES[:]를 갱신하세요.",
            "삭제 전후 길이를 비교해 deleted 값을 payload에 담으세요.",
        ],
    },
    "student_parts/week02_structure_natural_language_requests.py": {
        "extract_schedule_request": [
            "query를 extract_structured_request(query)에 전달하세요.",
            "StructuredRequest 객체를 model_dump()로 dict로 바꾸세요.",
            "ok/tool_name/base_date/structured_request를 JSON 문자열로 반환하세요.",
        ],
    },
    "student_parts/week03_build_nanas_logbook.py": {
        "save_structured_request": [
            "coerce_payload로 dict payload를 준비하세요.",
            "save_structured_request_payload 또는 STORE 저장 API로 저장하세요.",
            "저장 결과를 ok/tool_name과 함께 JSON 문자열로 반환하세요.",
        ],
        "list_saved_requests": [
            "kind/date_from/date_to 필터를 조회 helper에 그대로 넘기세요.",
            "조회 결과는 rows 배열로 유지하세요.",
        ],
        "get_saved_request": [
            "request_id 하나로 저장 요청 row를 조회하세요.",
            "결과가 없어도 row=None payload를 반환하세요.",
        ],
        "personal_list_saved_schedules": [
            "수정/삭제 후보를 볼 수 있게 저장 일정 목록을 조회하세요.",
            "limit 값을 조회 helper에 전달하고 schedules 배열을 반환하세요.",
        ],
        "personal_update_saved_schedule": [
            "schedule_id와 None이 아닌 수정 필드를 update helper에 전달하세요.",
            "updated_schedule/shared_sync payload를 JSON 문자열로 반환하세요.",
        ],
        "personal_delete_saved_schedules": [
            "schedule_ids/date/title/start_time/delete_all 조건을 delete helper에 전달하세요.",
            "조건 없는 삭제는 실패 payload가 되도록 안전 규칙을 유지하세요.",
            "deleted_count/filters/deleted를 JSON 문자열로 반환하세요.",
        ],
    },
    "student_parts/week04_retrieve_nanas_memory.py": {
        "add_personal_reference": [
            "title/content/tags를 reference 저장 helper에 넘기세요.",
            "tags가 None이면 빈 list처럼 처리되게 하세요.",
            "reference_backend와 reference를 payload에 담으세요.",
        ],
        "search_personal_references": [
            "query/top_k로 개인 참고자료 검색 helper를 호출하세요.",
            "검색 결과는 top-level hits 배열로 반환하세요.",
        ],
        "search_saved_requests": [
            "query/top_k로 SQLite 저장 요청 검색 helper를 호출하세요.",
            "검색 결과는 top-level rows 배열로 반환하세요.",
        ],
    },
    "student_parts/week05_load_kanas_past_conversations.py": {
        "search_previous_conversations": [
            'call_mcp_tool_sync("search_previous_conversations", args)를 호출하세요.',
            "멤버 이름 정규화는 외부 SQLite store/MCP 경계에 맡기세요.",
            "MCP 결과 JSON 문자열을 그대로 반환하세요.",
        ],
        "load_conversation_messages": [
            "conversation_id로 이전 대화 메시지를 조회하세요.",
            "speaker/content/created_at 순서를 보존해 rows로 반환하세요.",
        ],
        "extract_schedules_from_history": [
            'call_mcp_tool_sync("extract_schedules_from_history", args)를 호출하세요.',
            "멤버 이름과 수업 fixture 날짜 범위 보정은 외부 SQLite store/MCP 경계에 맡기세요.",
            "rows와 schedule_summary가 있는 MCP 결과를 반환하세요.",
        ],
        "create_shared_schedule": [
            "공유 일정 생성에 필요한 입력값을 args dict로 모으세요.",
            'call_mcp_tool_sync("create_shared_schedule", args)를 호출하세요.',
        ],
        "delete_shared_schedule": [
            "schedule_id 또는 source_conversation_id를 args dict에 담으세요.",
            'call_mcp_tool_sync("delete_shared_schedule", args)를 호출하세요.',
        ],
        "list_shared_schedules": [
            "member/date/source 필터를 args dict에 담으세요.",
            'call_mcp_tool_sync("list_shared_schedules", args)를 호출하세요.',
        ],
        "collect_member_schedules": [
            "ensure_demo_personal_schedule()로 내 샘플 일정을 준비하세요.",
            "내 일정과 외부 멤버 일정을 같은 row 구조로 합치세요.",
            "members/rows/schedule_summary payload를 반환하세요.",
        ],
    },
    "student_parts/week06_kanamate_decides_schedule.py": {
        "decide_final_slot": [
            "candidate_slots가 있으면 첫 번째 후보를 선택하세요.",
            "후보가 없고 member_names/date 범위가 있으면 공통 가능 시간을 먼저 계산하세요.",
            "final_slot/reason/candidates를 top-level payload로 반환하세요.",
        ],
        "nana_agent": [
            "PROXY_TOKEN이 없으면 ok=False 실패 payload를 반환하세요.",
            "Nana sub-agent를 만들거나 재사용해 query를 invoke하세요.",
            "answer/trace/inner_tool_names payload를 반환하세요.",
        ],
        "kana_agent": [
            "PROXY_TOKEN이 없으면 ok=False 실패 payload를 반환하세요.",
            "Kana sub-agent를 invoke하고 trace에서 final_slot payload를 찾으세요.",
            "answer/trace/inner_tool_names/final_slot_payload를 반환하세요.",
        ],
    },
}


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in EXCLUDED_NAMES}


def _node_map(tree: ast.Module) -> dict[str, ast.AST]:
    nodes: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes[node.name] = node
    return nodes


def _body_replace_range(node: ast.AST) -> tuple[int, int]:
    body = getattr(node, "body", [])
    if not body:
        return node.lineno, node.end_lineno or node.lineno
    first_body = body[0]
    if isinstance(first_body, ast.Expr) and isinstance(getattr(first_body, "value", None), ast.Constant):
        if isinstance(first_body.value.value, str):
            return (first_body.end_lineno or first_body.lineno), node.end_lineno or first_body.lineno
    return first_body.lineno - 1, node.end_lineno or first_body.lineno


def _decorator_name(decorator: ast.AST) -> str | None:
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        return decorator.attr
    if isinstance(decorator, ast.Call):
        return _decorator_name(decorator.func)
    return None


def _is_tool_annotated(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(_decorator_name(decorator) == "tool" for decorator in node.decorator_list)


def _replacement_lines(node: ast.AST, function_name: str, message: str, steps: list[str]) -> list[str]:
    indent = " " * (node.col_offset + 4)
    if isinstance(node, ast.ClassDef):
        return [
            f"{indent}# [STUDENT TODO] {message}",
            f"{indent}pass",
        ]
    lines = [
        f"{indent}# [STUDENT TODO] {message}",
    ]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{indent}#   {index}. {step}")
    lines.extend(
        [
            f"{indent}# payload = {{\"ok\": True, \"tool_name\": \"{function_name}\"}}",
            f"{indent}# return json.dumps(payload, ensure_ascii=False)",
            f'{indent}raise NotImplementedError("{message}")',
        ]
    )
    return lines


def _strip_reference_answers(path: Path, relative_path: str, targets: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    nodes = _node_map(tree)
    replacements: list[tuple[int, int, list[str]]] = []

    for name, message in targets.items():
        node = nodes.get(name)
        if node is None:
            raise RuntimeError(f"{path}: target not found: {name}")
        if not _is_tool_annotated(node):
            raise RuntimeError(f"{path}: TODO target is not decorated with @tool: {name}")
        start, end = _body_replace_range(node)
        steps = TODO_STEPS.get(relative_path, {}).get(name, ["입력값을 정리하고 payload를 완성하세요."])
        replacements.append((start, end, _replacement_lines(node, name, message, steps)))

    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = replacement
    lines = [line for line in lines if "[참고 답안]" not in line and "[REFERENCE ANSWER]" not in line]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_student_distribution(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROJECT_ROOT, target, ignore=_ignore)

    for relative_path, targets in TODO_TARGETS.items():
        _strip_reference_answers(target / relative_path, relative_path, targets)

    readme = target / "STUDENT_README.md"
    readme.write_text(
        "\n".join(
            [
                "# Kanana Schedule Agent 학생용 배포본",
                "",
                "이 배포본은 강사용 완성 구현 중 `student_parts/`의 핵심 `@tool` 함수 구현부만 TODO로 바꾼 버전입니다.",
                "prompt, schema, tool-list, agent builder, MCP server 함수는 참고 코드로 남겨 둡니다.",
                "구현 방법은 각 주차 파일 최상단의 `[수강생 구현 가이드]`를 먼저 읽고, TODO tool 본문 안에서 입력 정리, store/MCP 호출, JSON 반환 계약을 맞추세요.",
                "",
                "실행과 검증:",
                "",
                "```bash",
                "./run.sh --week1",
                "./run.sh --week2",
                "./run.sh --test",
                "```",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    target = Path(args[0]).expanduser().resolve() if args and args[0] else DEFAULT_TARGET
    build_student_distribution(target)
    print(f"학생용 배포본을 생성했습니다: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
