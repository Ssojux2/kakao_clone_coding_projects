# Kanana Schedule Agent

Kanana 강의용 일정 Agent 프로젝트입니다. LLM과 Agent를 공부하는 학생들이 prompt-driven supervisor agent, sub-agent, tool 호출 흐름을 따라가며 학습하도록 구성했습니다. 메인 채팅 화면은 사용자 프롬프트를 보고 `nana_agent` 또는 `kana_agent` tool을 직접 호출하며, tool/trace는 상세 탭에서 확인합니다.

처음 프로젝트 구조를 훑는 수강생은 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)를 먼저 보면 전체 흐름을 빠르게 잡을 수 있습니다.

6주 / 12차시 수업 운영안은 [CURRICULUM.md](CURRICULUM.md)를 기준으로 진행합니다.

## 실행

이 프로젝트의 기본 Python 패키지 관리는 `uv`를 사용합니다. 처음 실행할 때는 아래 명령으로 `pyproject.toml`과 `uv.lock` 기준의 `.venv`를 만들고 앱을 실행합니다.

```bash
cd kakao_clone_coding_projects
./run.sh --install
```

설치가 끝난 뒤에는 아래 명령만 실행하면 됩니다. `uv run`은 실행 전에 lockfile과 `.venv` 상태를 확인하고 필요한 패키지를 동기화합니다.

```bash
./run.sh
```

`.env`는 repo 루트의 파일을 읽습니다. `.env.example`을 복사해서 개인 키를 채워 넣으세요.

```bash
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
KANANA_USE_LLM=1
KANANA_LLM_ASSIST=1
```

메인 채팅 화면은 `OPENAI_API_KEY`가 있어야 동작합니다. 메인 런타임은 주차나 tool을 고르지 않고, LangChain supervisor prompt가 `golden_cases.py`의 하네스 예시를 참고해 `nana_agent` 또는 `kana_agent` tool을 호출합니다. 각 sub-agent도 자기 prompt와 tool 목록을 기준으로 structured output, 일정 CRUD, SQLite 저장/조회, RAG 검색, MCP 검색, 그룹 일정 제안을 수행합니다. Week 2 structured output tool은 조건문 분류기 없이 LangChain/OpenAI structured output 경로를 사용합니다.

### 학생용 배포본 만들기

강사용 기준본은 모든 주차가 실제로 동작하는 완성본입니다. 학생에게 나눠줄 때는 아래 명령으로 `@tool` 함수 구현부만 TODO로 바뀐 복사본을 생성합니다.

```bash
./run.sh --make-student-copy
```

기본 출력 위치는 `dist/kanana_student`입니다. 다른 위치로 만들고 싶으면 경로를 넘깁니다.

```bash
./run.sh --make-student-copy /tmp/kanana_student
```

### 패키지 관리

새 의존성의 기준 파일은 `pyproject.toml`과 `uv.lock`입니다. `requirements.txt`와 `environment.yml`은 기존 수강생 환경을 위한 legacy/fallback 파일로 남겨둡니다.

```bash
uv add "package-name>=1.0"
uv add --dev "dev-tool>=1.0"
uv remove package-name
uv lock --upgrade-package package-name
```

conda 환경이 필요한 경우에는 기존 `environment.yml` 기반 runner를 fallback으로 사용할 수 있습니다.

```bash
./run.sh --conda --install
./run.sh --conda --test
```

## 주차별 구현 포인트

- Week 1: `student_parts/week01_wake_up_nana.py`
  - `personal_create_schedule`, `personal_list_schedules`, `personal_delete_schedule`
  - 생성 tool은 DB 저장 도구에 바로 넘길 수 있는 `structured_request`를 함께 반환합니다.
  - 검증은 개별 tool을 직접 호출하기보다 하네스 프롬프트를 채팅 런타임에 넣고 LLM이 어떤 tool을 골랐는지 trace를 확인하는 방식이 기본입니다.
- Week 2: `student_parts/week02_structure_natural_language_requests.py`
  - LLM structured output + Pydantic `StructuredRequest`
  - `week02_tools()`는 Week 1 도구에 `extract_schedule_request`를 누적해 반환합니다.
- Week 3: `student_parts/week03_build_nanas_logbook.py`
  - LLM이 저장/조회 의도를 판단하고 SQLite tool로 structured output을 저장/조회
  - `week03_tools()`는 Week 1-2 도구와 SQLite 저장/조회/삭제 도구를 함께 노출합니다.
- Week 4: `student_parts/week04_retrieve_nanas_memory.py`
  - LLM이 ChromaDB 개인 참고자료와 SQLite structured data 검색 tool을 조합
  - 개인 참고자료 add/search는 `PersonalReferenceStore`의 ChromaDB collection과 OpenAI embedding adapter를 기준으로 동작합니다.
  - course repo 기준 RAG tool은 `search_personal_references`와 `search_saved_requests`이며, 각각 top-level `hits`, `rows` payload를 반환합니다.
  - 기존 통합 검색 `search_nana_memory`는 compatibility helper로 남겨 두며 `reference_backend`와 context를 함께 확인할 수 있습니다.
  - `week04_tools()`는 Week 1-3 도구에 RAG 도구를 누적합니다.
- Week 5: `student_parts/week05_load_kanas_past_conversations.py`, `mcp_server/sqlite_mcp_server.py`
  - LLM이 MCP SQLite 이전 대화 검색, 메시지 로드, 일정 추출 tool을 조합
  - `week05_tools()`는 Week 1-4 도구에 외부 SQLite/MCP 일정 도구를 누적합니다.
- Week 6: `student_parts/week06_kanamate_decides_schedule.py`
  - prompt-driven supervisor, `nana_agent`, `kana_agent`, tool 기반 sub-agent
  - Week 6 파일은 이전 주차 구현을 다시 작성하지 않고 Week 1-5 도구를 import해 sub-agent tool 목록을 조립합니다.
  - `decide_final_slot`이 course repo 기준 최종 `final_slot`, `reason`, `candidates` payload를 반환합니다.
  - 기존 `find_common_available_slots`와 `propose_group_schedule`은 compatibility helper로 남겨 기능을 유지합니다.

강사용 기준본은 실행 가능한 구현을 담고 있습니다. 학생용 배포본은 `scripts/make_student_distribution.py`가 주차별 `@tool` 함수 구현부만 `NotImplementedError` TODO로 바꿉니다.

## 검증

```bash
./run.sh --golden
```

모든 케이스의 `passed`가 `true`면 하네스 프롬프트가 supervisor/sub-agent prompt에 포함되어 있고, 기대 agent와 tool이 해당 agent의 tool 목록에 노출된 것입니다.

pytest 기반 하네스 테스트까지 함께 확인하려면 아래 명령을 실행합니다.

```bash
./run.sh --test
```

`--test`는 pytest가 하네스 프롬프트, agent prompt/tool wiring, prompt-driven runtime trace 형식을 확인한 뒤 golden harness 검증을 이어서 실행합니다.

Week 2 structured output과 Week 4 ChromaDB reference 검색 테스트는 실제 OpenAI API를 호출합니다. `.env`에 `OPENAI_API_KEY`가 없으면 해당 테스트는 실패합니다.

## 공식 문서 기준

- LangChain v1 agents/tools/structured output/subagents 패턴
- LangChain MCP adapters
- Gradio `Blocks(css_paths=...)`, `Chatbot(type="messages")`
- Kanana 공식 로고/브랜드 자산은 강의 목적으로 UI에 사용합니다.
