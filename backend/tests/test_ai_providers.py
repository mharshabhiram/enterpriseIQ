"""
Tests for the AI provider layer (app/ai).

MockEmbeddingProvider/MockLLMProvider are tested directly - pure,
deterministic, offline. OpenAICompatibleEmbeddingProvider/
OpenAICompatibleLLMProvider are tested against a real local HTTP server
(stdlib http.server, bound to 127.0.0.1) rather than mocking httpx - this
exercises the actual request construction (auth header, path, JSON body),
response parsing, and error handling for real. What this *can't* verify is
that the real api.openai.com endpoints behave exactly like our fake server
assumes - that remains unverified in this environment (no network access to
external AI providers), which is exactly why EMBEDDING_PROVIDER=mock and
LLM_PROVIDER=mock exist as real, first-class options.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.ai.factory import get_embedding_provider, get_llm_provider
from app.ai.mock_embedding_provider import MockEmbeddingProvider
from app.ai.mock_llm_provider import MockLLMProvider
from app.ai.openai_embedding_provider import OpenAICompatibleEmbeddingProvider
from app.ai.openai_llm_provider import OpenAICompatibleLLMProvider
from app.utils.errors import EmbeddingProviderError, LLMProviderError

# --- MockEmbeddingProvider ---


async def test_mock_provider_is_deterministic() -> None:
    provider = MockEmbeddingProvider(dimensions=16)
    first = await provider.embed(["hello world"])
    second = await provider.embed(["hello world"])
    assert first == second


async def test_mock_provider_differs_by_text() -> None:
    provider = MockEmbeddingProvider(dimensions=16)
    a, b = await provider.embed(["text one", "text two"])
    assert a != b


async def test_mock_provider_returns_unit_vectors_of_configured_dimension() -> None:
    provider = MockEmbeddingProvider(dimensions=32)
    [vector] = await provider.embed(["some text"])
    assert len(vector) == 32
    norm = sum(v * v for v in vector) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-9)


async def test_mock_provider_preserves_batch_order() -> None:
    provider = MockEmbeddingProvider(dimensions=8)
    texts = ["a", "b", "c"]
    vectors = await provider.embed(texts)
    # re-embedding one at a time must match the batched result at each position
    for text, vector in zip(texts, vectors):
        assert (await provider.embed([text]))[0] == vector


async def test_factory_returns_mock_provider_when_configured(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.factory.settings.embedding_provider", "mock")
    provider = get_embedding_provider()
    assert isinstance(provider, MockEmbeddingProvider)


async def test_factory_raises_on_unknown_provider(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.factory.settings.embedding_provider", "not-a-real-provider")
    with pytest.raises(ValueError):
        get_embedding_provider()


async def test_llm_factory_returns_mock_provider_when_configured(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.factory.settings.llm_provider", "mock")
    provider = get_llm_provider()
    assert isinstance(provider, MockLLMProvider)


async def test_llm_factory_raises_on_unknown_provider(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.factory.settings.llm_provider", "not-a-real-provider")
    with pytest.raises(ValueError):
        get_llm_provider()


# --- MockLLMProvider ---


async def test_mock_llm_provider_returns_default_response() -> None:
    provider = MockLLMProvider()
    response = await provider.generate([{"role": "user", "content": "hi"}])
    assert "mock" in response.lower()


async def test_mock_llm_provider_returns_custom_response() -> None:
    provider = MockLLMProvider(response="a fixed canned answer")
    response = await provider.generate([{"role": "user", "content": "hi"}])
    assert response == "a fixed canned answer"


async def test_mock_llm_provider_records_last_messages_and_call_count() -> None:
    provider = MockLLMProvider()
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]
    await provider.generate(messages)
    assert provider.last_messages == messages
    assert provider.call_count == 1
    await provider.generate(messages)
    assert provider.call_count == 2


# --- OpenAICompatibleEmbeddingProvider, against a real local fake server ---


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    expected_api_key = "test-key-123"
    dimensions = 8

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        texts = body["input"]

        if texts == ["TRIGGER_500"]:
            self._send(500, {"error": "internal server error"})
            return
        if self.headers.get("Authorization") != f"Bearer {self.expected_api_key}":
            self._send(401, {"error": "invalid api key"})
            return

        payload = {
            "data": [{"embedding": [float(i)] * self.dimensions, "index": i} for i, _ in enumerate(texts)],
            "model": body["model"],
        }
        self._send(200, payload)

    def _send(self, status: int, payload: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, format, *args) -> None:  # noqa: A002 - silence test server logging
        pass


@pytest.fixture(scope="module")
def fake_openai_server():
    server = HTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


async def test_openai_provider_round_trip(fake_openai_server: str) -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        api_key="test-key-123", model="fake-model", base_url=fake_openai_server
    )
    vectors = await provider.embed(["hello", "world"])
    assert vectors == [[0.0] * 8, [1.0] * 8]


async def test_openai_provider_empty_input_short_circuits(fake_openai_server: str) -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        api_key="test-key-123", model="fake-model", base_url=fake_openai_server
    )
    assert await provider.embed([]) == []


async def test_openai_provider_raises_on_5xx(fake_openai_server: str) -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        api_key="test-key-123", model="fake-model", base_url=fake_openai_server
    )
    with pytest.raises(EmbeddingProviderError):
        await provider.embed(["TRIGGER_500"])


async def test_openai_provider_raises_on_auth_failure(fake_openai_server: str) -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        api_key="wrong-key", model="fake-model", base_url=fake_openai_server
    )
    with pytest.raises(EmbeddingProviderError):
        await provider.embed(["test"])


async def test_openai_provider_raises_without_api_key(fake_openai_server: str) -> None:
    provider = OpenAICompatibleEmbeddingProvider(api_key="", model="fake-model", base_url=fake_openai_server)
    with pytest.raises(EmbeddingProviderError, match="EMBEDDING_API_KEY"):
        await provider.embed(["test"])


# --- OpenAICompatibleLLMProvider, against a real local fake server ---


class _FakeChatCompletionsHandler(BaseHTTPRequestHandler):
    expected_api_key = "test-llm-key"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        last_user_message = next(
            (m["content"] for m in reversed(body["messages"]) if m["role"] == "user"), ""
        )
        if last_user_message == "TRIGGER_500":
            self._send(500, {"error": "internal server error"})
            return
        if self.headers.get("Authorization") != f"Bearer {self.expected_api_key}":
            self._send(401, {"error": "invalid api key"})
            return
        if last_user_message == "TRIGGER_MALFORMED":
            self._send(200, {"unexpected": "shape"})
            return

        payload = {
            "choices": [{"message": {"role": "assistant", "content": f"echo: {last_user_message}"}}],
            "model": body["model"],
        }
        self._send(200, payload)

    def _send(self, status: int, payload: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, format, *args) -> None:  # noqa: A002
        pass


@pytest.fixture(scope="module")
def fake_chat_server():
    server = HTTPServer(("127.0.0.1", 0), _FakeChatCompletionsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


async def test_llm_provider_round_trip(fake_chat_server: str) -> None:
    provider = OpenAICompatibleLLMProvider(api_key="test-llm-key", model="fake-model", base_url=fake_chat_server)
    response = await provider.generate(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "What is the leave policy?"}]
    )
    assert response == "echo: What is the leave policy?"


async def test_llm_provider_raises_on_5xx(fake_chat_server: str) -> None:
    provider = OpenAICompatibleLLMProvider(api_key="test-llm-key", model="fake-model", base_url=fake_chat_server)
    with pytest.raises(LLMProviderError):
        await provider.generate([{"role": "user", "content": "TRIGGER_500"}])


async def test_llm_provider_raises_on_auth_failure(fake_chat_server: str) -> None:
    provider = OpenAICompatibleLLMProvider(api_key="wrong-key", model="fake-model", base_url=fake_chat_server)
    with pytest.raises(LLMProviderError):
        await provider.generate([{"role": "user", "content": "hello"}])


async def test_llm_provider_raises_on_malformed_response(fake_chat_server: str) -> None:
    provider = OpenAICompatibleLLMProvider(api_key="test-llm-key", model="fake-model", base_url=fake_chat_server)
    with pytest.raises(LLMProviderError):
        await provider.generate([{"role": "user", "content": "TRIGGER_MALFORMED"}])


async def test_llm_provider_raises_without_api_key(fake_chat_server: str) -> None:
    provider = OpenAICompatibleLLMProvider(api_key="", model="fake-model", base_url=fake_chat_server)
    with pytest.raises(LLMProviderError, match="LLM_API_KEY"):
        await provider.generate([{"role": "user", "content": "hello"}])
