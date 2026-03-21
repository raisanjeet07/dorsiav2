"""REST endpoints for Capability CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


class CapabilitySummary(BaseModel):
    name: str
    description: str
    tags: list[str]
    version: str
    compatible_agents: list[str]
    depends_on: list[str]
    config_knobs: list[str]


class CapabilityCreateRequest(BaseModel):
    yaml_content: str | None = None
    json_content: dict | None = None


@router.get("", summary="List all capabilities")
async def list_capabilities(request: Request, tag: str | None = None, agent: str | None = None):
    registry = request.app.state.registry
    capabilities = registry.list_capabilities(tag=tag, agent=agent)
    return {
        "capabilities": [
            CapabilitySummary(
                name=c.name,
                description=c.metadata.description,
                tags=c.metadata.tags,
                version=c.metadata.version,
                compatible_agents=c.spec.compatible_agents,
                depends_on=c.spec.depends_on,
                config_knobs=list(c.spec.config.keys()),
            ).model_dump()
            for c in capabilities
        ]
    }


@router.get("/{name}", summary="Get capability detail")
async def get_capability(name: str, request: Request):
    registry = request.app.state.registry
    cap = registry.get_capability(name)
    if cap is None:
        raise HTTPException(status_code=404, detail=f"Capability not found: {name}")
    return cap.model_dump(by_alias=True)


@router.post("", status_code=201, summary="Register a new capability")
async def create_capability(body: CapabilityCreateRequest, request: Request):
    loader = request.app.state.loader
    registry = request.app.state.registry
    persistence = request.app.state.persistence

    if body.yaml_content:
        cap = loader.parse_yaml_string(body.yaml_content, kind="Capability")
    elif body.json_content:
        from src.models.capability import Capability
        try:
            cap = Capability.model_validate(body.json_content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid capability: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide yaml_content or json_content")

    if cap is None:
        raise HTTPException(status_code=400, detail="Failed to parse capability YAML")

    # Validate dependencies exist
    for dep_name in cap.spec.depends_on:
        if registry.get_capability(dep_name) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Dependency not found: {dep_name}. Register it first.",
            )

    registry.upsert_capability(cap)

    if persistence:
        await persistence.save_extension(cap, "capabilities")

    return cap.model_dump(by_alias=True)


@router.put("/{name}", summary="Update an existing capability")
async def update_capability(name: str, body: CapabilityCreateRequest, request: Request):
    registry = request.app.state.registry
    loader = request.app.state.loader
    persistence = request.app.state.persistence

    existing = registry.get_capability(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Capability not found: {name}")

    if body.yaml_content:
        cap = loader.parse_yaml_string(body.yaml_content, kind="Capability")
    elif body.json_content:
        from src.models.capability import Capability
        try:
            cap = Capability.model_validate(body.json_content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid capability: {e}")
    else:
        raise HTTPException(status_code=400, detail="Provide yaml_content or json_content")

    if cap is None:
        raise HTTPException(status_code=400, detail="Failed to parse capability")

    if cap.name != name:
        raise HTTPException(status_code=400, detail=f"Name mismatch: URL has '{name}', body has '{cap.name}'")

    registry.upsert_capability(cap)

    if persistence:
        await persistence.save_extension(cap, "capabilities")

    return cap.model_dump(by_alias=True)


@router.delete("/{name}", summary="Delete a capability")
async def delete_capability(name: str, request: Request):
    registry = request.app.state.registry
    persistence = request.app.state.persistence

    # Check if any persona depends on this capability
    dependents = registry.find_personas_by_capability(name)
    if dependents:
        dependent_names = [p.name for p in dependents]
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: capability is used by personas: {dependent_names}",
        )

    deleted = registry.delete_capability(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Capability not found: {name}")

    if persistence:
        await persistence.delete_extension(name, "capabilities")

    return {"deleted": name}
