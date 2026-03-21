"""REST endpoints for AgentProfile CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentProfileSummary(BaseModel):
    name: str
    description: str
    version: str
    gateway_flow: str
    default_mode: str
    default_model: str
    supported_modes: list[str]
    is_gateway_agent: bool


class AgentProfileCreateRequest(BaseModel):
    yaml_content: str | None = None
    json_content: dict | None = None


@router.get("", summary="List all agent profiles")
async def list_agent_profiles(request: Request):
    registry = request.app.state.registry
    profiles = registry.list_agent_profiles()
    return {
        "agents": [
            AgentProfileSummary(
                name=p.name,
                description=p.metadata.description,
                version=p.metadata.version,
                gateway_flow=p.spec.gateway_flow,
                default_mode=p.spec.defaults.mode,
                default_model=p.spec.defaults.model,
                supported_modes=p.spec.supported_modes,
                is_gateway_agent=p.spec.is_gateway_agent,
            ).model_dump()
            for p in profiles
        ]
    }


@router.get("/{name}", summary="Get agent profile detail")
async def get_agent_profile(name: str, request: Request):
    registry = request.app.state.registry
    profile = registry.get_agent_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Agent profile not found: {name}")
    return profile.model_dump(by_alias=True)


@router.get("/{name}/personas", summary="List personas compatible with this agent")
async def list_agent_personas(name: str, request: Request):
    registry = request.app.state.registry
    profile = registry.get_agent_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Agent profile not found: {name}")

    personas = registry.find_personas_by_agent(name)
    return {
        "agent": name,
        "personas": [
            {
                "name": p.name,
                "description": p.metadata.description,
                "capabilities": p.spec.capabilities,
            }
            for p in personas
        ],
    }


@router.post("", status_code=201, summary="Register a new agent profile")
async def create_agent_profile(body: AgentProfileCreateRequest, request: Request):
    loader = request.app.state.loader
    registry = request.app.state.registry
    persistence = request.app.state.persistence

    if body.yaml_content:
        profile = loader.parse_yaml_string(body.yaml_content, kind="AgentProfile")
    elif body.json_content:
        from src.models.agent_profile import AgentProfile
        try:
            profile = AgentProfile.model_validate(body.json_content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid agent profile: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide yaml_content or json_content")

    if profile is None:
        raise HTTPException(status_code=400, detail="Failed to parse agent profile")

    registry.upsert_agent_profile(profile)

    if persistence:
        await persistence.save_extension(profile, "agents")

    return profile.model_dump(by_alias=True)


@router.put("/{name}", summary="Update an existing agent profile")
async def update_agent_profile(name: str, body: AgentProfileCreateRequest, request: Request):
    registry = request.app.state.registry
    loader = request.app.state.loader
    persistence = request.app.state.persistence

    existing = registry.get_agent_profile(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Agent profile not found: {name}")

    if body.yaml_content:
        profile = loader.parse_yaml_string(body.yaml_content, kind="AgentProfile")
    elif body.json_content:
        from src.models.agent_profile import AgentProfile
        try:
            profile = AgentProfile.model_validate(body.json_content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid agent profile: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide yaml_content or json_content")

    if profile is None:
        raise HTTPException(status_code=400, detail="Failed to parse agent profile")

    if profile.name != name:
        raise HTTPException(status_code=400, detail=f"Name mismatch: URL has '{name}', body has '{profile.name}'")

    registry.upsert_agent_profile(profile)

    if persistence:
        await persistence.save_extension(profile, "agents")

    return profile.model_dump(by_alias=True)


@router.delete("/{name}", summary="Delete an agent profile")
async def delete_agent_profile(name: str, request: Request):
    registry = request.app.state.registry
    persistence = request.app.state.persistence

    # Check if any persona references this agent
    personas = registry.find_personas_by_agent(name)
    agent_specific = [p for p in personas if p.spec.gateway_skill.scope == name]
    if agent_specific:
        names = [p.name for p in agent_specific]
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: agent profile is referenced by personas: {names}",
        )

    deleted = registry.delete_agent_profile(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent profile not found: {name}")

    if persistence:
        await persistence.delete_extension(name, "agents")

    return {"deleted": name}
