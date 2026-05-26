# Kanana Agent 6주 / 12차시 커리큘럼

이 문서는 1주차당 2번의 수업과 확장 미션을 운영하기 위한 강사용 수업 계획입니다. 용어는 실제 개발 수업처럼 사용하되, 학습 활동은 초보 학습자가 작은 단위로 따라오도록 설계합니다.

## 운영 기준

- 대상 수준: 중학교 1학년 수준의 Python 초보 학습자
- 용어 수준: 대학생/초급 개발자 기준
- 수업 시간: 차시당 120분
- 수업 방식: 개념 소개, 기준 코드 따라가기, 입력값 바꿔 실험하기, 결과 확인하기
- 과제 방식: 기본 구현 반복이 아니라 기존 기능에 작은 확장 하나 추가하기

## Week 1 · Stateful CRUD Tool

### 1차시: CRUD tool 구현

학습 목표는 `create`, `read`, `delete`가 코드에서 어떤 데이터 이동으로 나타나는지 확인하는 것입니다. `PERSONAL_SCHEDULES` 리스트를 in-memory store로 보고, 일정 하나를 dict payload로 만들어 추가합니다.

진행 순서는 `personal_create_schedule`에서 payload 구조를 확인하고, `personal_list_schedules`에서 날짜 필터 조건을 따라가며, `personal_delete_schedule`에서 리스트를 다시 만드는 방식을 관찰합니다. 학생 활동은 title/date/time 값을 바꿔 tool 결과가 어떻게 달라지는지 확인하는 데 둡니다.

### 2차시: JSON payload와 CRUD test 읽기

Week 1의 CRUD test는 tool이 저장한 JSON 파일을 읽는 것이 아닙니다. tool은 JSON 문자열을 반환하고, 테스트는 `json.loads()`로 문자열을 dict로 바꾼 뒤 `created_schedule`, `schedules`, `deleted` 필드를 검증합니다.

수업에서는 JSON serialization/deserialization, assertion, test fixture 역할을 다룹니다. 학생들은 테스트에서 `schedule_id`가 어떻게 만들어지고 삭제 검증에 다시 쓰이는지 따라 읽습니다.

### 확장 미션

- `personal_update_schedule` tool을 추가해 title 또는 time을 수정합니다.
- 날짜별 일정 개수를 반환하는 helper를 추가합니다.

## Week 2 · Structured Output Schema

### 1차시: schema와 classification

학습 목표는 자연어 입력을 앱이 처리할 수 있는 구조로 바꾸는 것입니다. `StructuredRequest`를 하나의 request schema로 보고, `kind`, `title`, `date`, `start_time`, `members` 필드가 왜 필요한지 확인합니다.

진행은 예시 문장 하나를 넣고, 어떤 키워드가 `personal_schedule`, `group_schedule`, `todo`, `reminder`, `unknown` 분류에 영향을 주는지 관찰합니다.

### 2차시: LLM structured output 실험

학생들은 입력 문장을 조금씩 바꿔가며 classification과 extraction 결과를 비교합니다. `내일`, `다음 주`, `오후 3시`, `팀원 A/B/C` 같은 표현이 어떤 필드로 바뀌는지 확인합니다.

기본 검증은 LangChain/OpenAI structured output 결과와 Pydantic schema가 맞물리는지 확인하는 방식으로 진행합니다.

### 확장 미션

- 날짜/시간 표현 3개를 추가 지원합니다.
- 예: `모레`, `아침`, `저녁`, `점심 이후`, `이번 주 금요일`

## Week 3 · SQLite Persistence

### 1차시: structured payload 저장

학습 목표는 in-memory store와 persistent storage의 차이를 이해하는 것입니다. Week 2의 structured payload가 `structured_requests`에 저장되고, kind에 따라 `schedules`, `todos`, `reminders`에 정규화되는 흐름을 봅니다.

학생 활동은 같은 입력을 여러 번 저장했을 때 request id와 row가 어떻게 달라지는지 관찰하는 것입니다.

### 2차시: SQL filtering과 row 조회

`kind`, `date_from`, `date_to` 필터가 SQL `WHERE` 조건으로 바뀌는 흐름을 확인합니다. `get_saved_request`는 단일 row 조회, `list_saved_requests`는 목록 조회라는 차이를 구분합니다.

### 확장 미션

- 특정 날짜의 todo만 조회하는 helper를 추가합니다.
- 조회 결과에 `count` 필드를 함께 반환합니다.

## Week 4 · Agentic RAG

### 1차시: reference search와 saved request search

학습 목표는 RAG를 "검색한 근거를 답변 재료로 붙이는 구조"로 이해하는 것입니다. Chroma reference search와 SQLite saved request search를 각각 실행하고, 두 검색 결과의 차이를 확인합니다.

### 2차시: RAG context assembly

`build_rag_context`가 reference hits와 SQLite hits를 하나의 context 문자열로 합치는 과정을 읽습니다. 학생들은 검색어를 바꾸면서 어떤 hit가 context에 들어가는지 확인합니다.

### 확장 미션

- 개인 참고자료 2개를 추가하고 검색 결과를 비교합니다.
- 태그 필터 또는 검색 결과 개수 제한을 조정합니다.

## Week 5 · MCP Tool Adapter

### 1차시: external SQLite를 tool interface로 접근

학습 목표는 agent 코드가 외부 DB를 직접 뒤지지 않고 MCP tool interface를 통해 접근하는 방식을 이해하는 것입니다. `search_previous_conversations`, `load_conversation_messages`, `extract_schedules_from_history`의 역할을 구분합니다.

### 2차시: MCP adapter와 trace 확인

LangChain MCP adapter가 local MCP server에서 tool 목록을 불러오는 흐름을 확인합니다. trace에서 `mcp_tool_call`과 `mcp_tool_result`를 읽으며 외부 대화 검색과 일정 추출을 연결합니다.

### 확장 미션

- 외부 멤버 1명과 일정 2개를 seed 데이터에 추가합니다.
- `load_conversation_messages` 결과를 더 읽기 좋은 payload로 정리합니다.

## Week 6 · Supervisor Routing and Sub-agents

### 1차시: sub-agent 책임 분리

학습 목표는 multi-agent routing을 역할 분리로 이해하는 것입니다. `nana_agent`는 개인 일정과 개인 RAG를 담당하고, `kana_agent`는 팀 일정 조율을 담당합니다.

학생들은 같은 요청이라도 개인 일정 요청과 그룹 일정 요청이 서로 다른 agent로 위임되는 이유를 확인합니다.

### 2차시: slot calculation과 final decision

`collect_member_schedules`로 Week 1 개인 일정과 Week 5 외부 멤버 일정을 모은 뒤, Kana가 가능한 시간을 판단해 `propose_group_schedule`에 `selected_slot`을 전달합니다. supervisor trace에서 어떤 agent가 선택됐고, 최종 payload의 `status`, `selected_slot`, `reason`이 어떻게 만들어지는지 확인합니다.

### 확장 미션

- 점심시간 `12:00-13:00`을 후보에서 제외합니다.
- 회의 길이를 30분/60분 중 선택할 수 있게 합니다.
- 오전 선호 scoring을 더 강하게 반영합니다.

## 차시별 공통 진행 템플릿

| 구간 | 시간 | 활동 |
| --- | ---: | --- |
| Concept | 20분 | 오늘의 핵심 용어와 데이터 흐름을 소개합니다. |
| Walkthrough | 40분 | 기준 코드를 함께 읽고 TODO 단위로 따라 구현합니다. |
| Experiment | 40분 | 입력값, 조건, payload 필드를 바꿔 결과를 관찰합니다. |
| Check | 20분 | 앱 화면, trace, JSON payload, test 중 하나로 동작을 확인합니다. |

## 검증 기준

- Week 1-2는 함수 실행 결과와 JSON payload 모양을 먼저 확인합니다.
- Week 3 이후는 `./run.sh --test`를 자동 검증 기준으로 사용합니다.
- Week 6 마지막에는 `./run.sh --golden`으로 전체 scenario가 깨지지 않았는지 확인합니다.
- 확장 미션은 기존 테스트를 깨지 않고, 새 예시 입력 1개가 의도대로 동작하면 통과로 봅니다.

## 강사용 준비물

- 학생용 배포본에서는 `# [REFERENCE ANSWER]` 아래 구현을 가리고 TODO만 남깁니다.
- 수업 전 `./run.sh --test`로 기준본이 통과하는지 확인합니다.
- Week 3 이후에는 DB row가 누적될 수 있으므로 수업용 DB를 초기화하거나 복사본을 준비합니다.
- 어려운 용어는 낮추지 말고, payload, table row, trace 화면과 바로 연결해 설명합니다.
