"""Hot-reload file watcher using watchdog — reloads extensions when YAML files change."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import structlog
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from src.loader.yaml_loader import ExtensionLoader, SUBDIR_KIND_MAP
from src.registry.extension_registry import ExtensionRegistry

logger = structlog.get_logger(__name__)


class _DebouncedHandler(FileSystemEventHandler):
    """Debounces file events and triggers reload on YAML changes."""

    def __init__(self, callback: callable, debounce_seconds: float = 1.0) -> None:
        super().__init__()
        self._callback = callback
        self._debounce_seconds = debounce_seconds
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        src_path = event.src_path
        if not (src_path.endswith(".yaml") or src_path.endswith(".yml")):
            return

        # Check if the file is in a recognized subdirectory
        path = Path(src_path)
        if path.parent.name not in SUBDIR_KIND_MAP:
            return

        with self._lock:
            self._pending[src_path] = time.time()
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_seconds, self._fire)
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            paths = list(self._pending.keys())
            self._pending.clear()

        if paths:
            logger.info("hot_reload_triggered", changed_files=len(paths))
            self._callback(paths)


class ExtensionWatcher:
    """
    Watches extension directories for YAML file changes and reloads them.

    On change:
    1. Re-parse the changed file(s)
    2. Upsert into the registry
    3. (Invalid files are logged and skipped — never break running extensions)
    """

    def __init__(
        self,
        loader: ExtensionLoader,
        registry: ExtensionRegistry,
        debounce_seconds: float = 1.0,
    ) -> None:
        self.loader = loader
        self.registry = registry
        self.debounce_seconds = debounce_seconds
        self._observer: Observer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Start watching all configured extension directories."""
        self._loop = loop

        handler = _DebouncedHandler(
            callback=self._on_files_changed,
            debounce_seconds=self.debounce_seconds,
        )

        self._observer = Observer()
        for directory in self.loader.directories:
            if directory.exists():
                self._observer.schedule(handler, str(directory), recursive=True)
                logger.info("watching_directory", path=str(directory))

        self._observer.daemon = True
        self._observer.start()
        logger.info("hot_reload_watcher_started")

    def stop(self) -> None:
        """Stop watching."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("hot_reload_watcher_stopped")

    def _on_files_changed(self, paths: list[str]) -> None:
        """Handle changed files — reload individually."""
        for path_str in paths:
            try:
                model = self.loader.load_single_file(path_str)
                if model is None:
                    logger.warning("hot_reload_skip_invalid", path=path_str)
                    continue

                # Upsert into registry based on type
                from src.models.persona import Persona
                from src.models.capability import Capability
                from src.models.agent_profile import AgentProfile

                if isinstance(model, Persona):
                    self.registry.upsert_persona(model)
                elif isinstance(model, Capability):
                    self.registry.upsert_capability(model)
                elif isinstance(model, AgentProfile):
                    self.registry.upsert_agent_profile(model)

                logger.info("hot_reloaded", kind=model.kind, name=model.metadata.name)

            except Exception as e:
                logger.error("hot_reload_error", path=path_str, error=str(e))
