from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, cast

from peewee import DateField, ForeignKeyField, IntegerField

from waifu.store.models import DailyTokenUsage, Message


class TokenAnalyticsRepository:
    """Token 使用量查詢。寫入端由 ConversationStore._upsert_daily_tokens 負責。"""

    def get_today(self, conversation_id: Optional[str] = None) -> Dict[str, int]:
        """今日（UTC）token 用量。conversation_id=None 代表全域彙總。"""
        return self._get_by_date(datetime.now(timezone.utc).date(), conversation_id)

    def get_by_date(self, target: date, conversation_id: Optional[str] = None) -> Dict[str, int]:
        """指定日期的 token 用量。"""
        return self._get_by_date(target, conversation_id)

    def get_range(
        self,
        start: date,
        end: date,
        conversation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """回傳日期區間內每日的用量列表。"""
        q = (
            DailyTokenUsage.select()
            .where(
                cast(DateField, DailyTokenUsage.date) >= start,
                cast(DateField, DailyTokenUsage.date) <= end,
                DailyTokenUsage.conversation_id == conversation_id,
            )
            .order_by(cast(DateField, DailyTokenUsage.date).asc())
        )

        return [
            {
                "date": str(cast(date, row.date)),
                "input_tokens": cast(int, row.input_tokens),
                "output_tokens": cast(int, row.output_tokens),
                "total_tokens": cast(int, row.total_tokens),
            }
            for row in q
        ]

    def get_conversation_total(self, conversation_id: str) -> Dict[str, int]:
        """某對話的歷史累計 token（從 Message 表聚合）。"""
        msgs = Message.select().where(
            cast(ForeignKeyField, Message.conversation) == conversation_id,
            Message.role == "assistant",
        )
        input_total = sum(cast(int, m.input_tokens) or 0 for m in msgs)
        output_total = sum(cast(int, m.output_tokens) or 0 for m in msgs)
        return {
            "input_tokens": input_total,
            "output_tokens": output_total,
            "total_tokens": input_total + output_total,
        }

    def _get_by_date(self, target: date, conversation_id: Optional[str]) -> Dict[str, int]:
        row = DailyTokenUsage.get_or_none(
            DailyTokenUsage.date == target,
            DailyTokenUsage.conversation_id == conversation_id,
        )
        if row is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        return {
            "input_tokens": cast(int, row.input_tokens),
            "output_tokens": cast(int, row.output_tokens),
            "total_tokens": cast(int, row.total_tokens),
        }
