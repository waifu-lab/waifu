import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Set

from waifu_types import BaseGatewayAdapter, GatewayProtocol, ServiceProvider

if TYPE_CHECKING:
    from fastapi.websockets import WebSocket

    from waifu.node.manager import NodeManager

from waifu.logger import logger

PROTOCOL_VERSION = "1"

# tool_executor: (tool_name, params) -> str
ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[str]]


class NodeNotConnectedError(RuntimeError):
    """waifu-node 尚未連線"""


class SkillSyncError(RuntimeError):
    """skill 同步失敗"""

    def __init__(self, skill_id: str, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.skill_id = skill_id
        self.code = code


@dataclass
class NodeSession:
    """
    單一 waifu-node 連線的狀態與操作介面。

    由 WaifuNodeAdapter.handle() 建立，斷線後自動從 adapter 的 _sessions 移除。
    外部透過 adapter.get_node(node_id) 或 adapter.nodes 取得 session 後再呼叫
    invoke() / sync_skill()。

    tool 命名規則（由呼叫方 plugin 負責）：
      - 只有一台 node：沿用原始名稱（exec）
      - 多台 node：加後綴（exec@home-pc）
    """

    node_id: str
    session_id: str
    platform: str
    display_name: Optional[str]
    skills_dir: Optional[str]
    installed_skills: List[Dict[str, Any]]
    caps: Set[str]
    tools: List[Dict[str, Any]]  # node_hello 帶入的原始 tool schema

    _ws: "WebSocket" = field(repr=False)
    _invoke_timeout: float = field(repr=False)
    _ping_interval: int = field(repr=False)
    _tool_executor: Optional[ToolExecutor] = field(default=None, repr=False)

    # request_id → Future  (node_invoke)
    _pending: Dict[str, "asyncio.Future[Dict[str, Any]]"] = field(default_factory=dict, repr=False)
    # skill_id → Future  (node_skill_sync)
    _skill_pending: Dict[str, "asyncio.Future[Dict[str, Any]]"] = field(default_factory=dict, repr=False)
    _ping_task: Optional[asyncio.Task] = field(default=None, repr=False)

    async def invoke(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        呼叫此 node 的能力，等待結果後回傳 data dict。

        Raises:
            TimeoutError: node 未在 invoke_timeout 內回應
            RuntimeError: node 回傳 ok=false
        """
        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._pending[request_id] = fut

        try:
            await self._ws.send_json(
                {
                    "type": "node_invoke",
                    "request_id": request_id,
                    "action": action,
                    "params": params,
                }
            )
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=self._invoke_timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"node {self.node_id!r} did not respond to {action!r} within {self._invoke_timeout}s")
        finally:
            self._pending.pop(request_id, None)

        if not result.get("ok", False):
            err = result.get("error", {})
            raise RuntimeError(f"[{err.get('code', 'ERROR')}] {err.get('message', 'unknown error')}")

        return result.get("data", {})

    async def sync_skill(
        self,
        skill_id: str,
        version: str,
        base_url: str,
        files: List[Dict[str, Any]],
        timeout_s: float = 120.0,
    ) -> None:
        """
        要求此 node 同步 skill 檔案。

        Args:
            skill_id: skill 識別碼
            version:  skill 版本
            base_url: 後端 HTTP 基底 URL，node 從此下載檔案
            files:    [{"path": ..., "sha256": ..., "size": ...}]
                      只傳 scripts/ assets/ data/ 下的檔案；
                      SKILL.md 留在後端，不納入此清單。
                      清單為空表示該 skill 無需同步，直接回傳。

        Raises:
            TimeoutError: node 未在 timeout_s 內完成同步
            SkillSyncError: node 回報同步失敗
        """
        if not files:
            return

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._skill_pending[skill_id] = fut

        try:
            await self._ws.send_json(
                {
                    "type": "node_skill_sync",
                    "skill_id": skill_id,
                    "version": version,
                    "base_url": base_url,
                    "files": files,
                }
            )
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout_s)
        except asyncio.TimeoutError:
            raise TimeoutError(f"node {self.node_id!r} did not complete skill sync {skill_id!r} within {timeout_s}s")
        finally:
            self._skill_pending.pop(skill_id, None)

        if result.get("type") == "node_skill_sync_error":
            raise SkillSyncError(
                skill_id=skill_id,
                code=result.get("code", "UNKNOWN"),
                message=result.get("message", "unknown error"),
            )

    def dispatch(self, msg: Dict[str, Any]) -> bool:
        """處理單一訊息，回傳 False 表示應結束迴圈。"""
        msg_type = msg.get("type")

        if msg_type == "node_result":
            request_id = msg.get("request_id")
            if isinstance(request_id, str):
                fut = self._pending.get(request_id)
                if fut and not fut.done():
                    fut.set_result(msg)

        elif msg_type in ("node_skill_ready", "node_skill_sync_error"):
            fut = self._skill_pending.get(msg.get("skill_id", ""))
            if fut and not fut.done():
                fut.set_result(msg)

        elif msg_type == "node_tool_call":
            asyncio.create_task(self._handle_tool_call(msg))

        elif msg_type == "node_bye":
            logger.info("node {}: node_bye reason={}", self.node_id, msg.get("reason"))
            return False

        elif msg_type != "node_pong":
            logger.debug("node {}: unknown message type={}", self.node_id, msg_type)

        return True

    async def _handle_tool_call(self, msg: Dict[str, Any]) -> None:
        request_id = msg.get("request_id", str(uuid.uuid4()))
        tool_name = msg.get("tool", "")
        params = msg.get("params", {})

        if self._tool_executor is None:
            await self._ws.send_json(
                {
                    "type": "node_tool_result",
                    "request_id": request_id,
                    "ok": False,
                    "error": {"code": "NOT_SUPPORTED", "message": "tool executor not configured"},
                }
            )
            return

        try:
            result = await self._tool_executor(tool_name, params)
            await self._ws.send_json(
                {
                    "type": "node_tool_result",
                    "request_id": request_id,
                    "ok": True,
                    "data": result,
                }
            )
        except Exception as e:
            await self._ws.send_json(
                {
                    "type": "node_tool_result",
                    "request_id": request_id,
                    "ok": False,
                    "error": {"code": "TOOL_ERROR", "message": str(e)},
                }
            )

    async def ping_loop(self) -> None:
        while True:
            await asyncio.sleep(self._ping_interval)
            try:
                await self._ws.send_json(
                    {
                        "type": "node_ping",
                        "ts": int(time.time() * 1000),
                    }
                )
            except Exception:
                break

    def cancel_pending(self) -> None:
        """斷線時取消所有等待中的 Future。"""
        exc = NodeNotConnectedError(f"node {self.node_id!r} disconnected")
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

        for fut in self._skill_pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._skill_pending.clear()

        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()


class WaifuNodeAdapter(BaseGatewayAdapter):
    """
    Waifu-Node Gateway Adapter

    接受一或多個 waifu-node 以 WebSocket client 身份連入 /node。
    每個 node 以 node_id 識別，存為獨立的 NodeSession。

    多 node 時 tool 命名（exec@home-pc）由呼叫方 plugin 負責

    Protocol messages（node_* 前綴）：
      node_hello / node_welcome / node_reject
      node_invoke / node_result
      node_skill_sync / node_skill_ready / node_skill_sync_error
      node_tool_call / node_tool_result
      node_ping / node_pong / node_bye
    """

    name = "waifu_node"

    def __init__(
        self,
        token: str = "",
        invoke_timeout_ms: int = 10000,
        ping_interval_s: int = 30,
        path: str = "/node",
    ) -> None:
        self._token = token
        self._invoke_timeout = invoke_timeout_ms / 1000.0
        self._ping_interval = ping_interval_s
        self._path = path

        # node_id → NodeSession
        self._sessions: Dict[str, NodeSession] = {}
        self._node_manager: Optional["NodeManager"] = None

    def set_node_manager(self, manager: "NodeManager") -> None:
        self._node_manager = manager

    def on_mount(self, services: ServiceProvider) -> None:
        from waifu.node.manager import NodeManager

        manager = services.get(NodeManager)
        if manager is not None:
            manager.wire(self)

    def routers(self) -> List[Any]:
        from waifu.router.waifu_node import make_waifu_node_router

        return [make_waifu_node_router(self, self._path)]

    @property
    def nodes(self) -> List[NodeSession]:
        """目前所有已連線的 NodeSession"""
        return list(self._sessions.values())

    def get_node(self, node_id: str) -> Optional[NodeSession]:
        """取得特定 node_id 的 NodeSession，未連線回傳 None"""
        return self._sessions.get(node_id)

    async def invoke(self, node_id: str, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        呼叫指定 node 的能力。

        Raises:
            NodeNotConnectedError: node_id 對應的 node 不存在
        """
        session = self._sessions.get(node_id)
        if session is None:
            raise NodeNotConnectedError(f"node {node_id!r} is not connected")
        return await session.invoke(action, params)

    async def sync_skill(
        self,
        node_id: str,
        skill_id: str,
        version: str,
        base_url: str,
        files: List[Dict[str, Any]],
        timeout_s: float = 120.0,
    ) -> None:
        """
        要求指定 node 同步 skill 檔案。

        Raises:
            NodeNotConnectedError: node_id 對應的 node 不存在
        """
        session = self._sessions.get(node_id)
        if session is None:
            raise NodeNotConnectedError(f"node {node_id!r} is not connected")
        await session.sync_skill(skill_id, version, base_url, files, timeout_s)

    async def start(self, core: GatewayProtocol) -> None:
        pass  # endpoint 由 routers() 掛載；非對話 channel

    async def handle(self, websocket: "WebSocket") -> None:
        await websocket.accept()

        # 等待 node_hello
        try:
            hello = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("waifu-node: timed out waiting for node_hello")
            await websocket.close(code=4000)
            return

        if hello.get("type") != "node_hello":
            logger.warning("waifu-node: expected node_hello, got {}", hello.get("type"))
            await websocket.close(code=4001)
            return

        # 驗證協議版本
        if hello.get("protocol") != PROTOCOL_VERSION:
            await websocket.send_json(
                {
                    "type": "node_reject",
                    "code": "PROTOCOL_VERSION_MISMATCH",
                    "reason": f"expected protocol={PROTOCOL_VERSION}, got {hello.get('protocol')}",
                }
            )
            await websocket.close(code=4002)
            return

        # 驗證 token
        if self._token and hello.get("token", "") != self._token:
            await websocket.send_json(
                {
                    "type": "node_reject",
                    "code": "AUTH_FAILED",
                    "reason": "invalid token",
                }
            )
            await websocket.close(code=4003)
            return

        node_id = hello.get("node_id") or str(uuid.uuid4())

        # 同一 node_id 重連：清除舊 session
        if node_id in self._sessions:
            logger.info("waifu-node: node {!r} reconnected, replacing old session", node_id)
            self._sessions[node_id].cancel_pending()
            del self._sessions[node_id]

        caps: Set[str] = set(hello.get("caps", []))
        node_tools: List[Dict[str, Any]] = hello.get("tools", [])
        session = NodeSession(
            node_id=node_id,
            session_id=str(uuid.uuid4()),
            platform=hello.get("platform", "unknown"),
            display_name=hello.get("display_name"),
            skills_dir=hello.get("skills_dir"),
            installed_skills=hello.get("installed_skills", []),
            caps=caps,
            tools=node_tools,
            _ws=websocket,
            _invoke_timeout=self._invoke_timeout,
            _ping_interval=self._ping_interval,
            _tool_executor=self._node_manager.make_tool_executor() if self._node_manager else None,
        )
        self._sessions[node_id] = session

        accepted_tool_names = [t.get("name") for t in node_tools]
        await websocket.send_json(
            {
                "type": "node_welcome",
                "session_id": session.session_id,
                "accepted_caps": list(caps),
                "accepted_tools": accepted_tool_names,
            }
        )

        logger.info(
            "waifu-node connected: node_id={} display_name={} platform={} caps=%s tools=%s skills=%s total_nodes=%d",
            node_id,
            session.display_name,
            session.platform,
            sorted(caps),
            accepted_tool_names,
            [s.get("skill_id") for s in session.installed_skills],
            len(self._sessions),
        )

        if self._node_manager is not None:
            self._node_manager.on_node_connect(session)

        session._ping_task = asyncio.create_task(session.ping_loop())

        try:
            await self._receive_loop(session, websocket)
        finally:
            self._sessions.pop(node_id, None)
            session.cancel_pending()
            if self._node_manager is not None:
                self._node_manager.on_node_disconnect(node_id)
            logger.info(
                "waifu-node disconnected: node_id={} total_nodes={}",
                node_id,
                len(self._sessions),
            )

    @staticmethod
    async def _receive_loop(session: NodeSession, websocket: "WebSocket") -> None:
        while True:
            try:
                msg = await websocket.receive_json()
            except Exception:
                break
            if not session.dispatch(msg):
                break
