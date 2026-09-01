"""HTTP surface for knowledge-base sources.

`POST /sources` takes multipart/form-data: a `name` plus EITHER a `text`
field OR an uploaded `file` (PDF / MD / TXT).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from ...dependencies import get_source_service
from ...schemas.source import SourceDetail, SourceRead, SourceRename
from ...services.source_service import SourceService

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
async def list_sources(service: SourceService = Depends(get_source_service)):
    return await service.list_sources()


@router.get("/{source_id}", response_model=SourceDetail)
async def get_source(
    source_id: int, service: SourceService = Depends(get_source_service)
):
    return await service.get_source(source_id)


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    name: str = Form(..., min_length=1),
    text: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    service: SourceService = Depends(get_source_service),
):
    if file is not None and (file.filename or file.size):
        data = await file.read()
        return await service.ingest_file(name, file.filename or "upload", data)
    if text and text.strip():
        return await service.ingest_text(name, text)
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "provide either a non-empty `text` field or a `file` upload",
    )


@router.patch("/{source_id}", response_model=SourceRead)
async def rename_source(
    source_id: int,
    payload: SourceRename,
    service: SourceService = Depends(get_source_service),
):
    return await service.rename_source(source_id, payload.name)


@router.delete(
    "/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_source(
    source_id: int, service: SourceService = Depends(get_source_service)
):
    await service.delete_source(source_id)
