# Kanana Agent 6주 / 총 12회 주차별 미션 커리큘럼

이 문서는 Kanana Schedule Agent 수업에서 다루는 Week별 미션을 정리한 강사용 운영안입니다. 미션은 현재 `student_parts/weekXX_*.py` 코드에 실제로 들어 있는 도구와 데이터 흐름만 기준으로 작성합니다. LLM과 Agent를 공부하는 학생들이 각 기능을 작은 단위로 따라가며 확인하도록 설계합니다.

## 운영 기준

- 대상: LLM과 Agent를 공부하는 학생
- 운영 시간: 주차당 2회, 회당 120분
- 수업 방식: 핵심 개념 확인, 기준 코드 따라가기, 입력값 바꿔 실험하기, 결과 확인하기
- 미션 방식: 각 Week 코드가 공개하는 tool, payload, 저장소, trace 흐름을 읽고 실행 결과로 검증하기

## Week 1 · week01_wake_up_nana.py

### 미션: 개인 일정 CRUD tool과 JSON payload 흐름 확인

학습 목표는 `create`, `list`, `delete`가 코드에서 어떤 데이터 이동으로 나타나는지 확인하는 것입니다. `PERSONAL_SCHEDULES` 리스트를 in-memory store로 보고, 일정 하나를 dict payload로 만들어 추가합니다.

`personal_create_schedule`에서는 `title`, `date`, `start_time`, `end_time`, `attendees` 입력이 `created_schedule`과 DB 저장용 `structured_request`로 바뀌는 흐름을 확인합니다. `personal_list_schedules`에서는 `date_from`, `date_to` 필터가 리스트 조회 조건으로 쓰이는 과정을 따라갑니다. `personal_delete_schedule`에서는 `schedule_id`로 일정을 제외한 새 리스트를 만들고 `deleted` 값을 반환하는 방식을 봅니다.

검증 포인트는 tool이 반환한 JSON 문자열을 `json.loads()`로 dict로 바꾼 뒤 `created_schedule`, `schedules`, `deleted`, `structured_request` 필드를 확인하는 것입니다.

## Week 2 · week02_structure_natural_language_requests.py

### 미션: 자연어 요청을 `StructuredRequest` schema로 변환

학습 목표는 한국어 자연어 입력을 앱이 처리할 수 있는 구조로 바꾸는 것입니다. `StructuredRequest`를 request schema로 보고, `kind`, `title`, `date`, `start_time`, `end_time`, `members`, `priority`, `reason`, `original_text` 필드가 왜 필요한지 확인합니다.

`structured_output_system_prompt`에서는 상대 날짜 기준, 요청 종류, 날짜/시간 형식, 애매한 필드 처리 규칙을 자연어 prompt로 작성합니다. `build_langchain_structured_agent`에서는 `response_format=StructuredRequest`를 넘겨 LLM structured output 경로를 구성합니다. `extract_schedule_request`는 사용자 prompt를 받아 `base_date`와 `structured_request`가 들어 있는 JSON payload를 반환합니다.

검증 포인트는 `내일`, `다음 주`, `오후 3시`, `팀원 A/B/C` 같은 표현이 schema 필드로 어떻게 들어가는지 비교하고, 조건문 parser가 아니라 LangChain/OpenAI structured output 결과와 Pydantic 검증이 맞물리는지 확인하는 것입니다.

## Week 3 · week03_build_nanas_logbook.py

### 미션: structured request 저장/조회와 저장 일정 삭제 흐름 확인

학습 목표는 in-memory store와 persistent storage의 차이를 이해하는 것입니다. Week 2의 structured payload가 `structured_requests`에 저장되고, `kind`에 따라 `schedules`, `todos`, `reminders`에 정규화되는 흐름을 봅니다.

`save_structured_request`에서는 payload를 SQLite store에 저장하고 저장 결과를 JSON으로 반환합니다. `list_saved_requests`에서는 `kind`, `date_from`, `date_to` 필터가 SQL 조회 조건으로 반영됩니다. `get_saved_request`에서는 `request_id`로 단일 row를 조회합니다.

저장된 개인 일정 삭제 흐름도 함께 확인합니다. `personal_list_saved_schedules`는 앱 DB의 일정 후보를 보여주고, `personal_delete_saved_schedules`는 `schedule_ids`, 날짜, 제목, 시간, 전체 삭제 여부 같은 필터로 저장 일정을 삭제합니다. `personal_delete_schedule_by_query`는 사용자 문장을 `extract_structured_request`로 구조화한 뒤 삭제 필터로 바꿉니다.

검증 포인트는 같은 입력을 여러 번 저장했을 때 request id와 row가 어떻게 달라지는지, 삭제 payload의 `deleted_count`, `filters`, `deleted`가 어떤 의미를 갖는지 확인하는 것입니다.

## Week 4 · week04_retrieve_nanas_memory.py

### 미션: 최소 tool로 개인 참고자료와 SQLite 일정 chunk 검색

학습 목표는 RAG를 "검색한 근거를 답변 재료로 붙이는 구조"로 이해하는 것입니다. Week 4의 대표 흐름은 Agent가 핵심 검색 조건을 고르고, `search_nana_memory` 한 번으로 Chroma 개인 참고자료와 SQLite `schedules` 일정 chunk를 함께 받아 답변 근거로 쓰는 방식입니다.

`search_nana_memory`는 `query`, `date_from`, `date_to`, `attendee`, `limit` 조건으로 참고자료와 저장 일정을 검색합니다. 개인 참고자료 검색은 ChromaDB collection에 저장된 문서를 OpenAI embedding으로 query하고, 저장 일정은 tool 안에서 "일정 1건 = chunk 1개"로 변환되어 `schedule_chunks`에 담깁니다.

`add_personal_reference`는 개인 참고자료를 추가할 때만 사용합니다. 일반 검색/답변 흐름에서는 `search_nana_memory` 결과의 `reference_hits`, `schedule_chunks`, `context`를 Agent가 직접 읽고 답합니다.

구현 순서는 단순하게 유지합니다. 먼저 ChromaDB 개인 참고자료를 OpenAI embedding 기반으로 검색하고, 그 다음 SQLite `schedules` 테이블을 검색한 뒤, 각 일정 row를 하나의 chunk dict로 바꾸고, 마지막에 모델 답변에 붙일 `context` 문자열을 조립합니다. `fixed/stores.py`는 테이블 구조와 저장소 API를 이해하기 위한 참고 파일이며, Week 4 실습 구현은 `student_parts/week04_retrieve_nanas_memory.py` 안에서 진행합니다.

실습 전 `.env`에 `OPENAI_API_KEY`가 필요합니다. 개인 참고자료 검색은 OpenAI embedding을 사용하며, 모델명은 `OPENAI_EMBEDDING_MODEL` 값으로 정합니다. `add_personal_reference`와 `search_nana_memory`의 `reference_backend` 필드에서 `vector_store=chromadb`, `embedding_provider=openai`를 확인합니다.

검증 포인트는 `search_nana_memory`가 참고자료와 일정 chunk를 함께 반환하는지, chunk가 `schedule_id`를 보존하는지, `context` 문자열이 모델 답변에 붙이기 좋은 형태인지 확인하는 것입니다.

## Week 5 · week05_load_kanas_past_conversations.py

### 미션: 외부 SQLite/MCP 기반 이전 대화와 멤버 일정 수집

학습 목표는 agent 코드가 외부 DB를 직접 뒤지지 않고 tool interface를 통해 이전 대화와 멤버 일정을 읽는 흐름을 이해하는 것입니다.

`search_previous_conversations`는 외부 SQLite 데이터베이스에서 이전 대화를 검색합니다. `load_conversation_messages`는 `conversation_id`로 특정 대화의 메시지를 시간순으로 불러옵니다. `extract_schedules_from_history`는 멤버 이름과 날짜 범위로 외부 대화 기록에 저장된 일정을 추출합니다.

`collect_member_schedules`는 Week 1의 내 개인 일정과 Week 5의 외부 멤버 일정을 합쳐 그룹 조율용 busy-time 목록을 만듭니다. `load_langchain_mcp_tools`와 `load_langchain_mcp_tools_sync`는 local MCP server에서 LangChain tool 목록을 불러오는 adapter 흐름을 보여줍니다.

검증 포인트는 `member_names`, `date_from`, `date_to`를 바꿨을 때 외부 대화 row와 일정 row가 어떻게 달라지는지, `collect_member_schedules`의 `members`와 `rows`가 그룹 조율에 필요한 입력을 갖추는지 확인하는 것입니다.

## Week 6 · week06_kanamate_decides_schedule.py

### 미션: Nana/Kana sub-agent와 supervisor routing으로 최종 일정 결정 payload 생성

학습 목표는 multi-agent routing을 역할 분리로 이해하는 것입니다. `nana_agent`는 개인 일정, 저장, 개인 RAG 흐름을 담당하고, `kana_agent`는 여러 사람의 일정 조율을 담당합니다.

`nana_system_prompt`, `kana_system_prompt`, `supervisor_system_prompt`는 각 agent가 어떤 tool chain을 고르는지 안내합니다. `nana_tools`는 Week 4까지의 개인 도구를 공개하고, `kana_tools`는 `extract_schedule_request`, 외부 대화 검색, 멤버 일정 수집, `find_common_available_slots`, `propose_group_schedule`을 공개합니다. `supervisor_tools`는 `nana_agent`, `kana_agent` 위임 도구만 노출합니다.

`kana_agent`는 `collect_member_schedules`로 busy-time 목록을 모으고, `find_common_available_slots`로 공통 가능 시간 후보를 계산합니다. 그 다음 선택한 시간을 `selected_slot`으로 만들어 `propose_group_schedule`에 전달합니다. `propose_group_schedule`은 `title`, `member_names`, `selected_slot`, `reason`을 최종 `final_decision` payload로 포장하고, 선택된 시간이 있으면 `status`를 `confirmed`로 둡니다.

검증 포인트는 supervisor trace에서 어떤 agent가 선택됐는지, 하위 agent trace에 `collect_member_schedules`, `find_common_available_slots`, `propose_group_schedule`이 어떤 순서로 호출됐는지, 최종 payload의 `status`, `selected_slot`, `reason`이 도구 결과와 일치하는지 확인하는 것입니다.

## 주차별 미션 진행 템플릿

| 구간 | 시간 | 활동 |
| --- | ---: | --- |
| Concept | 20분 | 이번 Week의 핵심 개념과 데이터 흐름을 소개합니다. |
| Walkthrough | 40분 | 기준 코드를 함께 읽고 TODO 단위로 구현 흐름을 확인합니다. |
| Experiment | 40분 | 입력값, 조건, payload 필드를 바꿔 결과를 관찰합니다. |
| Check | 20분 | 앱 화면, trace, JSON payload, test 중 하나로 동작을 확인합니다. |

## 검증 기준

- Week 1-2는 함수 실행 결과와 JSON payload 모양을 먼저 확인합니다.
- Week 3 이후는 `./run.sh --test`를 자동 검증 기준으로 사용합니다.
- Week 6 마지막에는 `./run.sh --golden`으로 전체 scenario가 깨지지 않았는지 확인합니다.

## 강사용 준비물

- 강사용 기준본은 실제 OpenAI/SQLite/ChromaDB 경로가 동작하는 완성본으로 유지하고, 학생용 배포본은 `./run.sh --make-student-copy`로 생성합니다.
- 학생용 배포본에서는 `student_parts/`의 `@tool` 함수 구현부만 `NotImplementedError` TODO로 바뀝니다.
- 수업 전 `./run.sh --test`로 기준본이 통과하는지 확인합니다.
- Week 2와 Week 4 검증은 실제 OpenAI API를 호출하므로 수업 전 `.env`의 `OPENAI_API_KEY`를 확인합니다.
- Week 3 이후에는 DB row가 누적될 수 있으므로 수업용 DB를 초기화하거나 복사본을 준비합니다.
