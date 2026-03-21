"""Persona model — defines WHO the agent is."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PersonaMetadata(BaseModel):
    """Metadata block common to all extension types."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    author: str = ""
    version: str = "1.0.0"


class PersonaBehavior(BaseModel):
    """Behavioral instructions for the persona."""

    tone: str = "professional"
    critical_thinking: str = Field(default="high", alias="criticalThinking")
    evidence_requirement: str = Field(default="moderate", alias="evidenceRequirement")
    bias_detection: bool = Field(default=False, alias="biasDetection")
    output_language: str = Field(default="english", alias="outputLanguage")
    extra: dict[str, str | bool | int] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class OutputSchema(BaseModel):
    """Expected output format for the persona."""

    format: str = "json"  # json | markdown | text
    template: str = ""


class GatewaySkillConfig(BaseModel):
    """How this persona maps to a CLI Agent Gateway skill."""

    scope: str = "global"  # global | claude-code | gemini | cursor
    prompt_override: str = Field(default="", alias="promptOverride")

    model_config = {"populate_by_name": True}


class PersonaSpec(BaseModel):
    """The spec block of a Persona definition."""

    identity: str = Field(..., min_length=1, description="Core identity prompt for the agent")
    behavior: PersonaBehavior = Field(default_factory=PersonaBehavior)
    review_dimensions: list[str] = Field(default_factory=list, alias="reviewDimensions")
    output_schema: OutputSchema | None = Field(default=None, alias="outputSchema")
    capabilities: list[str] = Field(default_factory=list, description="Capability names to compose into this persona")
    gateway_skill: GatewaySkillConfig = Field(default_factory=GatewaySkillConfig, alias="gatewaySkill")

    model_config = {"populate_by_name": True}


class Persona(BaseModel):
    """
    Top-level Persona extension.

    A persona defines the agent's identity, behavioral instructions,
    review dimensions, output expectations, and composed capabilities.
    """

    api_version: str = Field(default="v1", alias="apiVersion")
    kind: str = "Persona"
    metadata: PersonaMetadata
    spec: PersonaSpec

    model_config = {"populate_by_name": True}

    @property
    def name(self) -> str:
        return self.metadata.name

    def assemble_prompt(self, capability_prompts: list[str] | None = None) -> str:
        """Assemble the full prompt from identity + behavior + capabilities + output schema."""
        parts: list[str] = []

        # Identity
        parts.append(self.spec.identity.strip())

        # Behavior instructions
        behavior = self.spec.behavior
        behavior_lines = [
            f"Tone: {behavior.tone}",
            f"Critical thinking level: {behavior.critical_thinking}",
            f"Evidence requirement: {behavior.evidence_requirement}",
        ]
        if behavior.bias_detection:
            behavior_lines.append("Actively detect and flag potential biases.")
        if behavior.output_language != "english":
            behavior_lines.append(f"Output language: {behavior.output_language}")
        parts.append("\n".join(behavior_lines))

        # Review dimensions
        if self.spec.review_dimensions:
            dims = ", ".join(self.spec.review_dimensions)
            parts.append(f"Review dimensions to evaluate: {dims}")

        # Capability prompts
        if capability_prompts:
            parts.append("--- Additional Capabilities ---")
            for cp in capability_prompts:
                parts.append(cp.strip())

        # Output schema
        if self.spec.output_schema and self.spec.output_schema.template:
            parts.append(f"Output format: {self.spec.output_schema.format}")
            parts.append(f"Follow this output schema exactly:\n{self.spec.output_schema.template.strip()}")

        return "\n\n".join(parts)
