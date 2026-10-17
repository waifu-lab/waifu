from .adapter import BaseGatewayAdapter
from .command import CommandArgument, CommandCatalog, CommandDefinition, CommandHandler
from .gateway import GatewayProtocol
from .hook import BaseHook, HookContext
from .keys import Feature, RequestMeta, SessionMeta
from .mcp import BaseMCPAdapter
from .msg import MessageParts
from .output import (
    InlineTag,
    InlineTagTransformer,
    OutputTransformer,
    SpanMarkerTransformer,
    SpanPiece,
    SpanSplitter,
    StreamObserver,
    StreamTransform,
)
from .plugin import BasePlugin, PluginContext
from .prompt import SystemPromptLayers
from .services import (
    ConversationInfo,
    ConversationService,
    ServiceProvider,
    SessionService,
    StoredMessage,
    SynthesisResultProtocol,
    VoiceServiceProtocol,
)
from .session import BaseSession
from .tool import FunctionTool, ToolLike, tool
from .trace import BaseExecutionTrace
from .types import (
    AssistantMessage,
    Attachment,
    BaseMessage,
    ContentPart,
    ConversationMode,
    Event,
    GenericMessage,
    IncomingRequest,
    LLMMessage,
    MessageContent,
    OutgoingResponse,
    ReplyFn,
    Sender,
    SystemMessage,
    ToolCall,
    ToolCallFunction,
    ToolMessage,
    UserMessage,
)

__all__ = [
    "MessageParts",
    # message types
    "BaseMessage",
    "UserMessage",
    "AssistantMessage",
    "ToolMessage",
    "SystemMessage",
    "GenericMessage",
    "ToolCall",
    "ToolCallFunction",
    "LLMMessage",
    "ContentPart",
    "MessageContent",
    # types
    "IncomingRequest",
    "OutgoingResponse",
    "Attachment",
    "ConversationMode",
    "Sender",
    "Event",
    "ReplyFn",
    # well-known keys
    "Feature",
    "RequestMeta",
    "SessionMeta",
    # ABCs / Protocols
    "BaseGatewayAdapter",
    "GatewayProtocol",
    "BaseHook",
    "HookContext",
    "SystemPromptLayers",
    "OutputTransformer",
    "StreamTransform",
    "StreamObserver",
    "InlineTag",
    "InlineTagTransformer",
    "SpanMarkerTransformer",
    "SpanPiece",
    "SpanSplitter",
    "BaseSession",
    "BaseExecutionTrace",
    "BaseMCPAdapter",
    "BasePlugin",
    "PluginContext",
    # commands
    "CommandArgument",
    "CommandDefinition",
    "CommandHandler",
    "CommandCatalog",
    # tools
    "ToolLike",
    "FunctionTool",
    "tool",
    # service protocols
    "ConversationService",
    "ConversationInfo",
    "StoredMessage",
    "SessionService",
    "ServiceProvider",
    "VoiceServiceProtocol",
    "SynthesisResultProtocol",
]
