# hermes-agent ACP adapter

This package exposes the Hermes agent over the [Agent Client Protocol](https://github.com/zed-industries/agent-client-protocol)
(ACP) so editors like Zed and bridges like Paperclip can drive Hermes through a
long-lived stdio session instead of forking the CLI per turn.

The standard surface (`initialize`, `prompt`, `new_session`, `load_session`,
`fork_session`, `set_session_model`, ...) follows the ACP spec. The methods
below are **non-standard extensions** — they are intentionally namespaced so
ACP clients that don't know about them get a normal JSON-RPC `-32601 Method
not found` response.

## Extension methods

ACP routes any wire-level method whose name starts with `_` to
`Agent.ext_method(name, params)`, with the leading underscore stripped. The
method names listed here are the post-strip names; on the wire they appear as
`_experimental/factSearch` etc.

### `experimental/factSearch` — Paperclip memory bridge

**Status:** experimental, **Paperclip-bridge-specific**. Not part of the ACP
spec; the `experimental/` prefix advertises that the shape may change without
a major version bump and that other ACP clients should not rely on it.

Wraps `FactRetriever.search` so the Paperclip TS layer can pull memory
snippets without per-heartbeat Python cold-starts. See COG-116 §2.4 for the
design tradeoffs.

**Request**

```json
{
  "query": "string (required, non-empty)",
  "topK": 3
}
```

- `query` — search string passed straight to `FactRetriever.search`. Empty or
  non-string values produce JSON-RPC `-32602 Invalid params`.
- `topK` — optional cap on snippet count. Defaults to `3`. Non-positive values
  are coerced to the default; non-integer values produce `-32602`.

**Response**

```json
{
  "snippets": [
    {
      "factId": "42",
      "content": "...",
      "score": 0.83,
      "createdAt": "2026-05-04T12:00:00"
    }
  ]
}
```

`snippets` is empty when no facts match. `factId` is stringified for stable
JSON shape across SQLite int IDs and any future store backends.

**Provenance**

`_meta.requestId` and `_meta.taskId` from the ACP envelope (wired in COG-115
H3) are accepted on the request and logged for traceability. The current
implementation has no side effects to forward them to.

**Stability disclaimer**

This method exists to unblock the Paperclip memory bridge. Standardising it
would go through an ACP RFC and likely change shape; do not depend on it from
non-Paperclip clients.

### `experimental/honchoUserModel` — Paperclip user-model bridge

**Status:** experimental, **Paperclip-bridge-specific**. Not part of the ACP
spec; the `experimental/` prefix advertises non-stable status. Read-only
passthrough — Hermes is the source of truth for the snapshot shape and the
Paperclip TS layer must not rewrite it. See COG-116 §2.5 for the design
constraints.

Surfaces Hermes' Honcho user-modelling output for a single peer so the
Paperclip heartbeat-context route can fold a `userModel` into its response
without taking a write dependency on Honcho. Writes from Paperclip → Honcho
are an explicit non-goal for v1.

**Request**

```json
{
  "userId": "string (required, non-empty)"
}
```

- `userId` — Honcho peer identifier. Empty, missing, or non-string values
  produce JSON-RPC `-32602 Invalid params`.

**Response**

```json
{
  "userModel": {
    "userId": "user-42",
    "card": ["prefers concise responses", "expert in distributed systems"],
    "representation": "Senior backend engineer working on Cogni OS."
  }
}
```

`userModel` is `null` when the peer has no profile, when Honcho is not
configured for this Hermes process, or when the underlying Honcho call
fails (errors are intentionally swallowed so heartbeat-context stays
read-safe). The non-null payload is whatever the Hermes-side lookup
returns — Hermes owns the snapshot shape and the ACP handler does not
reshape, filter, or add fields beyond the `userModel` envelope.

**Provenance**

`_meta.requestId` and `_meta.taskId` from the ACP envelope are accepted on
the request and logged for traceability, mirroring `experimental/factSearch`.

**Stability disclaimer**

This method exists to unblock the Paperclip user-model bridge. Standardising
it would go through an ACP RFC and likely change shape; do not depend on it
from non-Paperclip clients.
