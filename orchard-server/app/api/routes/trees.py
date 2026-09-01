"""HTTP surface for trees."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from ...dependencies import get_source_service, get_tree_service
from ...schemas.source import SourceRead, TreeSourcesUpdate
from ...schemas.tree import TreeCreate, TreeRead, TreeUpdate
from ...services.source_service import SourceService
from ...services.tree_service import TreeService

router = APIRouter(prefix="/trees", tags=["trees"])


@router.get("", response_model=list[TreeRead])
async def list_trees(
    species: str | None = Query(default=None),
    zone_id: int | None = Query(default=None),
    service: TreeService = Depends(get_tree_service),
):
    return await service.list_trees(species=species, zone_id=zone_id)


@router.get("/{tree_id}", response_model=TreeRead)
async def get_tree(tree_id: int, service: TreeService = Depends(get_tree_service)):
    return await service.get_tree(tree_id)


@router.post("", response_model=TreeRead, status_code=status.HTTP_201_CREATED)
async def create_tree(
    payload: TreeCreate, service: TreeService = Depends(get_tree_service)
):
    return await service.create_tree(payload)


@router.patch("/{tree_id}", response_model=TreeRead)
async def update_tree(
    tree_id: int,
    payload: TreeUpdate,
    service: TreeService = Depends(get_tree_service),
):
    return await service.update_tree(tree_id, payload)


@router.delete(
    "/{tree_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_tree(tree_id: int, service: TreeService = Depends(get_tree_service)):
    await service.delete_tree(tree_id)


# -- linked knowledge-base sources ---------------------------------

@router.get("/{tree_id}/sources", response_model=list[SourceRead])
async def list_tree_sources(
    tree_id: int, sources: SourceService = Depends(get_source_service)
):
    return await sources.sources_for_tree(tree_id)


@router.put("/{tree_id}/sources", response_model=list[SourceRead])
async def set_tree_sources(
    tree_id: int,
    payload: TreeSourcesUpdate,
    sources: SourceService = Depends(get_source_service),
):
    return await sources.set_tree_sources(tree_id, payload.source_ids)
