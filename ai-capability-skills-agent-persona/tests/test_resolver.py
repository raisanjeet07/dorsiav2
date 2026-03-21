"""Tests for the persona resolver."""

import pytest
from pathlib import Path

from src.loader.yaml_loader import ExtensionLoader
from src.registry.extension_registry import ExtensionRegistry
from src.resolver.persona_resolver import PersonaResolver, ResolutionError


DEFAULTS_DIR = Path(__file__).resolve().parent.parent / "defaults"


class TestPersonaResolver:
    @pytest.fixture
    def resolver(self):
        loader = ExtensionLoader(directories=[str(DEFAULTS_DIR)])
        result = loader.load_all()
        registry = ExtensionRegistry()
        registry.load_from_result(result)
        return PersonaResolver(registry)

    def test_resolve_research_reviewer(self, resolver):
        resolved = resolver.resolve("research-reviewer", "claude-code")

        assert resolved.persona_name == "research-reviewer"
        assert resolved.agent_name == "claude-code"
        assert resolved.gateway_flow == "claude-code"
        assert resolved.mode == "bypassPermissions"
        assert resolved.model == "claude-sonnet-4-6"
        assert "citation-validation" in resolved.capability_names
        assert len(resolved.skill_prompt) > 100
        assert "senior research analyst" in resolved.skill_prompt.lower()

    def test_resolve_domain_expert(self, resolver):
        resolved = resolver.resolve("domain-expert", "claude-code")

        assert resolved.persona_name == "domain-expert"
        assert "web-research" in resolved.capability_names
        assert "citation-validation" in resolved.capability_names

    def test_resolve_web_researcher_on_gemini(self, resolver):
        resolved = resolver.resolve("web-researcher", "gemini")

        assert resolved.persona_name == "web-researcher"
        assert resolved.agent_name == "gemini"
        assert resolved.gateway_flow == "gemini"

    def test_resolve_nonexistent_persona(self, resolver):
        with pytest.raises(ResolutionError, match="Persona not found"):
            resolver.resolve("nonexistent", "claude-code")

    def test_resolve_nonexistent_agent(self, resolver):
        with pytest.raises(ResolutionError, match="Agent profile not found"):
            resolver.resolve("research-reviewer", "nonexistent")

    def test_resolve_with_model_override(self, resolver):
        resolved = resolver.resolve(
            "research-reviewer", "claude-code",
            model_override="claude-opus-4-6",
        )
        assert resolved.model == "claude-opus-4-6"

    def test_resolve_with_capability_overrides(self, resolver):
        resolved = resolver.resolve(
            "research-reviewer", "claude-code",
            capability_overrides={"citation-validation": {"maxSourceAge": 2}},
        )
        # The prompt should reflect the override
        assert "2 years" in resolved.skill_prompt or "2" in resolved.skill_prompt

    def test_resolve_preview(self, resolver):
        preview = resolver.resolve_preview("research-reviewer", "claude-code")

        assert preview["status"] == "ok"
        assert preview["persona_name"] == "research-reviewer"
        assert preview["agent_name"] == "claude-code"
        assert preview["prompt_length"] > 0
        assert "citation-validation" in preview["capabilities_resolved"]

    def test_resolve_preview_error(self, resolver):
        preview = resolver.resolve_preview("nonexistent", "claude-code")
        assert preview["status"] == "error"

    def test_gateway_skill_payload(self, resolver):
        resolved = resolver.resolve("research-reviewer", "claude-code")
        payload = resolved.to_gateway_skill_payload()

        assert payload["name"] == "persona-research-reviewer-claude-code"
        assert payload["scope"] == "claude-code"
        assert len(payload["prompt"]) > 0

    def test_session_create_config(self, resolver):
        resolved = resolver.resolve("research-reviewer", "claude-code")
        config = resolved.to_session_create_config()

        assert config["mode"] == "bypassPermissions"
        assert config["model"] == "claude-sonnet-4-6"
        assert config["connectionMode"] == "spawn"
