# Host smoke command fixtures

Run the offline checks with:

```bash
python3 samples/agent-host-smoke/test_smoke.py
```

These tests cover the public command result and the interpretation of host
events. They reject model claims, a ledger without a hook event, a different
session's ledger, a loop override instead of a fresh pass, and a shell refusal
without a matching requested tool and hook decision, including a denial for
another tool request in the same turn. Retained evidence is checked for
owner-only permissions under a normal `022` creation mask. A non-invoking executable
fails the same enforcement assertion that the live command uses, across
repository, linked-worktree, and subdirectory launches. The command's temporary
directories are gone when it returns. A simulated expired login proves that a
successful authentication status query cannot stand in for a usable session.

`protocol_fixture.py` (Claude) and `codex_protocol_fixture.py` (native Codex)
are **offline protocol simulators**. They execute the
fixture's configured hooks directly and emit invented host messages so the
test can exercise migration, diagnosis, the real recorder, fresh/stale content,
and the harmless shell tripwire together. Their output is never a live
observation. Neither simulator nor this test command authenticates with an
agent service. CI runs only these offline checks in the existing `agent-guard`
context.

For the separate opt-in real-host command and its evidence limits, see
[the runtime guide](../../docs/QUALITY-RUNTIME.md#observe-host-enforcement).

The Codex simulator uses stdio requests and native hook/item/turn notifications.
Blocked Stop probes do not complete a turn until interrupted; the adapter must
first establish native hook and matching ledger evidence. Tests separate
subdirectory discovery from supported roots, reject absent/disabled/untrusted
hooks before model calls, and reject unrelated thread, turn, source or request
identities. The denied-command item ordering is an **unverified native-host
assumption**, not something the simulator can prove: if a real PreToolUse
denial omits command items, the smoke cannot count it as a pass. The dated
Codex outcome records only preflight discovery, with no live enforcement.
