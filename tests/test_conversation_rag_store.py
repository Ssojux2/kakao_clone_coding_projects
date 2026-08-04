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


def test_conversation_rag_store_reembeds_only_the_last_window_on_append(tmp_path) -> None:
    """메시지를 한 건 붙여도 마지막 window 하나만 다시 embedding해야 합니다.

    window가 2개 이상인 대화로 확인합니다. 대화가 한 window 안에 들어가면
    `대화 1건 = 청크 1건`이던 예전 방식과 수치가 같아 회귀를 잡지 못합니다.
    """

    sqlite_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    rag_store = conversation_rag_store(tmp_path)
    conversation_id = sqlite_store.create_conversation("긴 대화")["conversation_id"]
    for index in range(2 * ConversationRAGStore.WINDOW_SIZE):
        sqlite_store.append_message(conversation_id, "user", f"{index}번째 메시지입니다.")

    first_sync = rag_store.sync_from_sqlite(sqlite_store)
    sqlite_store.append_message(conversation_id, "user", "마지막에 붙인 메시지입니다.")
    append_sync = rag_store.sync_from_sqlite(sqlite_store)

    assert first_sync == {"upserted": 2, "skipped": 0, "deleted": 0, "total": 2}
    # 새 window가 하나 열리고 가득 찬 window 2개는 그대로 유지됩니다.
    assert append_sync == {"upserted": 1, "skipped": 2, "deleted": 0, "total": 3}


def test_conversation_rag_store_archive_refreshes_metadata_without_reembedding(tmp_path) -> None:
    """보관 상태 변경은 metadata만 갱신하고 다시 embedding하지 않아야 합니다."""

    sqlite_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    rag_store = conversation_rag_store(tmp_path)
    conversation_id = sqlite_store.create_conversation("보관할 대화")["conversation_id"]
    sqlite_store.append_message(conversation_id, "user", "보관 전에 남긴 메시지입니다.")
    rag_store.sync_from_sqlite(sqlite_store)

    sqlite_store.archive_conversation(conversation_id)
    archive_sync = rag_store.sync_from_sqlite(sqlite_store)
    hits = rag_store.search(query="보관 전에 남긴", top_k=3)

    assert archive_sync == {"upserted": 0, "skipped": 1, "deleted": 0, "total": 1}
    assert hits[0]["status"] == "archived"


def test_conversation_rag_store_reuses_sync_result_when_sqlite_unchanged(tmp_path, monkeypatch) -> None:
    """SQLite가 그대로면 다시 청킹하지 않고 직전 sync 결과를 그대로 씁니다.

    search tool은 호출마다 sync를 먼저 하므로, 바뀐 게 없을 때 대화 전문을 다시 읽고
    Chroma metadata를 전량 조회하는 비용을 없앱니다.
    """

    sqlite_store = AppSQLiteStore(tmp_path / "app.sqlite3")
    rag_store = conversation_rag_store(tmp_path)
    conversation_id = sqlite_store.create_conversation("캐시 확인 대화")["conversation_id"]
    sqlite_store.append_message(conversation_id, "user", "캐시 확인용 메시지입니다.")
    rag_store.sync_from_sqlite(sqlite_store)

    chunk_calls: list[str] = []
    original_conversation_chunks = rag_store._conversation_chunks
    monkeypatch.setattr(
        rag_store,
        "_conversation_chunks",
        lambda store: (chunk_calls.append("called"), original_conversation_chunks(store))[1],
    )
    cached_sync = rag_store.sync_from_sqlite(sqlite_store)
    sqlite_store.append_message(conversation_id, "user", "메시지를 하나 더 붙입니다.")
    changed_sync = rag_store.sync_from_sqlite(sqlite_store)

    assert cached_sync == {"upserted": 0, "skipped": 1, "deleted": 0, "total": 1}
    # 캐시가 적중한 호출에서는 청킹을 건너뛰고, 메시지가 붙은 뒤에만 한 번 실행됩니다.
    assert chunk_calls == ["called"]
    assert changed_sync == {"upserted": 1, "skipped": 0, "deleted": 0, "total": 1}


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
