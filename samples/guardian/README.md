# Local Guardian subprocess fixtures

Run `python3 scripts/check-guardian.py`. The cases create invented Git projects,
with no CI configuration or agent host settings, and invoke the runner as a real
subprocess. They require only Python, Git and Bash (the existing gate shell).

`cases.json` pins passing execution, short-circuited compound failure, an absent
executable, misleading dependency text, a missing declaration, an invalid base,
and a gate that edits its input. Additional assertions cover human output,
unknown scope and attribution, retained failure output, later edits and commits,
Stop compatibility, and another checkout's inherited Git routing environment.

These prove the local mechanism, not adoption cost on a real consuming project
or enforcement inside an agent host. No tool-specific findings are parsed.
