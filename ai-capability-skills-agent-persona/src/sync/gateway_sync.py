"""GatewaySync — HTTP client that pushes resolved skills and MCPs to the CLI Agent Gateway."""

from __future__ import annotations

import httpx
import structlog

from src.models.resolved import ResolvedPersona, ResolvedMcp

logger = structlog.get_logger(__name__)


class GatewaySyncError(Exception):
    """Raised when a gateway sync operation fails."""


class GatewaySync:
    """
    Synchronises extension artifacts (skills, MCPs) with the CLI Agent Gateway.

    Operations:
    - Register/update a skill  → POST /skills
    - Register/update an MCP   → POST /mcps
    - Delete a skill            → DELETE /skills/{name}
    - Delete an MCP             → DELETE /mcps/{name}
    - Attach skill to session   → POST /sessions/{id}/skills/{name}
    - Attach MCP to session     → POST /sessions/{id}/mcps/{name}
    - Check gateway health      → GET /health
    - Check agent auth          → GET /agents/{agent}/auth
    """

    def __init__(self, gateway_http_url: str, timeout: float = 10.0) -> None:
        self.base_url = gateway_http_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Health ──

    async def check_health(self) -> bool:
        """Check if the gateway is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def check_agent_auth(self, agent_name: str) -> dict:
        """Check auth status of an agent via the gateway."""
        client = await self._get_client()
        resp = await client.get(f"/agents/{agent_name}/auth")
        resp.raise_for_status()
        return resp.json()

    # ── Skill Operations ──

    async def register_skill(self, name: str, prompt: str, scope: str = "global", description: str = "") -> dict:
        """Register or update a skill in the gateway's global registry."""
        client = await self._get_client()
        payload = {
            "name": name,
            "scope": scope,
            "description": description,
            "prompt": prompt,
        }
        resp = await client.post("/skills", json=payload)
        if resp.status_code not in (200, 201):
            logger.error("skill_register_failed", name=name, status=resp.status_code, body=resp.text)
            raise GatewaySyncError(f"Failed to register skill '{name}': {resp.status_code} {resp.text}")
        logger.info("skill_registered", name=name, scope=scope)
        return resp.json()

    async def delete_skill(self, name: str) -> bool:
        """Remove a skill from the gateway's global registry."""
        client = await self._get_client()
        resp = await client.delete(f"/skills/{name}")
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        logger.info("skill_deleted", name=name)
        return True

    async def list_skills(self) -> list[dict]:
        """List all skills in the gateway."""
        client = await self._get_client()
        resp = await client.get("/skills")
        resp.raise_for_status()
        return resp.json().get("skills", [])

    # ── MCP Operations ──

    async def register_mcp(self, mcp: ResolvedMcp) -> dict:
        """Register or update an MCP server in the gateway's global registry."""
        client = await self._get_client()
        payload = mcp.to_gateway_payload()
        resp = await client.post("/mcps", json=payload)
        if resp.status_code not in (200, 201):
            logger.error("mcp_register_failed", name=mcp.name, status=resp.status_code, body=resp.text)
            raise GatewaySyncError(f"Failed to register MCP '{mcp.name}': {resp.status_code} {resp.text}")
        logger.info("mcp_registered", name=mcp.name)
        return resp.json()

    async def delete_mcp(self, name: str) -> bool:
        """Remove an MCP from the gateway's global registry."""
        client = await self._get_client()
        resp = await client.delete(f"/mcps/{name}")
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        logger.info("mcp_deleted", name=name)
        return True

    async def list_mcps(self) -> list[dict]:
        """List all MCPs in the gateway."""
        client = await self._get_client()
        resp = await client.get("/mcps")
        resp.raise_for_status()
        return resp.json().get("mcps", [])

    # ── Session Attachment ──

    async def attach_skill_to_session(self, session_id: str, skill_name: str) -> dict:
        """Attach a registered skill to a live gateway session."""
        client = await self._get_client()
        resp = await client.post(f"/sessions/{session_id}/skills/{skill_name}")
        resp.raise_for_status()
        logger.info("skill_attached", session=session_id, skill=skill_name)
        return resp.json()

    async def detach_skill_from_session(self, session_id: str, skill_name: str) -> dict:
        """Detach a skill from a gateway session."""
        client = await self._get_client()
        resp = await client.delete(f"/sessions/{session_id}/skills/{skill_name}")
        resp.raise_for_status()
        return resp.json()

    async def attach_mcp_to_session(self, session_id: str, mcp_name: str) -> dict:
        """Attach a registered MCP to a live gateway session."""
        client = await self._get_client()
        resp = await client.post(f"/sessions/{session_id}/mcps/{mcp_name}")
        resp.raise_for_status()
        logger.info("mcp_attached", session=session_id, mcp=mcp_name)
        return resp.json()

    async def detach_mcp_from_session(self, session_id: str, mcp_name: str) -> dict:
        """Detach an MCP from a gateway session."""
        client = await self._get_client()
        resp = await client.delete(f"/sessions/{session_id}/mcps/{mcp_name}")
        resp.raise_for_status()
        return resp.json()

    # ── Bulk Sync ──

    async def sync_resolved_persona(self, resolved: ResolvedPersona) -> dict:
        """
        Register the skill and all MCPs for a resolved persona in the gateway.

        Does NOT attach to a session — call attach_to_session() separately.
        """
        results: dict = {"skill": None, "mcps": []}

        # Register assembled skill
        results["skill"] = await self.register_skill(
            name=resolved.skill_name,
            prompt=resolved.skill_prompt,
            scope=resolved.skill_scope,
            description=f"Persona: {resolved.persona_name} on {resolved.agent_name}",
        )

        # Register MCPs
        for mcp in resolved.mcps:
            result = await self.register_mcp(mcp)
            results["mcps"].append(result)

        logger.info(
            "persona_synced",
            persona=resolved.persona_name,
            agent=resolved.agent_name,
            mcps_count=len(resolved.mcps),
        )
        return results

    async def attach_to_session(self, session_id: str, resolved: ResolvedPersona) -> dict:
        """Attach a resolved persona's skill and MCPs to an existing gateway session."""
        results: dict = {"skill": None, "mcps": []}

        results["skill"] = await self.attach_skill_to_session(session_id, resolved.skill_name)

        for mcp in resolved.mcps:
            result = await self.attach_mcp_to_session(session_id, mcp.name)
            results["mcps"].append(result)

        return results
