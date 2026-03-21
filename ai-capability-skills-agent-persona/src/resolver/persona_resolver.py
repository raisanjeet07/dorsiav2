"""PersonaResolver — composes persona + capabilities + agent profile into a ResolvedPersona."""

from __future__ import annotations

from typing import Any

import structlog

from src.models.persona import Persona
from src.models.capability import Capability
from src.models.agent_profile import AgentProfile
from src.models.resolved import ResolvedPersona, ResolvedMcp
from src.registry.extension_registry import ExtensionRegistry

logger = structlog.get_logger(__name__)


class ResolutionError(Exception):
    """Raised when persona resolution fails."""


class PersonaResolver:
    """
    Resolves a persona name + agent name into a fully composed ResolvedPersona.

    Resolution chain:
    1. Look up Persona by name
    2. Look up AgentProfile by name
    3. Resolve all capabilities (including transitive deps)
    4. Filter capabilities by agent compatibility
    5. Render capability prompts (with config overrides)
    6. Assemble final prompt via agent's promptTemplate
    7. Collect all required MCPs (filtered by agent)
    8. Package everything into a ResolvedPersona
    """

    def __init__(self, registry: ExtensionRegistry) -> None:
        self.registry = registry

    def resolve(
        self,
        persona_name: str,
        agent_name: str,
        capability_overrides: dict[str, dict[str, Any]] | None = None,
        model_override: str | None = None,
        mode_override: str | None = None,
    ) -> ResolvedPersona:
        """
        Fully resolve a persona for a given agent.

        Args:
            persona_name: Name of the persona to resolve.
            agent_name: Name of the agent profile to use.
            capability_overrides: Per-capability config overrides.
                e.g. {"citation-validation": {"maxSourceAge": 3}}
            model_override: Override the agent's default model.
            mode_override: Override the agent's default mode.

        Returns:
            A ResolvedPersona ready for gateway sync.

        Raises:
            ResolutionError: If persona or agent not found, or circular deps detected.
        """
        capability_overrides = capability_overrides or {}

        # Step 1: Look up persona
        persona = self.registry.get_persona(persona_name)
        if persona is None:
            raise ResolutionError(f"Persona not found: {persona_name}")

        # Step 2: Look up agent profile
        agent = self.registry.get_agent_profile(agent_name)
        if agent is None:
            raise ResolutionError(f"Agent profile not found: {agent_name}")

        # Step 3: Resolve all capabilities (with transitive deps)
        all_capabilities: list[Capability] = []
        seen_names: set[str] = set()
        for cap_name in persona.spec.capabilities:
            chain = self.registry.resolve_capability_chain(cap_name)
            for cap in chain:
                if cap.name not in seen_names:
                    seen_names.add(cap.name)
                    all_capabilities.append(cap)

        # Step 4: Filter by agent compatibility
        compatible_caps = [
            cap for cap in all_capabilities
            if cap.spec.is_compatible_with(agent_name)
        ]
        skipped = len(all_capabilities) - len(compatible_caps)
        if skipped > 0:
            logger.info(
                "capabilities_skipped_incompatible",
                persona=persona_name,
                agent=agent_name,
                skipped=skipped,
            )

        # Step 5: Render capability prompts with overrides
        capability_prompts: list[str] = []
        for cap in compatible_caps:
            overrides = capability_overrides.get(cap.name, {})
            rendered = cap.spec.render_prompt(config_overrides=overrides)
            capability_prompts.append(rendered)

        # Step 6: Assemble the prompt
        if persona.spec.gateway_skill.prompt_override:
            # Explicit override takes precedence
            skill_prompt = persona.spec.gateway_skill.prompt_override
        else:
            # Use persona's assemble_prompt which builds from identity + behavior + output schema
            persona_prompt = persona.assemble_prompt(capability_prompts)

            # Wrap with agent's prompt template
            template = agent.spec.prompt_template
            skill_prompt = template.replace("{persona_prompt}", persona_prompt)
            skill_prompt = skill_prompt.replace(
                "{capability_prompts}",
                "\n\n".join(capability_prompts) if capability_prompts else "",
            )

        # Step 7: Collect MCPs
        mcps: list[ResolvedMcp] = []
        if agent.spec.capability_application.mcps == "attach":
            for cap in compatible_caps:
                for mcp_req in cap.spec.required_mcps:
                    if mcp_req.matches_agent(agent_name):
                        mcps.append(ResolvedMcp(
                            name=mcp_req.name,
                            scope=persona.spec.gateway_skill.scope,
                            type=mcp_req.type,
                            command=mcp_req.command,
                            args=mcp_req.args,
                            url=mcp_req.url,
                            env=mcp_req.env,
                        ))

        # Step 8: Build the result
        skill_name = f"persona-{persona_name}-{agent_name}"
        defaults = agent.spec.defaults

        return ResolvedPersona(
            persona_name=persona_name,
            agent_name=agent_name,
            skill_prompt=skill_prompt,
            skill_name=skill_name,
            skill_scope=persona.spec.gateway_skill.scope,
            gateway_flow=agent.spec.gateway_flow,
            mode=mode_override or defaults.mode,
            model=model_override or defaults.model,
            connection_mode=defaults.connection_mode,
            mcps=mcps,
            persona_application_method=agent.spec.persona_application.method,
            prompt_template=agent.spec.prompt_template,
            persona_version=persona.metadata.version,
            capability_names=[cap.name for cap in compatible_caps],
        )

    def resolve_preview(
        self,
        persona_name: str,
        agent_name: str,
        capability_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> dict:
        """
        Dry-run resolve — returns a preview dict without side effects.

        Useful for the GET /extensions/resolve endpoint.
        """
        try:
            resolved = self.resolve(persona_name, agent_name, capability_overrides)
            return {
                "status": "ok",
                "persona_name": resolved.persona_name,
                "agent_name": resolved.agent_name,
                "skill_name": resolved.skill_name,
                "skill_scope": resolved.skill_scope,
                "gateway_flow": resolved.gateway_flow,
                "mode": resolved.mode,
                "model": resolved.model,
                "capabilities_resolved": resolved.capability_names,
                "mcps_count": len(resolved.mcps),
                "mcps": [m.to_gateway_payload() for m in resolved.mcps],
                "prompt_length": len(resolved.skill_prompt),
                "prompt_preview": resolved.skill_prompt[:500] + ("..." if len(resolved.skill_prompt) > 500 else ""),
            }
        except ResolutionError as e:
            return {"status": "error", "error": str(e)}
