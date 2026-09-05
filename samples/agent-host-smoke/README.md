# Host smoke command fixtures

Run the offline checks with:

```bash
python3 samples/agent-host-smoke/test_smoke.py
```

These tests cover the public command result and the interpretation of host
events. They reject model claims, a ledger without a hook event, a different
session's ledger, a loop override instead of a fresh pass, and a shell refusal
without a matching requested tool and hook decision. A non-invoking executable
fails the same enforcement assertion that the live command uses, across
repository, linked-worktree, and subdirectory launches. The command's temporary
directories are gone when it returns. A simulated expired login proves that a
successful authentication status query cannot stand in for a usable session.

`protocol_fixture.py` is an **offline protocol simulator**. It executes the
fixture's configured hooks directly and emits invented host messages so the
test can exercise migration, diagnosis, the real recorder, fresh/stale content,
and the harmless shell tripwire together. Its output is never a live
observation. Neither the simulator nor this test command authenticates with an
agent service. CI runs only these offline checks in the existing `agent-guard`
context.

For the separate opt-in real-host command and its evidence limits, see
[the runtime guide](../../docs/QUALITY-RUNTIME.md#observe-host-enforcement).
