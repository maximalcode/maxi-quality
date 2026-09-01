# Preflight contract

`test_preflight.py` calls the public command as a subprocess. It reuses the
existing bad/clean language sources and independently committed finding
manifests. Only the sample harness's relative baseline imports are replaced in
temporary inputs; no source finding or expected manifest is weakened.

It asserts exact per-rule counts, clean counterparts, bug/style classification,
and byte-for-byte preservation of the original tree. The `contract` mode covers
bad arguments, absent tools, malformed output, failed tools, unknown rule IDs,
timeouts and external symlinks. Fake executables occupy the external tool
boundary only; no preflight internals are imported or mocked.

```bash
python3 samples/preflight/test_preflight.py contract
python3 samples/preflight/test_preflight.py python
python3 samples/preflight/test_preflight.py typescript
python3 samples/preflight/test_preflight.py dotnet
python3 samples/preflight/test_preflight.py rust
python3 samples/preflight/test_preflight.py java
```

Each language mode requires its normal installed toolchain. CI runs it within
the corresponding existing Layer 1 job; `contract` runs in `adopt`. No new
required context is introduced. These are fixture detection measurements, not
consumer adoption-cost measurements.
