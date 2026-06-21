from __future__ import annotations

import json
from uuid import uuid4

import pytest

import student_parts.week04_retrieve_nanas_memory as week04_module
from fixed.app_store import AppSQLiteStore
from fixed.conversation_rag_store import ConversationRAGStore
from fixed.config import CONFIG
from fixed.session_scope import conversation_session_scope


class FakeEmbeddingFunction:
    def name(self) -> str:
        return "fake_week04_conversation_embedding"

    def is_legacy(self) -> bool:
        return True

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in input:
            vector = [0.0] * 32
            for char in str(text):
                if char.isspace():
                    continue
                vector[ord(char) % len(vector)] += 1.0
            norm = sum(value * value for value in vector) ** 0.5 or 1.0
            vectors.append([value / norm for value in vector])
        return vectors

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)


def conversation_rag_store(tmp_path) -> ConversationRAGStore:
    return ConversationRAGStore(
        tmp_path / "chroma",
        embedding_function=FakeEmbeddingFunction(),
        collection_name=f"test-week04-rag-{uuid4().hex}",
    )


def test_week04_search_saved_requests_returns_empty_rows_without_recent_fallback(tmp_path, monkeypatch) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    store.save_structured_request(
        {
            "kind": "todo",
            "title": "검색되면 안 되는 최근 할 일",
            "date": "2026-05-20",
            "priority": "low",
            "reason": "fallback 방지 테스트",
        }
    )
    monkeypatch.setattr(week04_module, "SQLITE_STORE", store)

    result = json.loads(week04_module.search_saved_requests.invoke({"query": "절대없는검색어", "top_k": 3}))

    assert result["rows"] == []


def test_week04_search_conversation_messages_finds_app_chat_messages(tmp_path, monkeypatch) -> None:
    store = AppSQLiteStore(tmp_path / "app.sqlite3")
    rag_store = conversation_rag_store(tmp_path)
    source_conversation_id = store.create_conversation("양 정보")["conversation_id"]
    store.append_message(source_conversation_id, "user", "내가 가지고 있는 양은 검은색 양이다.")
    store.append_message(source_conversation_id, "assistant", "검은색 양으로 기억해둘게요.")
    current_conversation_id = store.create_conversation("양 색 질문")["conversation_id"]
    store.append_message(current_conversation_id, "user", "내가 가지고 있는 양의 색은?")
    store.append_message(
        current_conversation_id,
        "assistant",
        "양의 색에 대해 구체적으로 어떤 정보를 원하시는지 알려주세요.",
    )
    monkeypatch.setattr(week04_module, "SQLITE_STORE", store)
    monkeypatch.setattr(week04_module, "CONVERSATION_RAG_STORE", rag_store)

    saved_result = json.loads(week04_module.search_saved_requests.invoke({"query": "양", "top_k": 5}))
    with conversation_session_scope(current_conversation_id):
        message_result = json.loads(
            week04_module.search_conversation_messages.invoke(
                {"query": "양", "top_k": 5}
            )
        )

    assert saved_result["rows"] == []
    assert message_result["ok"] is True
    assert message_result["tool_name"] == "search_conversation_messages"
    assert message_result["rows"] == message_result["hits"]
    assert message_result["sync"]["upserted"] == 2
    assert "SQLite 대화 RAG 검색 결과" in message_result["context"]
    assert "내가 가지고 있는 양은 검은색 양이다." in message_result["context"]
    assert any(
        row["conversation_id"] == source_conversation_id
        and "내가 가지고 있는 양은 검은색 양이다." in row["content"]
        for row in message_result["rows"]
    )
    assert all(row["conversation_id"] != current_conversation_id for row in message_result["rows"])


@pytest.mark.integration
def test_week04_course_rag_tools_use_real_chroma_openai_and_sqlite() -> None:
    assert CONFIG.has_openai_key, "Week 4는 실제 embedding 호출이 필요합니다. .env에 PROXY_TOKEN을 설정하세요."

    token = f"week4-real-{uuid4().hex[:8]}"
    reference_text = f"{token} 중요한 회의는 오전 10시에서 12시 사이에 잡는 것을 선호한다."
    schedule_title = f"{token} 팀 회의"
    conversation_id = week04_module.SQLITE_STORE.create_conversation(f"{token} 대화 RAG")["conversation_id"]
    week04_module.SQLITE_STORE.append_message(conversation_id, "user", f"{token} 내 노트북 파우치는 회색이다.")

    added = json.loads(
        week04_module.add_personal_reference.invoke(
            {
                "title": f"{token} 회의 선호",
                "content": reference_text,
                "tags": ["meeting", "preference", token],
            }
        )
    )
    week04_module.SQLITE_STORE.save_structured_request(
        {
            "kind": "group_schedule",
            "title": schedule_title,
            "date": "2026-05-21",
            "start_time": "15:00",
            "end_time": "16:00",
            "members": ["민준", "서연"],
            "reason": "Week 4 실제 Chroma/OpenAI 테스트",
            "original_text": schedule_title,
        }
    )

    reference_result = json.loads(week04_module.search_personal_references.invoke({"query": token, "top_k": 5}))
    saved_result = json.loads(week04_module.search_saved_requests.invoke({"query": token, "top_k": 10}))
    conversation_result = json.loads(week04_module.search_conversation_messages.invoke({"query": token, "top_k": 5}))
    legacy_result = json.loads(
        week04_module.search_nana_memory.invoke(
            {
                "query": token,
                "date_from": "2026-05-21",
                "date_to": "2026-05-21",
                "attendee": "민준",
                "limit": 10,
            }
        )
    )

    backend = legacy_result["reference_backend"]
    assert added["reference_backend"] == backend
    assert backend["vector_store"] == "chromadb"
    assert backend["embedding_provider"] == "openai"
    assert backend["embedding_model"] == CONFIG.openai_embedding_model
    assert any(token in hit["content"] or token in json.dumps(hit["metadata"], ensure_ascii=False) for hit in reference_result["hits"])
    assert any(row["title"] == schedule_title for row in saved_result["rows"])
    assert conversation_result["rag_backend"]["vector_store"] == "chromadb"
    assert any(hit["conversation_id"] == conversation_id for hit in conversation_result["hits"])
    assert token in conversation_result["context"]
    assert any(token in hit["content"] or token in hit["title"] for hit in legacy_result["reference_hits"])
    assert any(chunk["title"] == schedule_title for chunk in legacy_result["schedule_chunks"])
    assert token in legacy_result["context"]
