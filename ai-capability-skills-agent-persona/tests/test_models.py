"""Tests for Pydantic models."""

import pytest
from src.models.persona import Persona, PersonaMetadata, PersonaSpec, PersonaBehavior, OutputSchema, GatewaySkillConfig
from src.models.capability import Capability, CapabilityMetadata, CapabilitySpec, McpRequirement, ConfigKnob
from src.models.agent_profile import AgentProfile, AgentProfileMetadata, AgentProfileSpec


class TestPersona:
    def test_minimal_persona(self):
        p = Persona(
            metadata=PersonaMetadata(name="test-persona"),
            spec=PersonaSpec(identity="You are a test agent."),
        )
        assert p.name == "test-persona"
        assert p.kind == "Persona"
        assert p.spec.identity == "You are a test agent."

    def test_persona_assemble_prompt(self):
        p = Persona(
            metadata=PersonaMetadata(name="reviewer"),
            spec=PersonaSpec(
                identity="You are a reviewer.",
                behavior=PersonaBehavior(tone="formal", criticalThinking="high"),
                reviewDimensions=["accuracy", "completeness"],
                outputSchema=OutputSchema(format="json", template='{"result": "..."}'),
            ),
        )
        prompt = p.assemble_prompt(capability_prompts=["Check citations."])
        assert "You are a reviewer." in prompt
        assert "formal" in prompt
        assert "accuracy, completeness" in prompt
        assert "Check citations." in prompt
        assert '{"result": "..."}' in prompt

    def test_persona_name_validation(self):
        with pytest.raises(Exception):
            PersonaMetadata(name="Invalid Name!")

    def test_persona_from_dict(self):
        data = {
            "apiVersion": "v1",
            "kind": "Persona",
            "metadata": {"name": "from-dict", "description": "test"},
            "spec": {"identity": "You are helpful."},
        }
        p = Persona.model_validate(data)
        assert p.name == "from-dict"


class TestCapability:
    def test_minimal_capability(self):
        c = Capability(
            metadata=CapabilityMetadata(name="test-cap"),
            spec=CapabilitySpec(prompt="Do the thing."),
        )
        assert c.name == "test-cap"
        assert c.kind == "Capability"

    def test_capability_compatibility(self):
        c = Capability(
            metadata=CapabilityMetadata(name="claude-only"),
            spec=CapabilitySpec(
                prompt="Claude specific.",
                compatibleAgents=["claude-code"],
            ),
        )
        assert c.spec.is_compatible_with("claude-code") is True
        assert c.spec.is_compatible_with("gemini") is False

    def test_capability_empty_compatible_means_all(self):
        c = Capability(
            metadata=CapabilityMetadata(name="universal"),
            spec=CapabilitySpec(prompt="Universal."),
        )
        assert c.spec.is_compatible_with("anything") is True

    def test_mcp_requirement_condition(self):
        mcp = McpRequirement(
            name="test-mcp",
            type="stdio",
            command="npx",
            onlyIf='agent == "claude-code"',
        )
        assert mcp.matches_agent("claude-code") is True
        assert mcp.matches_agent("gemini") is False

    def test_capability_render_prompt_with_overrides(self):
        c = Capability(
            metadata=CapabilityMetadata(name="configurable"),
            spec=CapabilitySpec(
                prompt="Max age: {config.maxAge} years.",
                config={"maxAge": ConfigKnob(type="integer", default=5)},
            ),
        )
        rendered = c.spec.render_prompt()
        assert "5 years" in rendered

        rendered_override = c.spec.render_prompt(config_overrides={"maxAge": 3})
        assert "3 years" in rendered_override


class TestAgentProfile:
    def test_minimal_agent_profile(self):
        a = AgentProfile(
            metadata=AgentProfileMetadata(name="test-agent"),
            spec=AgentProfileSpec(gatewayFlow="claude-code"),
        )
        assert a.name == "test-agent"
        assert a.spec.is_gateway_agent is True

    def test_non_gateway_agent(self):
        a = AgentProfile(
            metadata=AgentProfileMetadata(name="local-llm"),
            spec=AgentProfileSpec(adapter="http-completion", endpoint="http://localhost:11434"),
        )
        assert a.spec.is_gateway_agent is False
