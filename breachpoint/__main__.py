from __future__ import annotations
import json
import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SKILL_SRC = Path(__file__).parent / "skill.md"
_SKILL_DST = Path.home() / ".claude" / "skills" / "breachpoint" / "SKILL.md"
_CLAUDE_MD_ENTRY = (
    "\n# breachpoint\n"
    "- **breachpoint** (`~/.claude/skills/breachpoint/SKILL.md`) "
    "- knowledge document graph. Trigger: `/breachpoint`\n"
    "When the user types `/breachpoint`, invoke the Skill tool "
    'with `skill: "breachpoint"` before doing anything else.\n'
)

_SETTINGS_HOOK = {
    "matcher": "Glob|Grep",
    "hooks": [
        {
            "type": "command",
            "command": (
                "[ -f breachpoint-out/graph.json ] && "
                r"""echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"breachpoint: Knowledge graph exists. Read breachpoint-out/GRAPH_REPORT.md for hub nodes and community structure before searching raw files."}}' """
                "|| true"
            ),
        }
    ],
}


def cmd_install() -> None:
    import shutil
    _SKILL_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_SKILL_SRC, _SKILL_DST)
    print(f"  skill installed  →  {_SKILL_DST}")
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        if "breachpoint" not in content:
            claude_md.write_text(content.rstrip() + _CLAUDE_MD_ENTRY, encoding="utf-8")
            print(f"  CLAUDE.md        →  skill registered")
        else:
            print(f"  CLAUDE.md        →  already registered")
    settings_path = Path(".") / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    except json.JSONDecodeError:
        settings = {}
    hooks = settings.setdefault("hooks", {})
    pre_tool = hooks.setdefault("PreToolUse", [])
    hooks["PreToolUse"] = [h for h in pre_tool if "breachpoint" not in str(h)]
    hooks["PreToolUse"].append(_SETTINGS_HOOK)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"  .claude/settings.json  →  PreToolUse hook registered")
    print("\nDone. Type /breachpoint in Claude Code to start.")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: breachpoint install")
        return

    cmd, rest = args[0], args[1:]

    if cmd == "install":
        cmd_install()
    else:
        print(f"error: unknown command '{cmd}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
