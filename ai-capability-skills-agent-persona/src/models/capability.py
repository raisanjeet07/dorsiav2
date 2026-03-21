"""Capability model — defines WHAT an agent can do (reusable skill fragments)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CapabilityMetadata(BaseModel):
    """Metadata for a capability extension."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    version: str = "1.0.0"


class McpRequirement(BaseModel):
    """An MCP server required by this capability."""

    name: str
    type: str = "stdio"  # stdio | sse | http
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    only_if: str = Field(default="", alias="onlyIf", description="Conditional expression, e.g. 'agent == claude-code'")

    model_config = {"populate_by_name": True}

    def matches_agent(self, agent_name: str) -> bool:
        """Evaluate the onlyIf condition against the given agent name."""
        if not self.only_if:
            return True
        # Simple evaluator: supports "agent == <name>" and "agent != <name>"
        expr = self.only_if.strip()
        if "==" in expr:
            _, value = expr.split("==", 1)
            return value.strip().strip('"').strip("'") == agent_name
        if "!=" in expr:
            _, value = expr.split("!=", 1)
            return value.strip().strip('"').strip("'") != agent_name
        return True


class ConfigKnob(BaseModel):
    """A configuration parameter that can be overridden per-persona or per-workflow."""

    type: str = "string"  # string | integer | boolean | float
    default: Any = None
    description: str = ""


class CapabilitySpec(BaseModel):
    """The spec block of a Capability definition."""

    prompt: str = Field(..., min_length=1, description="Prompt fragment injected when this capability is active")
    compatible_agents: list[str] = Field(default_factory=list, alias="compatibleAgents")
    required_mcps: list[McpRequirement] = Field(default_factory=list, alias="requiredMcps")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    config: dict[str, ConfigKnob] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    def is_compatible_with(self, agent_name: str) -> bool:
        """Check if this capability works with the given agent."""
        if not self.compatible_agents:
            return True  # empty means compatible with all
        return agent_name in self.compatible_agents

    def render_prompt(self, config_overrides: dict[str, Any] | None = None) -> str:
        """Render the prompt, substituting any config values."""
        prompt = self.prompt
        resolved_config: dict[str, Any] = {}
        for key, knob in self.config.items():
            resolved_config[key] = knob.default
        if config_overrides:
            resolved_config.update(config_overrides)

        # Simple template substitution: {config.maxSourceAge} → value
        for key, value in resolved_config.items():
            prompt = prompt.replace(f"{{config.{key}}}", str(value))

        return prompt


class Capability(BaseModel):
    """
    Top-level Capability extension.

    A capability defines a reusable skill fragment (prompt + MCPs + config knobs)
    that can be composed into personas or attached independently.
    """

    api_version: str = Field(default="v1", alias="apiVersion")
    kind: str = "Capability"
    metadata: CapabilityMetadata
    spec: CapabilitySpec

    model_config = {"populate_by_name": True}

    @property
    def name(self) -> str:
        return self.metadata.name
