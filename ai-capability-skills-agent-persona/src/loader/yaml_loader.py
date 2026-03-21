"""YAML file discovery, validation, and parsing for all extension types."""

from __future__ import annotations

import structlog
import yaml
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.models.persona import Persona
from src.models.capability import Capability
from src.models.agent_profile import AgentProfile

logger = structlog.get_logger(__name__)

KIND_MODEL_MAP: dict[str, type] = {
    "Persona": Persona,
    "Capability": Capability,
    "AgentProfile": AgentProfile,
}

# Subdirectory name → expected kind
SUBDIR_KIND_MAP: dict[str, str] = {
    "personas": "Persona",
    "capabilities": "Capability",
    "agents": "AgentProfile",
}


class LoadResult:
    """Result of loading extensions from a directory."""

    def __init__(self) -> None:
        self.personas: dict[str, Persona] = {}
        self.capabilities: dict[str, Capability] = {}
        self.agent_profiles: dict[str, AgentProfile] = {}
        self.errors: list[dict[str, Any]] = []

    @property
    def total_loaded(self) -> int:
        return len(self.personas) + len(self.capabilities) + len(self.agent_profiles)

    def summary(self) -> dict[str, int]:
        return {
            "personas": len(self.personas),
            "capabilities": len(self.capabilities),
            "agent_profiles": len(self.agent_profiles),
            "errors": len(self.errors),
        }


class ExtensionLoader:
    """
    Discovers and loads YAML extension files from one or more directories.

    Directory structure expected:
        dir/
        ├── personas/
        │   ├── foo.yaml
        │   └── bar.yml
        ├── capabilities/
        │   └── baz.yaml
        └── agents/
            └── qux.yaml
    """

    def __init__(self, directories: list[str | Path]) -> None:
        self.directories = [Path(d) for d in directories]

    def load_all(self) -> LoadResult:
        """Load all extensions from all configured directories.

        Later directories override earlier ones (user overrides defaults).
        """
        result = LoadResult()

        for directory in self.directories:
            if not directory.exists():
                logger.warning("extension_dir_not_found", path=str(directory))
                continue
            self._load_directory(directory, result)

        logger.info("extensions_loaded", **result.summary())
        return result

    def load_single_file(self, file_path: str | Path) -> Persona | Capability | AgentProfile | None:
        """Load a single YAML file. Returns the parsed model or None on error."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            logger.error("file_not_found", path=str(path))
            return None

        raw = self._read_yaml(path)
        if raw is None:
            return None

        kind = raw.get("kind", "")
        model_cls = KIND_MODEL_MAP.get(kind)
        if model_cls is None:
            # Try to infer kind from parent directory name
            kind = SUBDIR_KIND_MAP.get(path.parent.name, "")
            model_cls = KIND_MODEL_MAP.get(kind)

        if model_cls is None:
            logger.error("unknown_kind", path=str(path), kind=kind)
            return None

        try:
            return model_cls.model_validate(raw)
        except ValidationError as e:
            logger.error("validation_failed", path=str(path), errors=e.error_count())
            return None

    def parse_yaml_string(self, content: str, kind: str | None = None) -> Persona | Capability | AgentProfile | None:
        """Parse a YAML string into an extension model.

        If kind is not specified, it's inferred from the YAML's 'kind' field.
        """
        try:
            raw = yaml.safe_load(content)
        except yaml.YAMLError as e:
            logger.error("yaml_parse_error", error=str(e))
            return None

        if not isinstance(raw, dict):
            logger.error("yaml_not_dict")
            return None

        resolved_kind = kind or raw.get("kind", "")
        model_cls = KIND_MODEL_MAP.get(resolved_kind)
        if model_cls is None:
            logger.error("unknown_kind", kind=resolved_kind)
            return None

        try:
            return model_cls.model_validate(raw)
        except ValidationError as e:
            logger.error("validation_failed", errors=e.error_count())
            return None

    # -- Private --

    def _load_directory(self, directory: Path, result: LoadResult) -> None:
        """Scan a directory's subdirectories for extension files."""
        for subdir_name, expected_kind in SUBDIR_KIND_MAP.items():
            subdir = directory / subdir_name
            if not subdir.exists() or not subdir.is_dir():
                continue

            for file_path in sorted(subdir.glob("*.y*ml")):  # .yaml and .yml
                self._load_file(file_path, expected_kind, result)

    def _load_file(self, path: Path, expected_kind: str, result: LoadResult) -> None:
        """Load and validate a single YAML file, storing in the result."""
        raw = self._read_yaml(path)
        if raw is None:
            result.errors.append({"path": str(path), "error": "Failed to parse YAML"})
            return

        # Determine kind: explicit in file > inferred from directory
        kind = raw.get("kind", expected_kind)
        model_cls = KIND_MODEL_MAP.get(kind)
        if model_cls is None:
            result.errors.append({"path": str(path), "error": f"Unknown kind: {kind}"})
            return

        try:
            model = model_cls.model_validate(raw)
        except ValidationError as e:
            result.errors.append({
                "path": str(path),
                "error": f"Validation failed: {e.error_count()} errors",
                "details": e.errors(),
            })
            logger.warning("validation_failed", path=str(path), errors=e.error_count())
            return

        name = model.metadata.name

        if kind == "Persona":
            result.personas[name] = model
        elif kind == "Capability":
            result.capabilities[name] = model
        elif kind == "AgentProfile":
            result.agent_profiles[name] = model

        logger.debug("extension_loaded", kind=kind, name=name, path=str(path))

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any] | None:
        """Read and parse a YAML file, returning None on error."""
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.warning("yaml_not_dict", path=str(path))
                return None
            return data
        except (yaml.YAMLError, OSError) as e:
            logger.error("yaml_read_error", path=str(path), error=str(e))
            return None
