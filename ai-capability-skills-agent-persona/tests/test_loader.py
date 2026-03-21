"""Tests for the YAML extension loader."""

import pytest
from pathlib import Path

from src.loader.yaml_loader import ExtensionLoader


DEFAULTS_DIR = Path(__file__).resolve().parent.parent / "defaults"


class TestExtensionLoader:
    def test_load_defaults(self):
        loader = ExtensionLoader(directories=[str(DEFAULTS_DIR)])
        result = loader.load_all()

        assert result.total_loaded > 0
        assert len(result.errors) == 0

        # Should have loaded the built-in personas
        assert "research-reviewer" in result.personas
        assert "domain-expert" in result.personas
        assert "technical-writer" in result.personas

        # Should have loaded the built-in capabilities
        assert "web-research" in result.capabilities
        assert "citation-validation" in result.capabilities

        # Should have loaded the built-in agent profiles
        assert "claude-code" in result.agent_profiles
        assert "gemini" in result.agent_profiles

    def test_load_nonexistent_directory(self):
        loader = ExtensionLoader(directories=["/nonexistent/path"])
        result = loader.load_all()
        assert result.total_loaded == 0

    def test_parse_yaml_string_persona(self):
        loader = ExtensionLoader(directories=[])
        yaml_str = """
apiVersion: v1
kind: Persona
metadata:
  name: test-persona
  description: "A test persona"
spec:
  identity: "You are a test agent."
"""
        model = loader.parse_yaml_string(yaml_str)
        assert model is not None
        assert model.metadata.name == "test-persona"

    def test_parse_yaml_string_invalid(self):
        loader = ExtensionLoader(directories=[])
        model = loader.parse_yaml_string("not: valid: yaml: {{{")
        assert model is None

    def test_parse_yaml_string_with_kind_hint(self):
        loader = ExtensionLoader(directories=[])
        yaml_str = """
metadata:
  name: no-kind
spec:
  identity: "Test"
"""
        model = loader.parse_yaml_string(yaml_str, kind="Persona")
        assert model is not None
        assert model.metadata.name == "no-kind"

    def test_user_overrides_defaults(self, tmp_path):
        """User extensions should override defaults with the same name."""
        # Create a "defaults" dir with a persona
        defaults = tmp_path / "defaults" / "personas"
        defaults.mkdir(parents=True)
        (defaults / "shared.yaml").write_text("""
apiVersion: v1
kind: Persona
metadata:
  name: shared
  version: "1.0.0"
spec:
  identity: "Default version."
""")

        # Create a "user" dir with same-name persona
        user = tmp_path / "user" / "personas"
        user.mkdir(parents=True)
        (user / "shared.yaml").write_text("""
apiVersion: v1
kind: Persona
metadata:
  name: shared
  version: "2.0.0"
spec:
  identity: "User version."
""")

        loader = ExtensionLoader(directories=[str(tmp_path / "defaults"), str(tmp_path / "user")])
        result = loader.load_all()

        # User version should win
        assert result.personas["shared"].metadata.version == "2.0.0"
        assert "User version" in result.personas["shared"].spec.identity
