"""Tests for the experimental/factSearch ACP extension method.

The method wraps ``FactRetriever.search`` and is exposed via the long-lived
ACP stdio session so the Paperclip TS layer can pull memory snippets without
spawning a new Python process per heartbeat.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from acp.exceptions import RequestError

from acp_adapter.server import HermesACPAgent
from acp_adapter.session import SessionManager
from plugins.memory.holographic.retrieval import FactRetriever
from plugins.memory.holographic.store import MemoryStore


@pytest.fixture()
def memory_store(tmp_path):
    """Fresh on-disk MemoryStore with a single seeded fact."""
    db_path = tmp_path / "memory_store.db"
    store = MemoryStore(db_path=db_path)
    store.add_fact(
        content="hermes-local adapter wires Hermes facts into Paperclip",
        category="general",
        tags="hermes paperclip bridge",
    )
    return store


@pytest.fixture()
def agent(memory_store):
    """HermesACPAgent backed by a real FactRetriever over a temp store."""
    manager = SessionManager(agent_factory=lambda: MagicMock(name="MockAIAgent"))
    return HermesACPAgent(
        session_manager=manager,
        fact_retriever_factory=lambda: FactRetriever(memory_store),
    )


class TestFactSearch:
    @pytest.mark.asyncio
    async def test_returns_snippet_shape_for_match(self, agent):
        resp = await agent.ext_method(
            "experimental/factSearch",
            {"query": "hermes paperclip"},
        )
        assert "snippets" in resp
        assert isinstance(resp["snippets"], list)
        assert len(resp["snippets"]) >= 1
        snippet = resp["snippets"][0]
        assert set(snippet.keys()) == {"factId", "content", "score", "createdAt"}
        assert isinstance(snippet["factId"], str) and snippet["factId"]
        assert isinstance(snippet["content"], str) and snippet["content"]
        assert isinstance(snippet["score"], float)
        assert isinstance(snippet["createdAt"], str) and snippet["createdAt"]

    @pytest.mark.asyncio
    async def test_empty_snippets_for_no_hit(self, agent):
        resp = await agent.ext_method(
            "experimental/factSearch",
            {"query": "completely-unrelated-token-zzzqqq"},
        )
        assert resp == {"snippets": []}

    @pytest.mark.asyncio
    async def test_top_k_bounds_results(self, agent, memory_store):
        # Seed a few more facts so topK actually bounds the result list.
        memory_store.add_fact(content="hermes second fact for bridge", tags="hermes")
        memory_store.add_fact(content="hermes third fact for bridge", tags="hermes")
        memory_store.add_fact(content="hermes fourth fact for bridge", tags="hermes")

        resp = await agent.ext_method(
            "experimental/factSearch",
            {"query": "hermes", "topK": 2},
        )
        assert len(resp["snippets"]) <= 2

    @pytest.mark.asyncio
    async def test_default_top_k_is_three(self, agent, memory_store):
        for i in range(5):
            memory_store.add_fact(
                content=f"hermes default-topk fact #{i}", tags="hermes"
            )
        resp = await agent.ext_method(
            "experimental/factSearch",
            {"query": "hermes"},
        )
        assert len(resp["snippets"]) <= 3

    @pytest.mark.asyncio
    async def test_invalid_query_rejected(self, agent):
        with pytest.raises(RequestError) as exc:
            await agent.ext_method("experimental/factSearch", {"query": ""})
        assert exc.value.code == -32602  # invalid params

    @pytest.mark.asyncio
    async def test_meta_provenance_does_not_break_call(self, agent):
        # _meta.requestId / _meta.taskId flow in from the ACP envelope (COG-115 H3).
        # The handler must accept them and still return a valid snippet payload.
        resp = await agent.ext_method(
            "experimental/factSearch",
            {
                "query": "hermes",
                "topK": 1,
                "_meta": {"requestId": "req-123", "taskId": "task-abc"},
            },
        )
        assert "snippets" in resp

    @pytest.mark.asyncio
    async def test_unknown_extension_method_raises_method_not_found(self, agent):
        with pytest.raises(RequestError) as exc:
            await agent.ext_method("experimental/unknownMethod", {})
        assert exc.value.code == -32601
