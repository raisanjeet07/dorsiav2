"""AgentProfile model — defines HOW to interact with an agent backend."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentProfileMetadata(BaseModel):
    """Metadata for an agent profile."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = ""
    version: str = "1.0.0"


class PersonaApplication(BaseModel):
    """How personas are applied to this agent type."""

    method: str = "skill"  # skill | systemPrompt | appendPrompt

    # "skill"         → register as gateway skill, attach per-session
    # "systemPrompt"  → inject via --append-system-prompt flag
    # "appendPrompt"  → prepend to every prompt.send content


class CapabilityApplication(BaseModel):
    """How capabilities are applied to this agent type."""

    skills: str = "merge"   # merge | individual
    mcps: str = "attach"    # attach | none

    # "merge"      → all capability prompts merged into a single persona skill
    # "individual" → each capability registered as a separate gateway skill
    # "attach"     → each capability's MCPs attached individually to the session
    # "none"       → MCPs not supported by this agent


class HealthCheckConfig(BaseModel):
    """How to verify this agent is healthy / authenticated."""

    endpoint: str = ""        # e.g. /agents/claude-code/auth
    field: str = ""           # e.g. loggedIn
    expected_value: bool | str = Field(default=True, alias="expectedValue")

    model_config = {"populate_by_name": True}


class SessionDefaults(BaseModel):
    """Default session configuration for this agent."""

    mode: str = "default"
    model: str = ""
    connection_mode: str = Field(default="spawn", alias="connectionMode")
    working_dir: str = Field(default="", alias="workingDir")
    extra_config: dict[str, str] = Field(default_factory=dict, alias="extraConfig")

    model_config = {"populate_by_name": True}


class AgentProfileSpec(BaseModel):
    """The spec block of an AgentProfile definition."""

    # Gateway integration
    gateway_flow: str = Field(default="", alias="gatewayFlow", description="Maps to gateway 'flow' field")

    # For non-gateway agents (direct HTTP, etc.)
    adapter: str = ""          # e.g. "http-completion"
    endpoint: str = ""         # e.g. "http://localhost:11434/api/generate"

    # Session defaults
    defaults: SessionDefaults = Field(default_factory=SessionDefaults)

    # Supported modes (informational)
    supported_modes: list[str] = Field(default_factory=list, alias="supportedModes")

    # How persona/capabilities are injected
    persona_application: PersonaApplication = Field(default_factory=PersonaApplication, alias="personaApplication")
    capability_application: CapabilityApplication = Field(default_factory=CapabilityApplication, alias="capabilityApplication")

    # Prompt template with placeholders
    prompt_template: str = Field(
        default="{persona_prompt}\n\n{capability_prompts}",
        alias="promptTemplate",
    )

    # Health check
    health_check: HealthCheckConfig = Field(default_factory=HealthCheckConfig, alias="healthCheck")

    model_config = {"populate_by_name": True}

    @property
    def is_gateway_agent(self) -> bool:
        """True if this agent communicates through the CLI Agent Gateway."""
        return bool(self.gateway_flow)


class AgentProfile(BaseModel):
    """
    Top-level AgentProfile extension.

    An agent profile defines how to connect to and interact with a specific
    agent backend — its connection settings, supported modes, and defaults.
    """

    api_version: str = Field(default="v1", alias="apiVersion")
    kind: str = "AgentProfile"
    metadata: AgentProfileMetadata
    spec: AgentProfileSpec

    model_config = {"populate_by_name": True}

    @property
    def name(self) -> str:
        return self.metadata.name
