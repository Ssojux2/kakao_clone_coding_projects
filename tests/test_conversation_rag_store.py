from __future__ import annotations

from uuid import uuid4

from fixed.app_store import AppSQLiteStore
from fixed.conversation_rag_store import ConversationRAGStore


class FakeEmbeddingFunction:
    def name(self) -> str:
        return "fake_conversation_embedding"

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
        collection_name=f"test-conversation-rag-{uuid4().hex}",
    )


def test_conversation_rag_store_syncs_upserts_skips_and_deletes(tmp_path) -> None:
    sqlite_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    rag_store = conversation_rag_store(tmp_path)
    first_conversation_id = sqlite_store.create_conversation("첫 대화")["conversation_id"]
    sqlite_store.append_message(first_conversation_id, "user", "검은색 양 이야기를 했다.")
    second_conversation_id = sqlite_store.create_conversation("둘째 대화")["conversation_id"]
    sqlite_store.append_message(second_conversation_id, "user", "파란 컵 이야기를 했다.")

    first_sync = rag_store.sync_from_sqlite(sqlite_store)
    second_sync = rag_store.sync_from_sqlite(sqlite_store)
    sqlite_store.append_message(first_conversation_id, "assistant", "검은색 양으로 기억해둘게요.")
    third_sync = rag_store.sync_from_sqlite(sqlite_store)
    sqlite_store.delete_conversation(second_conversation_id)
    fourth_sync = rag_store.sync_from_sqlite(sqlite_store)

    assert first_sync == {"upserted": 2, "skipped": 0, "deleted": 0, "total": 2}
    assert second_sync == {"upserted": 0, "skipped": 2, "deleted": 0, "total": 2}
    assert third_sync == {"upserted": 1, "skipped": 1, "deleted": 0, "total": 2}
    assert fourth_sync == {"upserted": 0, "skipped": 1, "deleted": 1, "total": 1}
    assert rag_store.collection.count() == 1


def test_conversation_rag_store_searches_archived_conversations(tmp_path) -> None:
    sqlite_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    rag_store = conversation_rag_store(tmp_path)
    conversation_id = sqlite_store.create_conversation("보관된 양 정보")["conversation_id"]
    sqlite_store.append_message(conversation_id, "user", "보관키워드 양은 초록색이다.")
    sqlite_store.archive_conversation(conversation_id)

    sync = rag_store.sync_from_sqlite(sqlite_store)
    hits = rag_store.search(query="보관키워드", top_k=3)

    assert sync["upserted"] == 1
    assert hits[0]["conversation_id"] == conversation_id
    assert hits[0]["status"] == "archived"
    assert "보관키워드 양은 초록색이다." in hits[0]["content"]


def test_conversation_rag_store_search_can_target_one_conversation(tmp_path) -> None:
    sqlite_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    rag_store = conversation_rag_store(tmp_path)
    first_conversation_id = sqlite_store.create_conversation("첫 대상")["conversation_id"]
    sqlite_store.append_message(first_conversation_id, "user", "공통키워드 첫 번째 대화다.")
    second_conversation_id = sqlite_store.create_conversation("둘째 대상")["conversation_id"]
    sqlite_store.append_message(second_conversation_id, "user", "공통키워드 두 번째 대화다.")
    rag_store.sync_from_sqlite(sqlite_store)

    hits = rag_store.search(query="공통키워드", top_k=5, conversation_id=second_conversation_id)

    assert hits
    assert {hit["conversation_id"] for hit in hits} == {second_conversation_id}
    assert "두 번째 대화" in hits[0]["content"]


def test_conversation_rag_store_search_excludes_current_conversation(tmp_path) -> None:
    sqlite_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    rag_store = conversation_rag_store(tmp_path)
    source_conversation_id = sqlite_store.create_conversation("과거 양 정보")["conversation_id"]
    sqlite_store.append_message(source_conversation_id, "user", "내 양은 검은색이다.")
    current_conversation_id = sqlite_store.create_conversation("현재 양 질문")["conversation_id"]
    sqlite_store.append_message(current_conversation_id, "user", "내 양은 무슨 색이야?")
    rag_store.sync_from_sqlite(sqlite_store)

    hits = rag_store.search(query="양", top_k=5, exclude_conversation_id=current_conversation_id)

    assert hits
    assert all(hit["conversation_id"] != current_conversation_id for hit in hits)
    assert any(hit["conversation_id"] == source_conversation_id for hit in hits)
