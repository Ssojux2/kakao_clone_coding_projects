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
        "_schedule_structured_request": "Week 1: DB 저장용 structured_request payload를 직접 구성하세요.",
        "personal_create_schedule": "Week 1: 개인 일정 생성 payload를 만들고 in-memory store에 저장하세요.",
        "personal_list_schedules": "Week 1: date_from/date_to 조건으로 개인 일정을 필터링하세요.",
        "personal_delete_schedule": "Week 1: schedule_id가 일치하는 일정을 삭제하고 결과 payload를 반환하세요.",
    },
    "student_parts/week02_structure_natural_language_requests.py": {
        "StructuredRequest": "Week 2: LLM structured output이 반환할 Pydantic schema를 정의하세요.",
        "structured_output_system_prompt": "Week 2: 날짜 기준, kind 분류, 애매한 필드 처리 규칙을 prompt로 작성하세요.",
        "build_langchain_structured_agent": "Week 2: response_format=StructuredRequest를 사용하는 LangChain agent를 만드세요.",
        "_structured_response_from_result": "Week 2: agent 결과에서 structured_response를 꺼내 Pydantic 모델로 검증하세요.",
    },
    "student_parts/week03_build_nanas_logbook.py": {
        "save_structured_request": "Week 3: 2주차 structured payload를 SQLite 저장소에 저장하는 tool을 구현하세요.",
        "list_saved_requests": "Week 3: kind/date_from/date_to 필터로 저장 요청을 조회하세요.",
        "get_saved_request": "Week 3: request_id 하나로 저장 요청 row를 조회하세요.",
        "delete_saved_schedules_dict": "Week 3: 일정 ID나 날짜/제목/시간 필터로 저장 일정을 삭제하세요.",
        "delete_schedule_by_query_dict": "Week 3: 자연어 삭제 요청을 구조화해 삭제 필터로 변환하세요.",
    },
    "student_parts/week04_retrieve_nanas_memory.py": {
        "add_personal_reference": "Week 4: 개인 참고자료를 ChromaDB에 저장하세요.",
        "search_nana_memory": "Week 4: 참고자료 검색, SQLite 일정 검색, chunk 변환, context 조립을 구현하세요.",
    },
    "student_parts/week05_load_kanas_past_conversations.py": {
        "search_previous_conversations": "Week 5: 외부 SQLite/MCP 대화 검색 tool을 구현하세요.",
        "load_conversation_messages": "Week 5: conversation_id로 이전 대화 메시지를 시간순 조회하세요.",
        "extract_schedules_from_history": "Week 5: 멤버와 날짜 범위로 외부 일정 row를 추출하세요.",
        "collect_member_schedules": "Week 5: 내 일정과 외부 멤버 일정을 그룹 조율용 busy-time으로 합치세요.",
    },
    "student_parts/week06_kanamate_decides_schedule.py": {
        "_nana_capability_text": "Week 6: Nana가 사용할 주차별 tool 설명을 직접 구성하세요.",
        "_nana_workflow_text": "Week 6: Nana의 개인 일정 처리 workflow prompt를 직접 구성하세요.",
        "_kana_capability_text": "Week 6: Kana가 사용할 그룹 조율 tool 설명을 직접 구성하세요.",
        "nana_system_prompt": "Week 6: Nana 하위 agent가 고를 tool chain과 제약을 prompt로 작성하세요.",
        "kana_system_prompt": "Week 6: Kana 하위 agent가 그룹 일정을 조율하는 prompt를 작성하세요.",
        "supervisor_system_prompt": "Week 6: supervisor가 Nana/Kana로 위임하는 기준을 prompt로 작성하세요.",
        "find_common_available_slots_dict": "Week 6: busy-time rows에서 공통 가능 시간 후보를 계산하세요.",
        "find_common_available_slots": "Week 6: 공통 가능 시간 후보 계산 tool payload를 반환하세요.",
        "nana_tools": "Week 6: 현재 주차에 맞춰 Nana sub-agent가 사용할 tool 목록을 조립하세요.",
        "kana_tools": "Week 6: 현재 주차에 맞춰 Kana sub-agent가 사용할 tool 목록을 조립하세요.",
        "supervisor_tools": "Week 6: supervisor가 사용할 위임 tool 목록을 조립하세요.",
        "propose_group_schedule": "Week 6: 선택된 후보 시간을 최종 결정 payload로 포장하세요.",
        "nana_agent": "Week 6: supervisor가 위임한 개인 일정 요청을 Nana sub-agent로 실행하세요.",
        "kana_agent": "Week 6: supervisor가 위임한 그룹 일정 요청을 Kana sub-agent로 실행하세요.",
        "build_langchain_supervisor_agent": "Week 6: nana_agent/kana_agent 위임 tool만 노출하는 supervisor를 만드세요.",
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
                "이 배포본은 강사용 완성 구현 중 `student_parts/`의 핵심 구현부를 TODO로 바꾼 버전입니다.",
                "",
                "주차별 실행:",
                "",
                "```bash",
                "./run.sh --week 1",
                "./run.sh --test-week 1",
                "```",
                "",
                "`KANANA_ACTIVE_WEEK` 값을 1부터 6까지 바꾸면 현재 주차까지의 도구만 노출됩니다.",
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
