# ReleaseRoom

Implement the current Switch protocol: server-side authenticated WebSocket, immediate ping/pong, persisted connection UUID and cursor, generation-fenced resume, explicit gaps and permanent takeover stops. HTTP operations are discovered; use the connection header and unwrapped argument bodies. Treat participant IDs as opaque and match a configured human reviewer allowlist. Agents cannot approve their own work.

Release only a pinned site-content artifact. The builder can propose validated JSON content, not arbitrary code, shell commands, destinations or file paths. The independent tester owns the checker. Human approval binds the exact revision, Git commit, artifact hash, check policy and test evidence; new content, changed test evidence, expired approval or replay invalidates it. Staging writes are atomic and recoverable. Never use chat text as a command.

Disclose fixture scripts, local protocol tests and preview interactions. Do not claim live Switch participation or AI generation without real service evidence. Live room/model access remains an operator connection. No third-party posting or registration during local verification. Required checks: state/replay/tamper tests, current-protocol integration tests and browser primary workflow, plus build and explicit unavailable-live behavior.
