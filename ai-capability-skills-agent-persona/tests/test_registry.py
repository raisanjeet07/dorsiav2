"""Tests for the extension registry."""

import pytest
from pathlib import Path

from src.loader.yaml_loader import ExtensionLoader
from src.registry.extension_registry import ExtensionRegistry
from src.models.persona import Persona, PersonaMetadata, PersonaSpec
from src.models.capability import Capability, CapabilityMetadata, CapabilitySpec


DEFAULTS_DIR = Path(__file__).resolve().parent.parent / "defaults"


class TestExtensionRegistry:
    @pytest.fixture
    def loaded_registry(self):
        loader = ExtensionLoader(directories=[str(DEFAULTS_DIR)])
        result = loader.load_all()
        registry = ExtensionRegistry()
        registry.load_from_result(result)
        return registry

    def test_stats(self, loaded_registry):
        stats = loaded_registry.stats()
        assert stats["personas"] > 0
        assert stats["capabilities"] > 0
        assert stats["agent_profiles"] > 0

    def test_get_persona(self, loaded_registry):
        p = loaded_registry.get_persona("research-reviewer")
        assert p is not None
        assert p.name == "research-reviewer"

    def test_get_nonexistent(self, loaded_registry):
        assert loaded_registry.get_persona("nonexistent") is None

    def test_upsert_and_delete_persona(self, loaded_registry):
        p = Persona(
            metadata=PersonaMetadata(name="new-persona"),
            spec=PersonaSpec(identity="New."),
        )
        loaded_registry.upsert_persona(p)
        assert loaded_registry.get_persona("new-persona") is not None

        loaded_registry.delete_persona("new-persona")
        assert loaded_registry.get_persona("new-persona") is None

    def test_list_personas_by_tag(self, loaded_registry):
        personas = loaded_registry.list_personas(tag="research")
        assert len(personas) > 0
        for p in personas:
            assert "research" in p.metadata.tags

    def test_list_capabilities_by_agent(self, loaded_registry):
        caps = loaded_registry.list_capabilities(agent="claude-code")
        assert len(caps) > 0

    def test_find_personas_by_capability(self, loaded_registry):
        personas = loaded_registry.find_personas_by_capability("citation-validation")
        assert len(personas) > 0
        for p in personas:
            assert "citation-validation" in p.spec.capabilities

    def test_resolve_capability_chain(self, loaded_registry):
        # Add a capability with a dependency
        base = Capability(
            metadata=CapabilityMetadata(name="base-cap"),
            spec=CapabilitySpec(prompt="Base."),
        )
        dependent = Capability(
            metadata=CapabilityMetadata(name="dep-cap"),
            spec=CapabilitySpec(prompt="Dependent.", dependsOn=["base-cap"]),
        )
        loaded_registry.upsert_capability(base)
        loaded_registry.upsert_capability(dependent)

        chain = loaded_registry.resolve_capability_chain("dep-cap")
        names = [c.name for c in chain]
        assert names == ["base-cap", "dep-cap"]

    def test_circular_dependency_handled(self, loaded_registry):
        a = Capability(
            metadata=CapabilityMetadata(name="cap-a"),
            spec=CapabilitySpec(prompt="A.", dependsOn=["cap-b"]),
        )
        b = Capability(
            metadata=CapabilityMetadata(name="cap-b"),
            spec=CapabilitySpec(prompt="B.", dependsOn=["cap-a"]),
        )
        loaded_registry.upsert_capability(a)
        loaded_registry.upsert_capability(b)

        # Should not infinite loop
        chain = loaded_registry.resolve_capability_chain("cap-a")
        assert len(chain) >= 1
