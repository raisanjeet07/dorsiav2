"""Persistence — saves API-created extensions to YAML files on disk."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger(__name__)


class ExtensionPersistence:
    """
    Persists extensions created via the API to the user extensions directory.

    This enables API-created extensions to survive restarts (they'll be
    picked up by the loader on next startup or hot-reload).
    """

    def __init__(self, extensions_dir: str) -> None:
        self.base_dir = Path(extensions_dir)

    async def save_extension(self, model, subdir: str) -> Path:
        """
        Save a Pydantic model as a YAML file.

        Args:
            model: A Persona, Capability, or AgentProfile model instance.
            subdir: "personas", "capabilities", or "agents".

        Returns:
            Path to the saved file.
        """
        target_dir = self.base_dir / subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        file_path = target_dir / f"{model.metadata.name}.yaml"
        data = model.model_dump(by_alias=True, exclude_none=True)

        with open(file_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        logger.info("extension_persisted", path=str(file_path))
        return file_path

    async def delete_extension(self, name: str, subdir: str) -> bool:
        """Delete the YAML file for an extension."""
        for suffix in (".yaml", ".yml"):
            file_path = self.base_dir / subdir / f"{name}{suffix}"
            if file_path.exists():
                file_path.unlink()
                logger.info("extension_file_deleted", path=str(file_path))
                return True
        return False
