"""Exception hierarchy for nl2sql."""
from __future__ import annotations


class Nl2SqlError(Exception):
    """Base class for all nl2sql errors."""


class SafetyError(Nl2SqlError):
    """SQL rejected by the safety layer."""


class AgentError(Nl2SqlError):
    """Agent loop failure."""


class ConfigError(Nl2SqlError):
    """Configuration parsing or resolution failure."""


class LLMError(Nl2SqlError):
    """LLM provider failure."""


class DatabaseError(Nl2SqlError):
    """Database driver failure."""
