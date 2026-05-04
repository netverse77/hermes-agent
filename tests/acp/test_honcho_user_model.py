"""Tests for the experimental/honchoUserModel ACP extension method.

The method surfaces Hermes' Honcho user-modelling output read-only over the
long-lived ACP stdio session so the Paperclip TS layer can fold a peer
profile into heartbeat-context without spawning a Python process per
heartbeat.

Mirrors the COG-134 ``experimental/factSearch`` test pattern.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from acp.exceptions import RequestError

from acp_adapter.server import HermesACPAgent
from acp_adapter.session import SessionManager


@pytest.fixture()
def agent_with_lookup():
    """HermesACPAgent factory taking a user-model lookup callable."""
    def _make(lookup):
        manager = SessionManager(agent_factory=lambda: MagicMock(name="MockAIAgent"))
        return HermesACPAgent(
            session_manager=manager,
            honcho_user_model_lookup=lookup,
        )

    return _make


@pytest.fixture()
def agent(agent_with_lookup):
    """Agent backed by an in-memory dict of peer profiles."""
    profiles = {
        "user-42": {
            "userId": "user-42",
            "card": ["prefers concise responses", "expert in distributed systems"],
            "representation": "Senior backend engineer working on Cogni OS.",
        },
    }
    return agent_with_lookup(lambda user_id: profiles.get(user_id))


class TestHonchoUserModel:
    @pytest.mark.asyncio
    async def test_returns_user_model_for_known_peer(self, agent):
        resp = await agent.ext_method(
            "experimental/honchoUserModel",
            {"userId": "user-42"},
        )
        assert "userModel" in resp
        snapshot = resp["userModel"]
        assert snapshot is not None
        assert snapshot["userId"] == "user-42"
        assert snapshot["card"] == [
            "prefers concise responses",
            "expert in distributed systems",
        ]
        assert snapshot["representation"] == (
            "Senior backend engineer working on Cogni OS."
        )

    @pytest.mark.asyncio
    async def test_returns_null_user_model_for_unknown_peer(self, agent):
        resp = await agent.ext_method(
            "experimental/honchoUserModel",
            {"userId": "user-does-not-exist"},
        )
        assert resp == {"userModel": None}

    @pytest.mark.asyncio
    async def test_returns_null_user_model_when_lookup_unconfigured(
        self, agent_with_lookup
    ):
        # When Honcho isn't configured at all, the lookup is None — the
        # method must still return a valid envelope with userModel=null
        # rather than raising, so the Paperclip bridge can degrade
        # gracefully.
        bare_agent = agent_with_lookup(None)
        resp = await bare_agent.ext_method(
            "experimental/honchoUserModel",
            {"userId": "user-42"},
        )
        assert resp == {"userModel": None}

    @pytest.mark.asyncio
    async def test_invalid_user_id_rejected(self, agent):
        with pytest.raises(RequestError) as exc:
            await agent.ext_method("experimental/honchoUserModel", {"userId": ""})
        assert exc.value.code == -32602  # invalid params

    @pytest.mark.asyncio
    async def test_missing_user_id_rejected(self, agent):
        with pytest.raises(RequestError) as exc:
            await agent.ext_method("experimental/honchoUserModel", {})
        assert exc.value.code == -32602

    @pytest.mark.asyncio
    async def test_non_string_user_id_rejected(self, agent):
        with pytest.raises(RequestError) as exc:
            await agent.ext_method(
                "experimental/honchoUserModel", {"userId": 12345}
            )
        assert exc.value.code == -32602

    @pytest.mark.asyncio
    async def test_meta_provenance_does_not_break_call(self, agent):
        # _meta.requestId / _meta.taskId flow in from the ACP envelope (COG-115 H3).
        resp = await agent.ext_method(
            "experimental/honchoUserModel",
            {
                "userId": "user-42",
                "_meta": {"requestId": "req-123", "taskId": "task-abc"},
            },
        )
        assert "userModel" in resp
        assert resp["userModel"]["userId"] == "user-42"

    @pytest.mark.asyncio
    async def test_lookup_exception_returns_null(self, agent_with_lookup):
        # A failing lookup must not surface as a JSON-RPC error — read-only
        # heartbeat-context has to keep working even if Honcho is misbehaving.
        def _boom(user_id: str):
            raise RuntimeError("honcho api down")

        flaky_agent = agent_with_lookup(_boom)
        resp = await flaky_agent.ext_method(
            "experimental/honchoUserModel",
            {"userId": "user-42"},
        )
        assert resp == {"userModel": None}

    @pytest.mark.asyncio
    async def test_payload_passes_through_unmodified(self, agent_with_lookup):
        # The acceptance criterion is that Hermes' Honcho output is
        # returned untouched — the handler MUST NOT reshape, filter, or
        # add fields to whatever the lookup returns (only wrap it in
        # {"userModel": ...}).
        weird_payload = {
            "userId": "user-99",
            "card": ["fact"],
            "representation": "rep",
            "extraField": {"nested": [1, 2, 3]},
            "anotherField": True,
        }
        passthrough_agent = agent_with_lookup(lambda _: weird_payload)
        resp = await passthrough_agent.ext_method(
            "experimental/honchoUserModel",
            {"userId": "user-99"},
        )
        assert resp["userModel"] == weird_payload
