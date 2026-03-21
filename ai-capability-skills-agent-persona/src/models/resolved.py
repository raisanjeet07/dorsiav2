"""Resolved models — the output of composing persona + capabilities + agent profile."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResolvedMcp(BaseModel):
    """An MCP server config ready to be registered with the gateway."""

    name: str
    scope: str = "global"
    type: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)

    def to_gateway_payload(self) -> dict:
        """Convert to the JSON body expected by POST /mcps."""
        payload: dict = {
            "name": self.name,
            "scope": self.scope,
            "type": self.type,
        }
        if self.type == "stdio":
            payload["command"] = self.command
            if self.args:
                payload["args"] = self.args
        else:
            payload["url"] = self.url
        if self.env:
            payload["env"] = self.env
        return payload


class ResolvedPersona(BaseModel):
    """
    The fully resolved result of composing a Persona + its Capabilities + an AgentProfile.

    This is what consumers use to create gateway sessions.
    """

    # Identity
    persona_name: str
    agent_name: str

    # Assembled prompt (identity + behavior + capabilities + output schema)
    skill_prompt: str
    skill_name: str = Field(description="Name to register this as a gateway skill")
    skill_scope: str = "global"

    # Session configuration
    gateway_flow: str = ""
    mode: str = "default"
    model: str = ""
    connection_mode: str = "spawn"

    # MCPs to attach
    mcps: list[ResolvedMcp] = Field(default_factory=list)

    # Persona application method
    persona_application_method: str = "skill"

    # Prompt template (with {persona_prompt} and {capability_prompts} already resolved)
    prompt_template: str = ""

    # Source metadata
    persona_version: str = "1.0.0"
    capability_names: list[str] = Field(default_factory=list)

    def to_gateway_skill_payload(self) -> dict:
        """Convert to the JSON body expected by POST /skills."""
        return {
            "name": self.skill_name,
            "scope": self.skill_scope,
            "description": f"Assembled persona: {self.persona_name} ({', '.join(self.capability_names)})",
            "prompt": self.skill_prompt,
        }

    def to_session_create_config(self) -> dict:
        """Build the config for a gateway session.create payload."""
        config: dict = {}
        if self.mode:
            config["mode"] = self.mode
        if self.model:
            config["model"] = self.model
        config["connectionMode"] = self.connection_mode
        return config
