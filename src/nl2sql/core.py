"""Public Nl2Sql class. The thin wiring layer over :mod:`nl2sql.agent`."""
from __future__ import annotations

import time
from typing import Optional, TYPE_CHECKING

from .types import Result

if TYPE_CHECKING:
    from .db.base import Database
    from .llm.base import LLMClient
    from .hints import DomainHints, KnowledgeStore
    from .feedback import FeedbackStore


class Nl2Sql:
    """Public entry point.

    Bind a ``Database`` and an ``LLMClient`` and call :meth:`ask`.
    """

    def __init__(
        self,
        db: "Database",
        llm: "LLMClient",
        *,
        hints: Optional["DomainHints"] = None,
        knowledge_store: Optional["KnowledgeStore"] = None,
        feedback: Optional["FeedbackStore"] = None,
        max_iterations: int = 10,
        max_rows_returned: int = 200,
        query_timeout_s: float = 10.0,
        require_select_only: bool = True,
        deny_system_tables: bool = True,
    ) -> None:
        self.db = db
        self.llm = llm
        self.hints = hints
        self.knowledge_store = knowledge_store
        self.feedback = feedback
        self.max_iterations = max_iterations
        self.max_rows_returned = max_rows_returned
        self.query_timeout_s = query_timeout_s
        self.require_select_only = require_select_only
        self.deny_system_tables = deny_system_tables

    def ask(self, question: str) -> Result:
        """Run the agent loop on ``question`` and return a :class:`Result`."""
        from .agent import run_agent

        start = time.monotonic()
        result = run_agent(
            question=question,
            db=self.db,
            llm=self.llm,
            hints=self.hints,
            knowledge_store=self.knowledge_store,
            feedback=self.feedback,
            max_iterations=self.max_iterations,
            max_rows_returned=self.max_rows_returned,
            query_timeout_s=self.query_timeout_s,
            require_select_only=self.require_select_only,
            deny_system_tables=self.deny_system_tables,
        )
        result.elapsed_s = time.monotonic() - start
        return result
