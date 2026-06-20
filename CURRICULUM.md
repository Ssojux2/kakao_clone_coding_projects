# Kanana Agent 6주 / 총 12회 주차별 미션 커리큘럼

이 문서는 Kanana Schedule Agent 수업에서 다루는 Week별 미션을 정리한 강사용 운영안입니다. 미션은 현재 `student_parts/weekXX_*.py` 코드에 실제로 들어 있는 prompt, 도구, 데이터 흐름만 기준으로 작성합니다. LLM과 Agent를 공부하는 학생들이 각 기능을 작은 단위로 따라가며 확인하도록 설계합니다.

앱 실행은 기본적으로 Week 1 agent를 사용합니다. 수업 주차별 앱 확인은 `./run.sh --week1`부터 `./run.sh --week6`까지 active week를 명시해 진행합니다. `fixed/agent_runtime.py`는 UI 입력과 대화 저장만 담당하고, 선택된 주차의 `build_week_agent()`를 `fixed.week_agent_registry`가 동적으로 import해 실행합니다.

## 운영 기준

- 대상: LLM과 Agent를 공부하는 학생
- 운영 시간: 주차당 2회, 회당 150분
- 수업 방식: 핵심 개념 확인, 기준 코드 따라가기, 입력값 바꿔 실험하기, 결과 확인하기
- 미션 방식: 각 Week 코드가 공개하는 prompt, tool, payload, 저장소, trace 흐름을 읽고 실행 결과로 검증하기
- 학생 직접 구현 범위: 각 `student_parts/weekXX_*.py` 최상단 `[수강생 구현 가이드]`가 지정한 핵심 `@tool` 함수만 구현합니다. 학생은 TODO tool 본문 안에서 입력 정리, 저장소/MCP 호출, JSON 반환까지 완성하며 별도 helper 계층을 따라 구현하지 않아도 됩니다. prompt, schema, tool-list, agent builder, MCP server 함수는 연결 구조를 읽는 참고 코드로 둡니다.

## Week 1 · week01_wake_up_nana.py

### 미션: 개인 일정 CRUD tool과 JSON payload 흐름 확인

학습 목표는 단일 agent 프롬프트와 `create`, `list`, `delete`가 코드에서 어떤 데이터 이동으로 나타나는지 확인하는 것입니다. `PERSONAL_SCHEDULES` 리스트를 in-memory store로 보고, 일정 하나를 dict payload로 만들어 추가합니다.

`week01_system_prompt`는 개인 일정 생성/조회/삭제 역할과 Week 1 범위를 정의합니다. `personal_create_schedule`에서는 `title`, `date`, `start_time`, `end_time`, `attendees` 입력이 `created_schedule`과 DB 저장용 `structured_request`로 바뀌는 흐름을 확인합니다. `personal_list_schedules`에서는 `date_from`, `date_to` 필터가 리스트 조회 조건으로 쓰이는 과정을 따라갑니다. `personal_delete_schedule`에서는 `schedule_id`로 일정을 제외한 새 리스트를 만들고 `deleted` 값을 반환하는 방식을 봅니다.

검증 포인트는 하네스 프롬프트를 채팅 런타임에 넣고 trace에서 `personal_create_schedule`, `personal_list_schedules`, `personal_delete_schedule` 중 어떤 tool이 선택됐는지 확인하는 것입니다. tool 결과 JSON의 `created_schedule`, `schedules`, `deleted`, `structured_request` 필드도 함께 봅니다.

## Week 2 · week02_structure_natural_language_requests.py

### 미션: 자연어 요청을 `StructuredRequest` schema로 변환

학습 목표는 한국어 자연어 입력을 앱이 처리할 수 있는 구조로 바꾸는 것입니다. `StructuredRequest`를 request schema로 보고, `kind`, `title`, `date`, `start_time`, `end_time`, `members`, `priority`, `reason`, `original_text` 필드가 왜 필요한지 확인합니다.

`structured_output_system_prompt`에서는 상대 날짜 기준, 요청 종류, 날짜/시간 형식, 애매한 필드 처리 규칙을 자연어 prompt로 작성합니다. `week02_system_prompt`는 Week 2 대화가 tool 호출 없이 `StructuredRequest`를 최종 structured output으로 반환하도록 정의합니다. `build_week02_agent`에서는 `response_format=StructuredRequest`를 넘겨 LLM structured output 경로를 구성합니다. `extract_schedule_request`는 Week 3 이상에서 DB 저장 tool chain에 재사용할 수 있도록 사용자 prompt를 `base_date`와 `structured_request`가 들어 있는 JSON payload로 감쌉니다.

검증 포인트는 `내일`, `다음 주`, `오후 3시`, `팀원 A/B/C` 같은 표현이 schema 필드로 어떻게 들어가는지 비교하고, 조건문 parser가 아니라 LangChain/OpenAI structured output 결과와 Pydantic 검증이 맞물리는지 확인하는 것입니다.

## Week 3 · week03_build_nanas_logbook.py

### 미션: structured request 저장/조회와 저장 일정 삭제 흐름 확인

학습 목표는 in-memory store와 persistent storage의 차이를 이해하는 것입니다. Week 2에서 대화의 최종 출력으로 확인했던 structured payload를 Week 3에서는 도구 결과로 만든 뒤 `structured_requests`에 저장하고, `kind`에 따라 `schedules`, `todos`, `reminders`에 정규화되는 흐름을 봅니다.

`week03_system_prompt`는 구조화, 저장, 조회, 수정, 삭제 tool chain을 선택하는 규칙을 정의합니다. `save_structured_request`에서는 payload를 SQLite store에 저장하고 저장 결과를 JSON으로 반환합니다. `list_saved_requests`에서는 `kind`, `date_from`, `date_to` 필터가 SQL 조회 조건으로 반영됩니다. `get_saved_request`에서는 `request_id`로 단일 row를 조회합니다.

저장된 개인 일정 삭제 흐름도 함께 확인합니다. `personal_list_saved_schedules`는 앱 DB의 일정 후보를 보여주고, `personal_delete_saved_schedules`는 `schedule_ids`, 날짜, 제목, 시간, 전체 삭제 여부 같은 필터로 저장 일정을 삭제합니다. 자연어 삭제 판단은 agent가 후보 목록을 본 뒤 명시적인 삭제 tool 인자로 넘기도록 둡니다.

검증 포인트는 같은 입력을 여러 번 저장했을 때 request id와 row가 어떻게 달라지는지, 삭제 payload의 `deleted_count`, `filters`, `deleted`가 어떤 의미를 갖는지 확인하는 것입니다.

## Week 4 · week04_retrieve_nanas_memory.py

### 미션: 개인 참고자료 검색과 SQLite 저장 요청 검색 tool 구분

학습 목표는 RAG를 "검색한 근거를 답변 재료로 붙이는 구조"로 이해하는 것입니다. Week 4의 대표 흐름은 Agent가 질문 성격에 따라 `search_personal_references`와 `search_saved_requests` 중 필요한 tool을 고르고, ChromaDB 참고자료 hit 또는 SQLite 저장 요청 row를 답변 근거로 쓰는 방식입니다.

`week04_system_prompt`는 개인 참고자료 검색과 저장 요청 검색의 역할을 구분합니다. `search_personal_references`는 `query`, `top_k` 조건으로 ChromaDB collection에 저장된 개인 참고자료를 OpenAI embedding 기반으로 검색하고 top-level `hits`를 반환합니다. `search_saved_requests`는 `query`, `top_k` 조건으로 Week 3 SQLite `structured_requests` row를 검색하고 top-level `rows`를 반환합니다.

`add_personal_reference`는 개인 참고자료를 추가할 때만 사용합니다. 기존 통합 검색 `search_nana_memory`는 앱 compatibility helper로 남겨 두지만, course repo 기준 agent prompt와 golden harness는 `search_personal_references`, `search_saved_requests`를 우선합니다.

구현 순서는 단순하게 유지합니다. 먼저 ChromaDB 개인 참고자료 검색 결과를 `hits` 배열로 바꾸고, 그 다음 SQLite 저장 요청 검색 결과를 `rows` 배열로 바꿉니다. 저장소 구현은 역할별로 `fixed/app_store.py`, `fixed/external_people_store.py`, `fixed/reference_store.py`에 나뉘어 있으며, Week 4 실습 구현은 `student_parts/week04_retrieve_nanas_memory.py` 안에서 진행합니다.

실습 전 `.env`에 실제 `PROXY_TOKEN`이 필요합니다. 개인 참고자료 검색은 `EMBEDDING_PROXY_URL`의 OpenAI 호환 embedding API를 사용하며, 모델명은 `OPENAI_EMBEDDING_MODEL` 값으로 정합니다. compatibility helper인 `search_nana_memory`의 `reference_backend` 필드에서 `vector_store=chromadb`, `embedding_provider=openai`를 확인할 수 있습니다.

검증 포인트는 `search_personal_references`가 `hits`를, `search_saved_requests`가 `rows`를 top-level payload로 반환하는지, trace에서 두 tool 중 어떤 tool이 왜 호출됐는지 확인하는 것입니다.

## Week 5 · week05_load_kanas_past_conversations.py

### 미션: 외부 SQLite/MCP 기반 이전 대화와 멤버 일정 수집

학습 목표는 agent 코드가 외부 DB를 직접 뒤지지 않고 tool interface를 통해 이전 대화와 멤버 일정을 읽는 흐름을 이해하는 것입니다.

`week05_system_prompt`는 이전 대화 검색, 메시지 로드, 일정 추출, 멤버 일정 수집 tool의 사용 조건을 정의합니다. `search_previous_conversations`는 외부 SQLite 데이터베이스에서 이전 대화를 검색합니다. `load_conversation_messages`는 `conversation_id`로 특정 대화의 메시지를 시간순으로 불러옵니다. `extract_schedules_from_history`는 멤버 이름과 날짜 범위로 외부 대화 기록에 저장된 일정을 추출합니다.

`collect_member_schedules`는 Week 1의 내 개인 일정과 Week 5의 외부 멤버 일정을 합쳐 그룹 조율용 busy-time 목록을 만듭니다. `load_langchain_mcp_tools`와 `load_langchain_mcp_tools_sync`는 local MCP server에서 LangChain tool 목록을 불러오는 adapter 흐름을 보여줍니다. `mcp_server/sqlite_mcp_server.py`의 `@mcp.tool` 함수는 학생 구현 대상이 아니라 wrapper tool이 호출하는 기준 구현으로 유지합니다.

검증 포인트는 `member_names`, `date_from`, `date_to`를 바꿨을 때 외부 대화 row와 일정 row가 어떻게 달라지는지, `collect_member_schedules`의 `members`와 `rows`가 그룹 조율에 필요한 입력을 갖추는지 확인하는 것입니다.

## Week 6 · week06_kanamate_decides_schedule.py

### 미션: Nana/Kana sub-agent와 supervisor routing으로 최종 일정 결정 payload 생성

학습 목표는 multi-agent routing을 역할 분리로 이해하는 것입니다. `nana_agent`는 개인 일정, 저장, 개인 RAG 흐름을 담당하고, `kana_agent`는 여러 사람의 일정 조율을 담당합니다.

`nana_system_prompt`, `kana_system_prompt`, `supervisor_system_prompt`는 각 agent가 어떤 tool chain을 고르는지 안내합니다. `nana_tools`는 Week 4까지의 개인 도구를 공개하고, `kana_tools`는 `extract_schedule_request`, 외부 대화 검색, 멤버 일정 수집, `find_common_available_slots`, `decide_final_slot`을 공개합니다. `supervisor_tools`는 `nana_agent`, `kana_agent` 위임 도구만 노출합니다.

`kana_agent`는 외부 대화와 멤버 일정을 확인한 뒤 `find_common_available_slots`로 후보를 계산하고, 선택한 후보를 `decide_final_slot`에 명시해 최종 `final_slot`, `reason`, `candidates` payload를 반환합니다.

검증 포인트는 supervisor trace에서 어떤 agent가 선택됐는지, 하위 agent trace에 `search_previous_conversations`, `extract_schedules_from_history`, `find_common_available_slots`, `decide_final_slot`이 어떤 순서로 호출됐는지, 최종 payload의 `final_slot`, `reason`, `candidates`가 도구 결과와 일치하는지 확인하는 것입니다.

## 주차별 미션 진행 템플릿

| 구간 | 시간 | 활동 |
| --- | ---: | --- |
| Concept | 20분 | 이번 Week의 핵심 개념과 데이터 흐름을 소개합니다. |
| Walkthrough | 40분 | 기준 코드를 함께 읽고 각 파일 최상단 구현 가이드와 핵심 `@tool` TODO 범위를 확인합니다. |
| Experiment | 40분 | 입력값, 조건, payload 필드를 바꿔 결과를 관찰합니다. |
| Check | 20분 | 앱 화면, trace, JSON payload, test 중 하나로 동작을 확인합니다. |

## 검증 기준

- Week 1-2도 채팅 런타임 trace에서 LLM이 고른 tool과 JSON payload 모양을 먼저 확인합니다.
- Week 3 이후는 API key 없이 통과하는 `./run.sh --test`를 기본 자동 검증 기준으로 사용합니다.
- Week 6 마지막에는 `./run.sh --golden`으로 전체 scenario가 깨지지 않았는지 확인합니다.

## 강사용 준비물

- 강사용 기준본은 실제 OpenAI/SQLite/ChromaDB 경로가 동작하는 완성본으로 유지하고, 학생용 repo와 Week 1-6 branch는 별도로 관리합니다.
- 학생용 branch에서는 `student_parts/`의 주차별 핵심 `@tool` 함수 구현부가 각 실습의 구현 단위가 됩니다.
- 수업 전 `./run.sh --test`로 기준본의 오프라인 검증이 통과하는지 확인합니다.
- Week 2와 Week 4의 실제 structured output/embedding 검증은 프록시 서버를 통해 모델 API를 호출하므로, 수업 전 `.env`의 `PROXY_TOKEN`을 확인한 뒤 `./run.sh --integration-test`를 실행합니다.
- Week 3 이후에는 DB row가 누적될 수 있으므로 수업용 DB를 초기화하거나 복사본을 준비합니다.
