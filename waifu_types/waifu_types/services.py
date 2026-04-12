from typing import Any, List, Optional, Protocol, runtime_checkable

#FIXME: 回傳的物件應該定義正式的 Protocol

@runtime_checkable
class ConversationService(Protocol):
    """
    對話資料存取介面

    回傳的物件保證具備以下欄位：
    ```
    Conversation : .id (str)  .title (str)  .created_at  .updated_at
    Message      : .id (str)  .role (str)   .content (str, JSON-encoded parts)
    ```
    """

    def get(self, id: str) -> Optional[Any]:
        """以完整 ID 取得對話；不存在時回傳 None"""
        ...

    def create(self, title: str) -> Any:
        """建立新對話，回傳 Conversation 物件"""
        ...

    def list(self, limit: int = 20) -> List[Any]:
        """列出最近的對話（依 updated_at 降序）"""
        ...

    def search(self, query: str) -> List[Any]:
        """全文搜尋對話標題與訊息內容"""
        ...

    def get_messages(self, conversation_id: str, limit: int = 100) -> List[Any]:
        """取得訊息列表（依 created_at 升序）limit=0 表示全部"""
        ...

    def add_message(self, conversation_id: str, role: str, parts: Any) -> Any:
        """新增一條訊息，回傳 Message 物件"""
        ...


@runtime_checkable
class SessionService(Protocol):
    """
    進行中 Session 的存取介面

    Session 物件保證具備：
      .conversation_id (str)
      .history  (List[Dict])   — in-memory 對話歷史
      .metadata (Dict[str, Any])
      .touch()
      .add_message(message: Dict)
    """

    def get(self, conversation_id: str) -> Optional[Any]:
        """取得進行中的 Session；若已過期或不存在回傳 None"""
        ...

    def get_or_create(self, conversation_id: str) -> Any:
        """取得或建立 Session"""
        ...

    def delete(self, conversation_id: str) -> None:
        """刪除 Session（強制結束對話）"""
        ...


@runtime_checkable
class VoiceServiceProtocol(Protocol):
    """
    TTS / STT 存取介面，供需要語音功能的 Plugin 使用
    """

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

    async def synthesize(self, text: str) -> Any:
        """
        文字轉語音，回傳 SynthesisResult

        SynthesisResult 保證具備：
          .audio_bytes  (bytes)
          .format       (str)
          .duration_ms  (int)
          .lipsync_events (List[Dict])
        """
        ...
