#!/usr/bin/env python3
"""P1c-S5 gate: the agent layer reaches tools only through the runtime.

Static and offline — it imports no agent module, starts no workflow, calls no
model. It fails when:

* an agent imports a tool implementation instead of the runtime
  (``backend.tools.xhs.trending`` and friends give it an object no Gateway
  ever sees, so timeout / retry / scope / tracing stop applying at once);
* an agent invokes a capability it did not declare, or declares one it never
  invokes;
* a gateway call cannot be read at all — a non-literal capability, a shape
  this gate does not recognise, a source that does not parse. Reported, never
  skipped: "0 mismatches" over code nobody read is a false pass;
* a capability an agent names is absent from the catalogue.

Catalogue entries no agent uses are reported, not failed: ``xhs.publish`` has
no caller until P2a, and a gate that fails on planned work gets switched off.

See docs/tool-runtime.md for the architecture this protects.

Examples:
    python scripts/gates/tool_runtime_gate.py
    python scripts/gates/tool_runtime_gate.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.tools.runtime.audit import DEFAULT_AGENTS_DIR, audit_tool_runtime
from backend.tools.runtime.catalog import build_registry

GATE_NAME = "P1c-S5 tool runtime"


def _render_agents(audit) -> list[str]:
    lines: list[str] = []
    for usage in audit.usages:
        notes: list[str] = []
        if usage.undeclared:
            notes.append(f"UNDECLARED={list(usage.undeclared)}")
        if usage.unused:
            notes.append(f"UNUSED={list(usage.unused)}")
        status = " ".join(notes) if notes else "ok"
        lines.append(
            f"{usage.module:<26}declared={len(usage.declared)} "
            f"invoked={len(usage.invoked)}  {status}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--agents-dir", type=Path, default=DEFAULT_AGENTS_DIR)
    parser.add_argument("--json", type=Path, default=None, help="write the full report here")
    args = parser.parse_args(argv)

    known = build_registry().capabilities()
    audit = audit_tool_runtime(known_capabilities=known, agents_dir=args.agents_dir)

    print(f"== {GATE_NAME} ==")
    print(f"agents dir: {audit.agents_dir}")
    print(f"sources: {len(audit.modules)}   catalogue: {len(known)}")

    print("\n-- direct tool imports --")
    if audit.direct_imports:
        for item in audit.direct_imports:
            print(f"BYPASS {item}")
    else:
        print("none — every agent reaches a tool through self.tools")

    print("\n-- declarations vs invocations --")
    rendered = _render_agents(audit)
    print("\n".join(rendered) if rendered else "no agent uses a tool")

    print("\n-- unreadable --")
    if audit.unreadable:
        for item in audit.unreadable:
            print(f"UNREADABLE {item}")
    else:
        print("none")

    print("\n-- catalogue coverage --")
    named = {name for usage in audit.usages for name in (*usage.declared, *usage.invoked)}
    print(f"named by agents: {len(named)}")
    for name in audit.unknown:
        print(f"UNKNOWN {name} — no such capability in the catalogue")
    if audit.orphans:
        print(f"orphans (reported, not failed): {', '.join(audit.orphans)}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(audit.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON report: {args.json}")

    if not audit.ok:
        print(f"\n{GATE_NAME}: FAILED")
        return 1
    print(f"\n{GATE_NAME}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
