"""In-memory registry for all extension types with CRUD, query, and tagging."""

from __future__ import annotations

import threading
from typing import Any

import structlog

from src.models.persona import Persona
from src.models.capability import Capability
from src.models.agent_profile import AgentProfile

logger = structlog.get_logger(__name__)


class ExtensionRegistry:
    """
    Thread-safe in-memory store for Personas, Capabilities, and AgentProfiles.

    Supports CRUD operations, tag-based queries, and bulk loading from a LoadResult.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._personas: dict[str, Persona] = {}
        self._capabilities: dict[str, Capability] = {}
        self._agent_profiles: dict[str, AgentProfile] = {}

    # ── Bulk Load ──

    def load_from_result(self, result: Any) -> None:
        """Populate the registry from an ExtensionLoader.LoadResult."""
        with self._lock:
            self._personas.update(result.personas)
            self._capabilities.update(result.capabilities)
            self._agent_profiles.update(result.agent_profiles)
        logger.info(
            "registry_populated",
            personas=len(self._personas),
            capabilities=len(self._capabilities),
            agent_profiles=len(self._agent_profiles),
        )

    # ── Persona CRUD ──

    def get_persona(self, name: str) -> Persona | None:
        with self._lock:
            return self._personas.get(name)

    def list_personas(self, tag: str | None = None) -> list[Persona]:
        with self._lock:
            personas = list(self._personas.values())
        if tag:
            personas = [p for p in personas if tag in p.metadata.tags]
        return personas

    def upsert_persona(self, persona: Persona) -> None:
        with self._lock:
            self._personas[persona.name] = persona
        logger.info("persona_upserted", name=persona.name)

    def delete_persona(self, name: str) -> bool:
        with self._lock:
            if name in self._personas:
                del self._personas[name]
                logger.info("persona_deleted", name=name)
                return True
            return False

    # ── Capability CRUD ──

    def get_capability(self, name: str) -> Capability | None:
        with self._lock:
            return self._capabilities.get(name)

    def list_capabilities(self, tag: str | None = None, agent: str | None = None) -> list[Capability]:
        with self._lock:
            caps = list(self._capabilities.values())
        if tag:
            caps = [c for c in caps if tag in c.metadata.tags]
        if agent:
            caps = [c for c in caps if c.spec.is_compatible_with(agent)]
        return caps

    def upsert_capability(self, capability: Capability) -> None:
        with self._lock:
            self._capabilities[capability.name] = capability
        logger.info("capability_upserted", name=capability.name)

    def delete_capability(self, name: str) -> bool:
        with self._lock:
            if name in self._capabilities:
                del self._capabilities[name]
                logger.info("capability_deleted", name=name)
                return True
            return False

    # ── AgentProfile CRUD ──

    def get_agent_profile(self, name: str) -> AgentProfile | None:
        with self._lock:
            return self._agent_profiles.get(name)

    def list_agent_profiles(self) -> list[AgentProfile]:
        with self._lock:
            return list(self._agent_profiles.values())

    def upsert_agent_profile(self, profile: AgentProfile) -> None:
        with self._lock:
            self._agent_profiles[profile.name] = profile
        logger.info("agent_profile_upserted", name=profile.name)

    def delete_agent_profile(self, name: str) -> bool:
        with self._lock:
            if name in self._agent_profiles:
                del self._agent_profiles[name]
                logger.info("agent_profile_deleted", name=name)
                return True
            return False

    # ── Cross-cutting Queries ──

    def find_personas_by_capability(self, capability_name: str) -> list[Persona]:
        """Find all personas that use a given capability."""
        with self._lock:
            return [
                p for p in self._personas.values()
                if capability_name in p.spec.capabilities
            ]

    def find_personas_by_agent(self, agent_name: str) -> list[Persona]:
        """Find all personas scoped to a given agent."""
        with self._lock:
            return [
                p for p in self._personas.values()
                if p.spec.gateway_skill.scope in (agent_name, "global")
            ]

    def resolve_capability_chain(self, capability_name: str, _visited: set[str] | None = None) -> list[Capability]:
        """Resolve a capability and all its transitive dependencies (topological order)."""
        if _visited is None:
            _visited = set()

        if capability_name in _visited:
            logger.warning("circular_dependency_detected", capability=capability_name)
            return []

        _visited.add(capability_name)
        cap = self.get_capability(capability_name)
        if cap is None:
            logger.warning("capability_not_found", name=capability_name)
            return []

        result: list[Capability] = []
        for dep_name in cap.spec.depends_on:
            result.extend(self.resolve_capability_chain(dep_name, _visited))
        result.append(cap)
        return result

    # ── Stats ──

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "personas": len(self._personas),
                "capabilities": len(self._capabilities),
                "agent_profiles": len(self._agent_profiles),
            }
