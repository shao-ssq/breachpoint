# monitor a folder and notify when documents change (requires --update to re-extract via LLM)
from __future__ import annotations
import time
from pathlib import Path

_WATCHED_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".pdf", ".docx", ".doc",
    ".html", ".htm", ".json", ".csv", ".tex", ".org", ".adoc", ".asciidoc",
}


def _notify(watch_path: Path) -> None:
    """Write a needs_update flag and print a notification."""
    flag = watch_path / "breachpoint-out" / "needs_update"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("1", encoding="utf-8")
    print(f"\n[breachpoint watch] New or changed documents detected in {watch_path}")
    print("[breachpoint watch] Document changes require LLM re-extraction.")
    print("[breachpoint watch] Run 'breachpoint update <path>' to update the graph.")
    print(f"[breachpoint watch] Flag written to {flag}")


def watch(watch_path: Path, debounce: float = 3.0) -> None:
    """Watch watch_path for new or modified documents and write a needs_update flag.

    Unlike graphify, ALL document changes require LLM re-extraction — there is no
    AST-only rebuild shortcut. This function notifies the user to run --update.

    debounce: seconds to wait after the last change before triggering.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError as e:
        raise ImportError("watchdog not installed. Run: pip install watchdog") from e

    last_trigger: float = 0.0
    pending: bool = False
    changed: set[Path] = set()

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            nonlocal last_trigger, pending
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in _WATCHED_EXTENSIONS:
                return
            if any(part.startswith(".") for part in path.parts):
                return
            if "breachpoint-out" in path.parts:
                return
            last_trigger = time.monotonic()
            pending = True
            changed.add(path)

    handler = Handler()
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    observer.start()

    print(f"[breachpoint watch] Watching {watch_path.resolve()} - press Ctrl+C to stop")
    print(f"[breachpoint watch] All document changes require LLM re-extraction via 'breachpoint update'.")
    print(f"[breachpoint watch] Debounce: {debounce}s")

    try:
        while True:
            time.sleep(0.5)
            if pending and (time.monotonic() - last_trigger) >= debounce:
                pending = False
                batch = list(changed)
                changed.clear()
                print(f"\n[breachpoint watch] {len(batch)} file(s) changed")
                _notify(watch_path)
    except KeyboardInterrupt:
        print("\n[breachpoint watch] Stopped.")
    finally:
        observer.stop()
        observer.join()
