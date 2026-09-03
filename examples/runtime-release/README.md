# Runtime installation diagnosis example

This invented Adopter checkout demonstrates the public diagnosis entry point.
After preparing a release cache and migrating the checkout, run:

```bash
quality-runtime diagnose --root /path/to/this/example
quality-runtime diagnose --root /path/to/this/example --json
```

The healthy result reports the pinned version and commit, its installation
profile, the declared gate, and the cache and wiring checks. It says
`live_enforcement: unverified` because a static read cannot claim that an
agent host executed a hook. Host settings and overrides are also reported as
`unverified`.

To demonstrate a broken installation, change the owned
`Edit|Write|MultiEdit` matcher in `.claude/settings.json` to `Edit|Write` and
run the same command again. The command exits nonzero and the JSON result
identifies `hook-sample-guard` as failed. Restore the matcher to return to the
healthy result. Diagnosis does not edit the checkout or run its gate.

The complete black box demonstration, including a profile without
`samples/expected/`, an explicitly disabled profile, and a legacy copied
installation, is exercised by:

```bash
python3 samples/runtime-release/test_runtime.py
```
