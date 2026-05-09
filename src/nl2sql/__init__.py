"""nl2sql — natural language to SQL via an agent loop."""
from .core import Nl2Sql
from .hints import DomainHints, KnowledgeStore, DictKnowledgeStore
from .feedback import FeedbackStore, JsonFeedbackStore, FeedbackEntry
from .types import (
    Result,
    AgentStep,
    TableSchema,
    ColumnSchema,
    ForeignKey,
    QueryResult,
    EvalReport,
    TokenUsage,
    ToolDef,
    ToolCall,
    LLMResponse,
    Message,
)
from .exceptions import (
    Nl2SqlError,
    SafetyError,
    AgentError,
    ConfigError,
    LLMError,
    DatabaseError,
)

__version__ = "0.1.0"

__all__ = [
    "Nl2Sql",
    "DomainHints",
    "KnowledgeStore",
    "DictKnowledgeStore",
    "FeedbackStore",
    "JsonFeedbackStore",
    "FeedbackEntry",
    "Result",
    "AgentStep",
    "TableSchema",
    "ColumnSchema",
    "ForeignKey",
    "QueryResult",
    "EvalReport",
    "TokenUsage",
    "ToolDef",
    "ToolCall",
    "LLMResponse",
    "Message",
    "Nl2SqlError",
    "SafetyError",
    "AgentError",
    "ConfigError",
    "LLMError",
    "DatabaseError",
    "__version__",
]
