"""REST endpoints for Persona CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/personas", tags=["personas"])


class PersonaSummary(BaseModel):
    name: str
    description: str
    tags: list[str]
    version: str
    capabilities: list[str]
    scope: str


class PersonaCreateRequest(BaseModel):
    """Accept raw YAML string or JSON body for creating a persona."""
    yaml_content: str | None = None
    json_content: dict | None = None


@router.get("", summary="List all personas")
async def list_personas(request: Request, tag: str | None = None):
    registry = request.app.state.registry
    personas = registry.list_personas(tag=tag)
    return {
        "personas": [
            PersonaSummary(
                name=p.name,
                description=p.metadata.description,
                tags=p.metadata.tags,
                version=p.metadata.version,
                capabilities=p.spec.capabilities,
                scope=p.spec.gateway_skill.scope,
            ).model_dump()
            for p in personas
        ]
    }


@router.get("/{name}", summary="Get persona detail")
async def get_persona(name: str, request: Request):
    registry = request.app.state.registry
    persona = registry.get_persona(name)
    if persona is None:
        raise HTTPException(status_code=404, detail=f"Persona not found: {name}")
    return persona.model_dump(by_alias=True)


@router.post("", status_code=201, summary="Register a new persona")
async def create_persona(body: PersonaCreateRequest, request: Request):
    loader = request.app.state.loader
    registry = request.app.state.registry
    persistence = request.app.state.persistence

    if body.yaml_content:
        persona = loader.parse_yaml_string(body.yaml_content, kind="Persona")
    elif body.json_content:
        from src.models.persona import Persona
        try:
            persona = Persona.model_validate(body.json_content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid persona: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide yaml_content or json_content")

    if persona is None:
        raise HTTPException(status_code=400, detail="Failed to parse persona YAML")

    registry.upsert_persona(persona)

    # Persist to disk if enabled
    if persistence:
        await persistence.save_extension(persona, "personas")

    # Sync to gateway if enabled
    gateway_sync = request.app.state.gateway_sync
    if gateway_sync:
        try:
            resolver = request.app.state.resolver
            # Try to find a matching agent profile for the persona's scope
            agent_name = persona.spec.gateway_skill.scope
            if agent_name != "global":
                resolved = resolver.resolve(persona.name, agent_name)
                await gateway_sync.sync_resolved_persona(resolved)
        except Exception as e:
            # Don't fail the registration just because gateway sync failed
            pass

    return persona.model_dump(by_alias=True)


@router.put("/{name}", summary="Update an existing persona")
async def update_persona(name: str, body: PersonaCreateRequest, request: Request):
    registry = request.app.state.registry
    loader = request.app.state.loader
    persistence = request.app.state.persistence

    existing = registry.get_persona(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Persona not found: {name}")

    if body.yaml_content:
        persona = loader.parse_yaml_string(body.yaml_content, kind="Persona")
    elif body.json_content:
        from src.models.persona import Persona
        try:
            persona = Persona.model_validate(body.json_content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid persona: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide yaml_content or json_content")

    if persona is None:
        raise HTTPException(status_code=400, detail="Failed to parse persona")

    if persona.name != name:
        raise HTTPException(status_code=400, detail=f"Name mismatch: URL has '{name}', body has '{persona.name}'")

    registry.upsert_persona(persona)

    if persistence:
        await persistence.save_extension(persona, "personas")

    return persona.model_dump(by_alias=True)


@router.delete("/{name}", summary="Delete a persona")
async def delete_persona(name: str, request: Request):
    registry = request.app.state.registry
    persistence = request.app.state.persistence

    deleted = registry.delete_persona(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Persona not found: {name}")

    if persistence:
        await persistence.delete_extension(name, "personas")

    # Try to clean up from gateway
    gateway_sync = request.app.state.gateway_sync
    if gateway_sync:
        try:
            # Attempt to delete any skills that were generated for this persona
            await gateway_sync.delete_skill(f"persona-{name}-claude-code")
            await gateway_sync.delete_skill(f"persona-{name}-gemini")
        except Exception:
            pass

    return {"deleted": name}
