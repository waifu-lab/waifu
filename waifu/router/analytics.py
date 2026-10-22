from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from waifu.store.repositories.analytics import TokenAnalyticsRepository


def make_analytics_router(repo: TokenAnalyticsRepository) -> APIRouter:
    router = APIRouter(prefix="/analytics", tags=["analytics"])

    @router.get("/tokens/today")
    async def get_today_tokens(
        conversation_id: Optional[str] = Query(None, description="指定對話；不傳則回傳全域彙總"),
    ) -> Dict[str, Any]:
        return repo.get_today(conversation_id)

    @router.get("/tokens/date/{target_date}")
    async def get_date_tokens(
        target_date: str,
        conversation_id: Optional[str] = Query(None),
    ) -> Dict[str, Any]:
        try:
            d = date.fromisoformat(target_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="日期格式應為 YYYY-MM-DD") from exc
        return repo.get_by_date(d, conversation_id)

    @router.get("/tokens/range")
    async def get_range_tokens(
        start: str = Query(..., description="開始日期 YYYY-MM-DD"),
        end: str = Query(..., description="結束日期 YYYY-MM-DD"),
        conversation_id: Optional[str] = Query(None),
    ) -> List[Dict[str, Any]]:
        try:
            s = date.fromisoformat(start)
            e = date.fromisoformat(end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="日期格式應為 YYYY-MM-DD") from exc
        if s > e:
            raise HTTPException(status_code=422, detail="start 不能晚於 end")
        return repo.get_range(s, e, conversation_id)

    @router.get("/tokens/conversation/{conversation_id}")
    async def get_conversation_tokens(conversation_id: str) -> Dict[str, Any]:
        return repo.get_conversation_total(conversation_id)

    return router
