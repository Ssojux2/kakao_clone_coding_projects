from __future__ import annotations

import fixed.config as config_module


def test_load_config_reads_proxy_chat_and_embedding_settings(monkeypatch) -> None:
    monkeypatch.setenv("PROXY_TOKEN", "test-proxy-token")
    monkeypatch.setenv("CHAT_PROXY_URL", "https://chat.example.test/v1")
    monkeypatch.setenv("EMBEDDING_PROXY_URL", "https://embedding.example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "openai/text-embedding-3-small")

    config = config_module.load_config()

    assert config.proxy_token == "test-proxy-token"
    assert config.chat_proxy_url == "https://chat.example.test/v1"
    assert config.embedding_proxy_url == "https://embedding.example.test/v1"
    assert config.openai_model == "openai/gpt-4.1-mini"
    assert config.openai_embedding_model == "openai/text-embedding-3-small"
    assert config.has_openai_key is True


def test_placeholder_proxy_token_is_treated_as_missing(monkeypatch) -> None:
    monkeypatch.setenv("PROXY_TOKEN", config_module.PROXY_TOKEN_PLACEHOLDER)

    config = config_module.load_config()

    assert config.has_openai_key is False
