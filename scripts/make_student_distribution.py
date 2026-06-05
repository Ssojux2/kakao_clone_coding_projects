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
        "personal_update_saved_schedule": "Week 3: 저장 일정 수정 helper를 JSON tool로 감싸세요.",
        "personal_delete_saved_schedules": "Week 3: 저장 일정 삭제 helper를 JSON tool로 감싸세요.",
        "personal_delete_schedule_by_query": "Week 3: 자연어 삭제 helper를 JSON tool로 감싸세요.",
    },
    "student_parts/week04_retrieve_nanas_memory.py": {
        "add_personal_reference": "Week 4: 개인 참고자료를 ChromaDB에 저장하세요.",
        "search_nana_memory": "Week 4: 참고자료 검색, SQLite 일정 검색, chunk 변환, context 조립을 구현하세요.",
    },
    "student_parts/week05_load_kanas_past_conversations.py": {
        "search_previous_conversations": "Week 5: 외부 SQLite/MCP 대화 검색 tool을 구현하세요.",
        "load_conversation_messages": "Week 5: conversation_id로 이전 대화 메시지를 시간순 조회하세요.",
        "extract_schedules_from_history": "Week 5: 멤버와 날짜 범위로 외부 일정 row를 추출하세요.",
        "create_shared_schedule": "Week 5: 외부 MCP 공유 일정 생성/갱신 tool wrapper를 구현하세요.",
        "delete_shared_schedule": "Week 5: 외부 MCP 공유 일정 삭제 tool wrapper를 구현하세요.",
        "collect_member_schedules": "Week 5: 내 일정과 외부 멤버 일정을 그룹 조율용 busy-time으로 합치세요.",
    },
    "student_parts/week06_kanamate_decides_schedule.py": {
        "personal_delete_schedule_by_query": "Week 6: 기존 삭제 helper를 JSON tool로 감싸 호환성을 유지하세요.",
        "extract_schedule_request": "Week 6: Kana가 사용할 구조화 요청 tool wrapper를 구현하세요.",
        "find_common_available_slots": "Week 6: 공통 가능 시간 후보 계산 tool payload를 반환하세요.",
        "propose_group_schedule": "Week 6: 선택된 후보 시간을 최종 결정 payload로 포장하세요.",
        "nana_agent": "Week 6: supervisor가 위임한 개인 일정 요청을 Nana sub-agent로 실행하세요.",
        "kana_agent": "Week 6: supervisor가 위임한 그룹 일정 요청을 Kana sub-agent로 실행하세요.",
    },
}

TODO_GUIDES: dict[str, dict[str, list[str]]] = {
    "student_parts/week01_wake_up_nana.py": {
        "personal_create_schedule": [
            "new_id('personal')와 now_iso()로 id/created_at을 채운 schedule dict를 만드세요.",
            "PERSONAL_SCHEDULES에 append한 뒤 ok, tool_name, created_schedule, structured_request를 JSON 문자열로 반환하세요.",
        ],
        "personal_list_schedules": [
            "date_from/date_to가 주어진 경우만 YYYY-MM-DD 문자열 비교로 범위를 필터링하세요.",
            "반환 payload에는 ok, tool_name, schedules를 포함하세요.",
        ],
        "personal_delete_schedule": [
            "PERSONAL_SCHEDULES 리스트 객체를 유지한 채 schedule_id가 다른 항목만 남기세요.",
            "삭제 전후 길이 비교로 deleted bool을 만들고 schedule_id와 함께 반환하세요.",
        ],
    },
    "student_parts/week02_structure_natural_language_requests.py": {
        "extract_schedule_request": [
            "extract_structured_request(query)를 호출해 검증된 StructuredRequest 모델을 얻으세요.",
            "ok, tool_name, base_date, structured_request를 포함한 JSON 문자열을 반환하세요.",
        ],
    },
    "student_parts/week03_build_nanas_logbook.py": {
        "save_structured_request": [
            "payload가 문자열이면 json.loads로 dict로 바꾼 뒤 STORE.save_structured_request에 넘기세요.",
            "저장소 결과에 ok와 tool_name을 더해 JSON 문자열로 반환하세요.",
        ],
        "list_saved_requests": [
            "kind/date_from/date_to 필터를 STORE.list_saved_requests에 그대로 전달하세요.",
            "rows 배열을 ok/tool_name과 함께 반환하세요.",
        ],
        "get_saved_request": [
            "request_id로 STORE.get_saved_request를 호출하세요.",
            "row가 None이어도 ok/tool_name/row 형태를 유지하세요.",
        ],
        "personal_list_saved_schedules": [
            "AppSQLiteStore(CONFIG.app_db_path)를 만들고 list_schedules(limit=limit)를 호출하세요.",
            "수정/삭제 후보를 agent가 고를 수 있도록 schedules 배열을 반환하세요.",
        ],
        "personal_update_saved_schedule": [
            "update_saved_schedule_dict를 호출하고 결과 dict를 json.dumps(..., ensure_ascii=False)로 감싸세요.",
        ],
        "personal_delete_saved_schedules": [
            "delete_saved_schedules_dict를 호출하고 결과 dict를 JSON 문자열로 감싸세요.",
            "tool 결과에는 deleted_count와 filters가 유지되어야 합니다.",
        ],
        "personal_delete_schedule_by_query": [
            "delete_schedule_by_query_dict를 호출하고 JSON 문자열로 반환하세요.",
            "이 tool은 ID 없는 삭제 요청을 처리하는 호환 wrapper입니다.",
        ],
    },
    "student_parts/week04_retrieve_nanas_memory.py": {
        "add_personal_reference": [
            "REFERENCE_STORE.add_personal_reference에 title/content/tags를 저장하세요.",
            "reference_backend와 저장된 reference를 함께 반환하세요.",
        ],
        "search_nana_memory": [
            "limit을 보정하고 ChromaDB 개인 참고자료를 먼저 검색하세요.",
            "SQLite schedules 테이블을 query/date/attendee 조건으로 조회한 뒤 각 row를 schedule_chunks로 변환하세요.",
            "reference_hits와 schedule_chunks를 사람이 읽을 수 있는 context 문자열로 조립해 반환하세요.",
        ],
    },
    "student_parts/week05_load_kanas_past_conversations.py": {
        "search_previous_conversations": [
            "member_names를 외부 DB 기준 이름으로 정규화하고 MCP search_previous_conversations tool을 호출하세요.",
            "MCP tool 결과 문자열을 그대로 반환하세요.",
        ],
        "load_conversation_messages": [
            "conversation_id를 MCP load_conversation_messages tool 인자로 넘기세요.",
            "대화 메시지 rows가 포함된 JSON 문자열을 반환하세요.",
        ],
        "extract_schedules_from_history": [
            "멤버와 날짜 범위를 정규화한 뒤 MCP extract_schedules_from_history tool에 넘기세요.",
            "Week 6에서 busy-time으로 쓸 수 있도록 rows payload를 유지하세요.",
        ],
        "create_shared_schedule": [
            "member_name/title/date/start_time/end_time/notes/source_conversation_id/schedule_id를 MCP create_shared_schedule tool에 넘기세요.",
            "내 일정 저장소와 공유 일정 저장소를 연결할 수 있도록 source_conversation_id를 보존하세요.",
        ],
        "delete_shared_schedule": [
            "schedule_id 또는 source_conversation_id를 MCP delete_shared_schedule tool에 넘기세요.",
            "삭제 결과 JSON 문자열을 그대로 반환하세요.",
        ],
        "collect_member_schedules": [
            "내 일정은 list_personal_schedule_dicts에서, 외부 일정은 extract_schedules_from_history_dict에서 가져오세요.",
            "두 결과를 member_name/title/date/start_time/end_time/notes 모양으로 합치고 schedule_summary도 넣으세요.",
        ],
    },
    "student_parts/week06_kanamate_decides_schedule.py": {
        "personal_delete_schedule_by_query": [
            "Week 3 delete_schedule_by_query_dict를 호출하고 JSON 문자열로 반환하세요.",
            "Week 6 import 호환을 위해 tool_name과 payload 모양을 유지하세요.",
        ],
        "extract_schedule_request": [
            "extract_structured_request(query)를 호출해 StructuredRequest 모델을 얻으세요.",
            "base_date와 structured_request.model_dump()를 포함한 JSON 문자열을 반환하세요.",
        ],
        "find_common_available_slots": [
            "find_common_available_slots_dict 결과를 JSON 문자열로 감싸는 @tool wrapper를 작성하세요.",
        ],
        "propose_group_schedule": [
            "selected_slot이 있으면 그것을, 없으면 candidate_slots의 첫 번째 값을 선택하세요.",
            "선택된 시간이 있으면 status=confirmed, 없으면 needs_manual_review로 final_decision을 만드세요.",
        ],
        "nana_agent": [
            "build_nana_subagent().invoke로 query를 전달하고 answer, trace, inner_tool_names를 JSON으로 반환하세요.",
            "OPENAI_API_KEY가 없을 때는 실패 payload를 반환하세요.",
        ],
        "kana_agent": [
            "build_kana_subagent().invoke로 query를 전달하고 trace에서 final_decision을 찾아 끌어올리세요.",
            "answer, trace, inner_tool_names, final_decision_payload를 JSON으로 반환하세요.",
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


def _replacement_lines(node: ast.AST, message: str, guide_lines: list[str] | None = None) -> list[str]:
    indent = " " * (node.col_offset + 4)
    todo_comments = [f"{indent}# [STUDENT TODO] {message}"]
    for line in guide_lines or []:
        todo_comments.append(f"{indent}# - {line}")
    if isinstance(node, ast.ClassDef):
        return [
            *todo_comments,
            f"{indent}pass",
        ]
    return [
        *todo_comments,
        f'{indent}raise NotImplementedError("{message}")',
    ]


def _strip_reference_answers(path: Path, targets: dict[str, str], guides: dict[str, list[str]] | None = None) -> None:
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
        replacements.append((start, end, _replacement_lines(node, message, (guides or {}).get(name))))

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
        _strip_reference_answers(target / relative_path, targets, TODO_GUIDES.get(relative_path))

    readme = target / "STUDENT_README.md"
    readme.write_text(
        "\n".join(
            [
                "# Kanana Schedule Agent 학생용 배포본",
                "",
                "이 배포본은 강사용 완성 구현 중 `student_parts/`의 `@tool` 함수 구현부만 TODO로 바꾼 버전입니다.",
                "tool annotation이 붙지 않은 helper, schema, prompt, tool-list 함수는 참고 코드로 남겨 둡니다.",
                "각 TODO에는 구현 순서가 주석으로 붙어 있습니다. 수업에서는 `@tool` 함수의 입력/출력 JSON 계약을 먼저 맞추세요.",
                "",
                "실행과 검증:",
                "",
                "```bash",
                "./run.sh",
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
