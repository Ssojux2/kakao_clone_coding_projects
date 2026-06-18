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


def _replacement_lines(node: ast.AST, message: str) -> list[str]:
    indent = " " * (node.col_offset + 4)
    if isinstance(node, ast.ClassDef):
        return [
            f"{indent}# [STUDENT TODO] {message}",
            f"{indent}pass",
        ]
    return [
        f"{indent}# [STUDENT TODO] {message}",
        f'{indent}raise NotImplementedError("{message}")',
    ]


def _strip_reference_answers(path: Path, targets: dict[str, str]) -> None:
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
        replacements.append((start, end, _replacement_lines(node, message)))

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
        _strip_reference_answers(target / relative_path, targets)

    readme = target / "STUDENT_README.md"
    readme.write_text(
        "\n".join(
            [
                "# Kanana Schedule Agent 학생용 배포본",
                "",
                "이 배포본은 강사용 완성 구현 중 `student_parts/`의 핵심 `@tool` 함수 구현부만 TODO로 바꾼 버전입니다.",
                "prompt, schema, helper, tool-list, agent builder, MCP server 함수는 참고 코드로 남겨 둡니다.",
                "구현 방법은 각 주차 파일 최상단의 `[수강생 구현 가이드]`를 먼저 읽고, TODO 함수의 입력/출력 JSON 계약을 맞추세요.",
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
