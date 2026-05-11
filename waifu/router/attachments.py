from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response

from waifu.store.conversation import ConversationStore


def make_attachments_router(
    conversation_store: ConversationStore,
    attachments_dir: Path,
) -> APIRouter:
    router = APIRouter(prefix="/attachments", tags=["attachments"])

    @router.get("/{attachment_id}")
    async def get_attachment(attachment_id: str) -> Response:
        att = conversation_store.get_attachment(attachment_id)
        if att is None:
            raise HTTPException(status_code=404, detail="Attachment not found")

        storage_path = cast("str | None", att.storage_path)
        if storage_path:
            full = attachments_dir / storage_path
            if not full.is_file():
                raise HTTPException(status_code=404, detail="Attachment file missing")
            return FileResponse(
                path=str(full),
                media_type=cast(str, att.content_type),
                filename=cast(str, att.filename),
            )

        url = cast("str | None", att.url)
        if url:
            return RedirectResponse(url=url, status_code=302)

        raise HTTPException(status_code=404, detail="Attachment has no content")

    return router
