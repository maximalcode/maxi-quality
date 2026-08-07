# C# / .NET

```bash
"$BASELINE"/scripts/adopt.sh .    # writes Directory.Build.props, appends .editorconfig
dotnet build                      # the build IS the analysis run
```

Note what is *not* here: no `.csproj` changes at all. MSBuild picks up
`Directory.Build.props` for every project beneath it, and the props file turns on
`TreatWarningsAsErrors`, `EnforceCodeStyleInBuild` and the two analyzer packages.

If this repo already had its own `Directory.Build.props`, `adopt.sh` refuses to
overwrite it and tells you to merge — see [`../../docs/ADOPTION.md`](../../docs/ADOPTION.md) §3.

**Consider a lock file.** Without `packages.lock.json` the dependency scan
resolves your *direct* dependencies only — measured 4 findings versus 7 on the
same project. `dotnet restore --use-lock-file`, then commit it.
