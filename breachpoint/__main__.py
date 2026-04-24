"""breachpoint CLI — `breachpoint install` sets up the skill."""
from __future__ import annotations
import json
import platform
import shutil
import sys
from pathlib import Path

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("breachpoint")
except Exception:
    __version__ = "unknown"


def _check_skill_version(skill_dst: Path) -> None:
    """Warn if the installed skill is from an older breachpoint version."""
    version_file = skill_dst.parent / ".breachpoint_version"
    if not version_file.exists():
        return
    installed = version_file.read_text(encoding="utf-8").strip()
    if installed != __version__:
        print(f"  warning: skill is from breachpoint {installed}, package is {__version__}. Run 'breachpoint install' to update.")


def _refresh_all_version_stamps() -> None:
    for cfg in _PLATFORM_CONFIG.values():
        vf = Path.home() / cfg["skill_dst"]
        vf = vf.parent / ".breachpoint_version"
        if vf.exists():
            vf.write_text(__version__, encoding="utf-8")


_SKILL_REGISTRATION = (
    "\n# breachpoint\n"
    "- **breachpoint** (`~/.claude/skills/breachpoint/SKILL.md`) "
    "- TTL/RDF 知识文档图谱. Trigger: `/breachpoint`\n"
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


_PLATFORM_CONFIG: dict[str, dict] = {
    "claude": {
        "skill_file": "skill.md",
        "skill_dst": Path(".claude") / "skills" / "breachpoint" / "SKILL.md",
        "claude_md": True,
    },
    "windows": {
        "skill_file": "skill.md",
        "skill_dst": Path(".claude") / "skills" / "breachpoint" / "SKILL.md",
        "claude_md": True,
    },
}


def install(platform: str = "claude") -> None:
    if platform not in _PLATFORM_CONFIG:
        print(
            f"error: unknown platform '{platform}'. Choose from: {', '.join(_PLATFORM_CONFIG)}",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = _PLATFORM_CONFIG[platform]
    skill_src = Path(__file__).parent / cfg["skill_file"]
    if not skill_src.exists():
        print(f"error: {cfg['skill_file']} not found in package - reinstall breachpoint", file=sys.stderr)
        sys.exit(1)

    skill_dst = Path.home() / cfg["skill_dst"]
    skill_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(skill_src, skill_dst)
    (skill_dst.parent / ".breachpoint_version").write_text(__version__, encoding="utf-8")
    print(f"  skill installed  ->  {skill_dst}")

    if cfg["claude_md"]:
        claude_md = Path.home() / ".claude" / "CLAUDE.md"
        if claude_md.exists():
            content = claude_md.read_text(encoding="utf-8")
            if "breachpoint" in content:
                print(f"  CLAUDE.md        ->  already registered (no change)")
            else:
                claude_md.write_text(content.rstrip() + _SKILL_REGISTRATION, encoding="utf-8")
                print(f"  CLAUDE.md        ->  skill registered in {claude_md}")
        else:
            claude_md.parent.mkdir(parents=True, exist_ok=True)
            claude_md.write_text(_SKILL_REGISTRATION.lstrip(), encoding="utf-8")
            print(f"  CLAUDE.md        ->  created at {claude_md}")

    _refresh_all_version_stamps()

    print()
    print("Done. Type /breachpoint in Claude Code to start.")


def main() -> None:
    if not any(arg in ("install", "uninstall") for arg in sys.argv):
        for skill_dst in {Path.home() / cfg["skill_dst"] for cfg in _PLATFORM_CONFIG.values()}:
            _check_skill_version(skill_dst)

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: breachpoint <command>")
        print()
        print("Commands:")
        print("  install [--platform P]  copy skill to platform config dir (claude|windows)")
        print("  uninstall               remove skill and hooks")
        print()
        return

    cmd = sys.argv[1]
    if cmd == "install":
        default_platform = "windows" if platform.system() == "Windows" else "claude"
        chosen_platform = default_platform
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i].startswith("--platform="):
                chosen_platform = args[i].split("=", 1)[1]
                i += 1
            elif args[i] == "--platform" and i + 1 < len(args):
                chosen_platform = args[i + 1]
                i += 2
            else:
                i += 1
        install(platform=chosen_platform)
    elif cmd == "uninstall":
        for cfg in _PLATFORM_CONFIG.values():
            skill_dst = Path.home() / cfg["skill_dst"]
            if skill_dst.exists():
                skill_dst.unlink()
                print(f"  skill removed    ->  {skill_dst}")
            vf = skill_dst.parent / ".breachpoint_version"
            if vf.exists():
                vf.unlink()
        print("Done.")
    else:
        print(f"error: unknown command '{cmd}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
