from __future__ import annotations

from uuid import uuid4

import fixed.reference_store as reference_store_module
from fixed.reference_store import PersonalReferenceStore


class CountingEmbeddingFunction:
    """embedding 호출 횟수를 세는 테스트용 embedding function입니다."""

    def __init__(self) -> None:
        self.embedded_documents: list[str] = []

    def name(self) -> str:
        return "counting_reference_embedding"

    def is_legacy(self) -> bool:
        return True

    def __call__(self, input: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in input:
            self.embedded_documents.append(str(text))
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


def personal_reference_store(tmp_path, monkeypatch) -> tuple[PersonalReferenceStore, CountingEmbeddingFunction]:
    """실제 embedding 호출 없이 동작하는 참고자료 저장소를 만듭니다."""

    embedding_function = CountingEmbeddingFunction()
    monkeypatch.setattr(
        reference_store_module,
        "OpenAIEmbeddingFunction",
        lambda **kwargs: embedding_function,
    )
    monkeypatch.setattr(
        PersonalReferenceStore,
        "COLLECTION_NAME",
        f"test-personal-reference-{uuid4().hex}",
    )
    store = PersonalReferenceStore(tmp_path / "chroma")
    embedding_function.embedded_documents.clear()
    return store, embedding_function


def test_personal_reference_store_skips_reembedding_same_reference(tmp_path, monkeypatch) -> None:
    """같은 참고자료를 반복 저장해도 다시 embedding하지 않아야 합니다.

    reference_id가 내용 기반 해시이므로 agent가 같은 내용을 여러 번 저장해도
    중복 청크와 중복 검색 결과가 생기지 않습니다.
    """

    store, embedding_function = personal_reference_store(tmp_path, monkeypatch)
    before_count = store.collection.count()

    first = store.add_personal_reference("집중 시간", "오전 10시에서 12시 사이에 집중이 잘 된다.", ["preference"])
    second = store.add_personal_reference("집중 시간", "오전 10시에서 12시 사이에 집중이 잘 된다.", ["preference"])

    assert first["reference_id"] == second["reference_id"]
    assert first["already_exists"] is False
    assert second["already_exists"] is True
    assert store.collection.count() == before_count + 1
    assert len(embedding_function.embedded_documents) == 1


def test_personal_reference_store_keeps_different_references_apart(tmp_path, monkeypatch) -> None:
    """내용이 다르면 별개 참고자료로 저장돼야 합니다."""

    store, embedding_function = personal_reference_store(tmp_path, monkeypatch)
    before_count = store.collection.count()

    first = store.add_personal_reference("집중 시간", "오전에 집중이 잘 된다.", ["preference"])
    second = store.add_personal_reference("집중 시간", "오후에 집중이 잘 된다.", ["preference"])

    assert first["reference_id"] != second["reference_id"]
    assert second["already_exists"] is False
    assert store.collection.count() == before_count + 2
    assert len(embedding_function.embedded_documents) == 2


def test_personal_reference_store_treats_tag_order_as_same_reference(tmp_path, monkeypatch) -> None:
    """태그 순서만 다른 저장은 같은 참고자료로 봐야 합니다."""

    store, _ = personal_reference_store(tmp_path, monkeypatch)

    first = store.add_personal_reference("회의 규칙", "회의는 60분 이하로 잡는다.", ["team", "meeting"])
    second = store.add_personal_reference("회의 규칙", "회의는 60분 이하로 잡는다.", ["meeting", "team"])

    assert first["reference_id"] == second["reference_id"]
    assert second["already_exists"] is True
