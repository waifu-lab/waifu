from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Type, TypeVar, Union, runtime_checkable

from pydantic import BaseModel

from waifu_types.session import BaseSession

T = TypeVar("T")


class ConversationInfo(BaseModel):
    id: str
    title: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StoredMessage(BaseModel):
    id: str
    role: str
    content: List[Dict[str, Any]]  # message parts
    created_at: Optional[datetime] = None


@runtime_checkable
class ConversationService(Protocol):
    """對話資料存取介面"""

    def get(self, id: str) -> Optional[ConversationInfo]:
        """以完整 ID 取得對話；不存在時回傳 None"""
        ...

    def create(self, title: str) -> ConversationInfo:
        """建立新對話"""
        ...

    def list(self, limit: int = 20) -> List[ConversationInfo]:
        """列出最近的對話（依 updated_at 降序）"""
        ...

    def search(self, query: str) -> List[ConversationInfo]:
        """全文搜尋對話標題與訊息內容"""
        ...

    def get_messages(self, conversation_id: str, limit: int = 100) -> List[StoredMessage]:
        """取得訊息列表（依 created_at 升序）limit=0 表示全部"""
        ...

    def add_message(
        self, conversation_id: str, role: str, parts: Union[List[Dict[str, Any]], str]
    ) -> StoredMessage:
        """新增一條訊息；parts 為字串時自動包成 text part"""
        ...


@runtime_checkable
class SessionService(Protocol):
    """進行中 Session 的存取介面"""

    def get(self, conversation_id: str) -> Optional[BaseSession]:
        """取得進行中的 Session；若已過期或不存在回傳 None"""
        ...

    def get_or_create(self, conversation_id: str) -> BaseSession:
        """取得或建立 Session"""
        ...

    def delete(self, conversation_id: str) -> None:
        """刪除 Session（強制結束對話）"""
        ...


@runtime_checkable
class SynthesisResultProtocol(Protocol):
    audio_bytes: bytes
    format: str
    lipsync_events: List[Dict[str, Any]]


@runtime_checkable
class VoiceServiceProtocol(Protocol):
    """TTS / STT 存取介面，供需要語音功能的 Plugin 使用"""

    @property
    def has_stt(self) -> bool:
        """是否已設定 STT provider"""
        ...

    @property
    def has_tts(self) -> bool:
        """是否已設定 TTS provider"""
        ...

    async def transcribe(self, audio: bytes, format: str = "webm", language: Optional[str] = None) -> str:
        """語音轉文字"""
        ...

    async def synthesize(self, text: str, need_lipsync: bool = False) -> SynthesisResultProtocol:
        """文字轉語音"""
        ...


class ServiceProvider(Protocol):
    """以型別查詢執行期服務，例如 services.get(VoiceServiceProtocol)"""

    def get(self, key: Type[T]) -> Optional[T]: ...
