# Java, single Maven module

```bash
"$BASELINE"/scripts/adopt.sh .    # merges the lint region into your pom.xml
mvn test-compile                  # the analysis run — Error Prone IS the compile
mvn spotless:apply                # once, alone, then commit it separately
```

**The lint config lives in your own `pom.xml`, and the markers around it are the
whole Java story.** Maven has no remote lint consumption, and its one real
inheritance mechanism — a parent POM — is unavailable twice over: publishing one
needs a registry, and a Spring Boot project's single `<parent>` slot is already
taken. So Java follows the C# and Rust pattern of an adopt-time copy.

Rust gets away with `cat >> Cargo.toml` because TOML appends. XML does not — the
block has to land *inside* `<build><plugins>` — so it arrives as a managed
region:

```xml
<!-- maxi-quality:begin — Java lint baseline. GENERATED, do not hand-edit. ... -->
...
<!-- maxi-quality:end -->
```

Re-running `adopt.sh` replaces what is between the markers and nothing outside
them. **Do not hand-edit inside them**; that is what makes a baseline bump a
one-command refresh instead of a merge.

If your `pom.xml` already configures `maven-compiler-plugin`, `adopt.sh` writes
**nothing** and tells you to merge by hand. That refusal is deliberate: two
declarations of one plugin in one POM is last-one-wins, so writing the
baseline's would silently drop the `compilerArgs` you already had — a repo
arriving with `-Xlint:all -Werror` would come out of adoption weaker than it went
in.

**The workflow here is the same six lines as every other example.** The pins that
matter to a consumer — the JDK, Error Prone, NullAway, Spotless — live in this
baseline, not in a job stamped into your repo, for the reason #70 settled: a
scaffolded job only moves when someone re-runs `adopt.sh`, which is
copy-paste-drift with extra steps.

## Two things worth knowing before the first run

**`-Werror` and Error Prone do not compose.** When javac's own `-Xlint` produces
a warning, the compile ends before Error Prone's pass runs, so its findings are
missing from that build's output. The build is still red — a *green* build is by
definition one where Error Prone ran and found nothing — but your first run on an
existing codebase can show four lint warnings and hide forty analyzer findings
behind them. Fix the lint warnings, re-run, and the rest appear. The CI job says
so out loud when it happens.

**`annotationProcessorPaths` turns off classpath processor discovery.** If you
use Lombok or MapStruct, add them to that element too. That is Maven's behaviour
rather than this baseline's, and it is the one way adopting this can break a
build that was previously fine.

## Scope

Maven only. Gradle gets built when a Gradle consumer exists — the same
just-in-time rule that produced this layer at all. A `build.gradle[.kts]` with no
`pom.xml` **stops the run** rather than skipping, because "no Java here" is a lie
about a repo that plainly has some.

See [`docs/ADOPTION.md` §4c](../../docs/ADOPTION.md).
