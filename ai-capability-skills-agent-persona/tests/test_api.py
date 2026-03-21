"""Tests for the REST API endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "registry" in data


class TestPersonasAPI:
    @pytest.mark.asyncio
    async def test_list_personas(self, client):
        resp = await client.get("/api/v1/extensions/personas")
        assert resp.status_code == 200
        data = resp.json()
        assert "personas" in data
        assert len(data["personas"]) > 0

    @pytest.mark.asyncio
    async def test_get_persona(self, client):
        resp = await client.get("/api/v1/extensions/personas/research-reviewer")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["name"] == "research-reviewer"

    @pytest.mark.asyncio
    async def test_get_persona_not_found(self, client):
        resp = await client.get("/api/v1/extensions/personas/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_persona_json(self, client):
        resp = await client.post("/api/v1/extensions/personas", json={
            "json_content": {
                "apiVersion": "v1",
                "kind": "Persona",
                "metadata": {"name": "api-created"},
                "spec": {"identity": "Created via API."},
            }
        })
        assert resp.status_code == 201
        assert resp.json()["metadata"]["name"] == "api-created"

        # Verify it's in the list
        resp = await client.get("/api/v1/extensions/personas/api-created")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_persona_yaml(self, client):
        yaml_content = """
apiVersion: v1
kind: Persona
metadata:
  name: yaml-created
  description: "Created from YAML"
spec:
  identity: "You are a YAML-created agent."
"""
        resp = await client.post("/api/v1/extensions/personas", json={
            "yaml_content": yaml_content,
        })
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_delete_persona(self, client):
        # Create first
        await client.post("/api/v1/extensions/personas", json={
            "json_content": {
                "apiVersion": "v1",
                "kind": "Persona",
                "metadata": {"name": "to-delete"},
                "spec": {"identity": "Will be deleted."},
            }
        })
        # Delete
        resp = await client.delete("/api/v1/extensions/personas/to-delete")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "to-delete"

    @pytest.mark.asyncio
    async def test_filter_personas_by_tag(self, client):
        resp = await client.get("/api/v1/extensions/personas?tag=research")
        assert resp.status_code == 200
        data = resp.json()
        for p in data["personas"]:
            assert "research" in p["tags"]


class TestCapabilitiesAPI:
    @pytest.mark.asyncio
    async def test_list_capabilities(self, client):
        resp = await client.get("/api/v1/extensions/capabilities")
        assert resp.status_code == 200
        assert len(resp.json()["capabilities"]) > 0

    @pytest.mark.asyncio
    async def test_filter_by_agent(self, client):
        resp = await client.get("/api/v1/extensions/capabilities?agent=claude-code")
        assert resp.status_code == 200


class TestAgentsAPI:
    @pytest.mark.asyncio
    async def test_list_agents(self, client):
        resp = await client.get("/api/v1/extensions/agents")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        names = [a["name"] for a in agents]
        assert "claude-code" in names
        assert "gemini" in names

    @pytest.mark.asyncio
    async def test_get_agent_personas(self, client):
        resp = await client.get("/api/v1/extensions/agents/claude-code/personas")
        assert resp.status_code == 200
        assert len(resp.json()["personas"]) > 0


class TestResolveAPI:
    @pytest.mark.asyncio
    async def test_resolve_preview(self, client):
        resp = await client.get(
            "/api/v1/extensions/resolve",
            params={"persona_name": "research-reviewer", "agent_name": "claude-code"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["persona_name"] == "research-reviewer"

    @pytest.mark.asyncio
    async def test_resolve_preview_error(self, client):
        resp = await client.get(
            "/api/v1/extensions/resolve",
            params={"persona_name": "nonexistent", "agent_name": "claude-code"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


class TestReloadAPI:
    @pytest.mark.asyncio
    async def test_reload(self, client):
        resp = await client.post("/api/v1/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reloaded"] is True
        assert "summary" in data
