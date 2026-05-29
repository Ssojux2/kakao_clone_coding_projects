# Kanana Agent 6주 / 총 12회 주차별 미션 커리큘럼

이 문서는 Kanana Schedule Agent 수업에서 다루는 Week별 미션을 정리한 강사용 운영안입니다. 미션은 현재 `student_parts/weekXX_*.py` 코드에 실제로 들어 있는 도구와 데이터 흐름만 기준으로 작성합니다. 용어는 실제 개발 수업처럼 사용하되, 학습 활동은 초보 학습자가 작은 단위로 따라오도록 설계합니다.

## 운영 기준

- 대상 수준: 중학교 1학년 수준의 Python 초보 학습자
- 용어 수준: 대학생/초급 개발자 기준
- 운영 시간: 주차당 2회, 회당 120분
- 수업 방식: 핵심 개념 확인, 기준 코드 따라가기, 입력값 바꿔 실험하기, 결과 확인하기
- 미션 방식: 각 Week 코드가 공개하는 tool, payload, 저장소, trace 흐름을 읽고 실행 결과로 검증하기

## Week 1 · Stateful CRUD Tool

### 미션: 개인 일정 CRUD tool과 JSON payload 흐름 확인

학습 목표는 `create`, `list`, `delete`가 코드에서 어떤 데이터 이동으로 나타나는지 확인하는 것입니다. `PERSONAL_SCHEDULES` 리스트를 in-memory store로 보고, 일정 하나를 dict payload로 만들어 추가합니다.

`personal_create_schedule`에서는 `title`, `date`, `start_time`, `end_time`, `attendees` 입력이 `created_schedule`과 DB 저장용 `structured_request`로 바뀌는 흐름을 확인합니다. `personal_list_schedules`에서는 `date_from`, `date_to` 필터가 리스트 조회 조건으로 쓰이는 과정을 따라갑니다. `personal_delete_schedule`에서는 `schedule_id`로 일정을 제외한 새 리스트를 만들고 `deleted` 값을 반환하는 방식을 봅니다.

검증 포인트는 tool이 반환한 JSON 문자열을 `json.loads()`로 dict로 바꾼 뒤 `created_schedule`, `schedules`, `deleted`, `structured_request` 필드를 확인하는 것입니다.

## Week 2 · Structured Output Schema

### 미션: 자연어 요청을 `StructuredRequest` schema로 변환

학습 목표는 한국어 자연어 입력을 앱이 처리할 수 있는 구조로 바꾸는 것입니다. `StructuredRequest`를 request schema로 보고, `kind`, `title`, `date`, `start_time`, `end_time`, `members`, `priority`, `reason`, `original_text` 필드가 왜 필요한지 확인합니다.

`structured_output_system_prompt`에서는 상대 날짜 기준, 요청 종류, 날짜/시간 형식, 애매한 필드 처리 규칙을 자연어 prompt로 작성합니다. `build_langchain_structured_agent`에서는 `response_format=StructuredRequest`를 넘겨 LLM structured output 경로를 구성합니다. `extract_schedule_request`는 사용자 prompt를 받아 `base_date`와 `structured_request`가 들어 있는 JSON payload를 반환합니다.

검증 포인트는 `내일`, `다음 주`, `오후 3시`, `팀원 A/B/C` 같은 표현이 schema 필드로 어떻게 들어가는지 비교하고, 조건문 parser가 아니라 LangChain/OpenAI structured output 결과와 Pydantic 검증이 맞물리는지 확인하는 것입니다.

## Week 3 · SQLite Persistence

### 미션: structured request 저장/조회와 저장 일정 삭제 흐름 확인

학습 목표는 in-memory store와 persistent storage의 차이를 이해하는 것입니다. Week 2의 structured payload가 `structured_requests`에 저장되고, `kind`에 따라 `schedules`, `todos`, `reminders`에 정규화되는 흐름을 봅니다.

`save_structured_request`에서는 payload를 SQLite store에 저장하고 저장 결과를 JSON으로 반환합니다. `list_saved_requests`에서는 `kind`, `date_from`, `date_to` 필터가 SQL 조회 조건으로 반영됩니다. `get_saved_request`에서는 `request_id`로 단일 row를 조회합니다.

저장된 개인 일정 삭제 흐름도 함께 확인합니다. `personal_list_saved_schedules`는 앱 DB의 일정 후보를 보여주고, `personal_delete_saved_schedules`는 `schedule_ids`, 날짜, 제목, 시간, 전체 삭제 여부 같은 필터로 저장 일정을 삭제합니다. `personal_delete_schedule_by_query`는 사용자 문장을 `extract_structured_request`로 구조화한 뒤 삭제 필터로 바꿉니다.

검증 포인트는 같은 입력을 여러 번 저장했을 때 request id와 row가 어떻게 달라지는지, 삭제 payload의 `deleted_count`, `filters`, `deleted`가 어떤 의미를 갖는지 확인하는 것입니다.

## Week 4 · Agentic RAG

### 미션: Chroma 참고자료와 SQLite 저장 요청을 검색해 RAG context 조립

학습 목표는 RAG를 "검색한 근거를 답변 재료로 붙이는 구조"로 이해하는 것입니다. ChromaDB 개인 참고자료 검색과 SQLite 저장 요청 검색을 각각 실행하고, 두 검색 결과의 차이를 확인합니다.

`add_personal_reference`는 개인 참고자료를 ChromaDB collection에 문서와 metadata로 저장합니다. `search_personal_references`는 사용자의 질문을 검색어로 삼아 관련 참고자료 hit를 반환합니다. `search_saved_requests`는 SQLite에 저장된 structured request row를 검색합니다.

`build_rag_context`는 `reference_hits`와 `sqlite_hits`를 받아 `[개인 참고자료]`, `[SQLite 저장 요청]` 구역이 있는 하나의 context 문자열로 합칩니다.

검증 포인트는 검색어와 `limit` 값을 바꿨을 때 어떤 hit가 들어오는지, 최종 `context` 문자열이 모델 답변에 붙이기 좋은 형태인지 확인하는 것입니다.

## Week 5 · MCP Tool Adapter

### 미션: 외부 SQLite/MCP 기반 이전 대화와 멤버 일정 수집

학습 목표는 agent 코드가 외부 DB를 직접 뒤지지 않고 tool interface를 통해 이전 대화와 멤버 일정을 읽는 흐름을 이해하는 것입니다.

`search_previous_conversations`는 외부 SQLite 데이터베이스에서 이전 대화를 검색합니다. `load_conversation_messages`는 `conversation_id`로 특정 대화의 메시지를 시간순으로 불러옵니다. `extract_schedules_from_history`는 멤버 이름과 날짜 범위로 외부 대화 기록에 저장된 일정을 추출합니다.

`collect_member_schedules`는 Week 1의 내 개인 일정과 Week 5의 외부 멤버 일정을 합쳐 그룹 조율용 busy-time 목록을 만듭니다. `load_langchain_mcp_tools`와 `load_langchain_mcp_tools_sync`는 local MCP server에서 LangChain tool 목록을 불러오는 adapter 흐름을 보여줍니다.

검증 포인트는 `member_names`, `date_from`, `date_to`를 바꿨을 때 외부 대화 row와 일정 row가 어떻게 달라지는지, `collect_member_schedules`의 `members`와 `rows`가 그룹 조율에 필요한 입력을 갖추는지 확인하는 것입니다.

## Week 6 · Supervisor Routing and Sub-agents

### 미션: Nana/Kana sub-agent와 supervisor routing으로 최종 일정 결정 payload 생성

학습 목표는 multi-agent routing을 역할 분리로 이해하는 것입니다. `nana_agent`는 개인 일정, 저장, 개인 RAG 흐름을 담당하고, `kana_agent`는 여러 사람의 일정 조율을 담당합니다.

`nana_system_prompt`, `kana_system_prompt`, `supervisor_system_prompt`는 각 agent가 어떤 tool chain을 고르는지 안내합니다. `nana_tools`는 Week 4까지의 개인 도구를 공개하고, `kana_tools`는 `extract_schedule_request`, 외부 대화 검색, 멤버 일정 수집, `propose_group_schedule`을 공개합니다. `supervisor_tools`는 `nana_agent`, `kana_agent` 위임 도구만 노출합니다.

`kana_agent`는 `collect_member_schedules` 결과를 보고 가능한 시간을 판단한 뒤, 선택한 시간을 `selected_slot`으로 만들어 `propose_group_schedule`에 전달합니다. `propose_group_schedule`은 `title`, `member_names`, `selected_slot`, `reason`을 최종 `final_decision` payload로 포장하고, 선택된 시간이 있으면 `status`를 `confirmed`로 둡니다.

검증 포인트는 supervisor trace에서 어떤 agent가 선택됐는지, 하위 agent trace에 어떤 inner tool이 호출됐는지, 최종 payload의 `status`, `selected_slot`, `reason`이 도구 결과와 일치하는지 확인하는 것입니다.

## 주차별 미션 진행 템플릿

| 구간 | 시간 | 활동 |
| --- | ---: | --- |
| Concept | 20분 | 이번 Week의 핵심 용어와 데이터 흐름을 소개합니다. |
| Walkthrough | 40분 | 기준 코드를 함께 읽고 TODO 단위로 구현 흐름을 확인합니다. |
| Experiment | 40분 | 입력값, 조건, payload 필드를 바꿔 결과를 관찰합니다. |
| Check | 20분 | 앱 화면, trace, JSON payload, test 중 하나로 동작을 확인합니다. |

## 검증 기준

- Week 1-2는 함수 실행 결과와 JSON payload 모양을 먼저 확인합니다.
- Week 3 이후는 `./run.sh --test`를 자동 검증 기준으로 사용합니다.
- Week 6 마지막에는 `./run.sh --golden`으로 전체 scenario가 깨지지 않았는지 확인합니다.

## 강사용 준비물

- 학생용 배포본에서는 `# [REFERENCE ANSWER]` 아래 구현을 가리고 TODO만 남깁니다.
- 수업 전 `./run.sh --test`로 기준본이 통과하는지 확인합니다.
- Week 3 이후에는 DB row가 누적될 수 있으므로 수업용 DB를 초기화하거나 복사본을 준비합니다.
- 어려운 용어는 낮추지 말고, payload, table row, trace 화면과 바로 연결해 설명합니다.
