"""Config file + env var + flag resolution for the CLI."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from ..exceptions import ConfigError


@dataclass
class Config:
    profile: Optional[str] = None
    db_url: Optional[str] = None
    llm_provider: str = "anthropic"
    llm_model: str = "claude-opus-4-7"
    hints_path: Optional[str] = None
    feedback_path: Optional[str] = None
    knowledge_store: dict[str, str] = field(default_factory=dict)
    max_iterations: int = 10
    max_rows_returned: int = 200
    query_timeout_s: float = 10.0
    require_select_only: bool = True
    deny_system_tables: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    def build_db(self):
        from ..db import SqliteDatabase

        if not self.db_url:
            raise ConfigError(
                "No database configured. Set NL2SQL_DB_URL, --db, or db: in your "
                "profile."
            )
        url = self.db_url
        if url.startswith("sqlite:///"):
            return SqliteDatabase(url[len("sqlite:///"):])
        if url.startswith("sqlite:"):
            return SqliteDatabase(url[len("sqlite:"):])
        if url.endswith(".db") or url.endswith(".sqlite") or url.endswith(".sqlite3"):
            return SqliteDatabase(url)
        if url.startswith("postgres://") or url.startswith("postgresql://"):
            from ..db.postgres import PostgresDatabase
            return PostgresDatabase(url)
        raise ConfigError(f"Unrecognised db URL: {url}")

    def build_llm(self):
        if self.llm_provider == "anthropic":
            from ..llm.anthropic import AnthropicClient
            return AnthropicClient(model=self.llm_model)
        if self.llm_provider == "openai":
            from ..llm.openai import OpenAIClient
            return OpenAIClient(model=self.llm_model)
        if self.llm_provider == "mock":
            from ..llm.base import MockLLMClient
            return MockLLMClient(responses=[])
        raise ConfigError(f"Unknown LLM provider: {self.llm_provider}")

    def build_hints(self):
        if not self.hints_path:
            return None
        from ..hints import DomainHints
        return DomainHints.from_yaml(self.hints_path)

    def build_feedback(self):
        if not self.feedback_path:
            return None
        from ..feedback import JsonFeedbackStore
        return JsonFeedbackStore(self.feedback_path)

    def build_knowledge(self):
        if not self.knowledge_store:
            return None
        from ..hints import DictKnowledgeStore
        return DictKnowledgeStore(self.knowledge_store)


_USER_CONFIG_DIRS = [
    Path.home() / ".config" / "nl2sql" / "config.yaml",
    Path.home() / ".nl2sql.yaml",
]


def _project_config_path(start: Optional[Path] = None) -> Optional[Path]:
    cwd = start or Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".nl2sql.yaml"
        if candidate.exists():
            return candidate
    return None


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error in {path}: {e}") from e


def _select_profile(data: dict, profile_name: Optional[str]) -> tuple[Optional[str], dict]:
    profiles = data.get("profiles", {}) or {}
    name = profile_name or data.get("default_profile")
    if name and name in profiles:
        return name, profiles[name]
    if not name and not profiles:
        return None, data  # flat config
    if name and name not in profiles:
        raise ConfigError(f"Profile '{name}' not found in config.")
    return None, data


def _merge(*dicts: dict) -> dict:
    out: dict = {}
    for d in dicts:
        if not d:
            continue
        for k, v in d.items():
            if (
                k in out
                and isinstance(out[k], dict)
                and isinstance(v, dict)
            ):
                out[k] = _merge(out[k], v)
            else:
                out[k] = v
    return out


def load_config(
    *,
    profile: Optional[str] = None,
    db_override: Optional[str] = None,
    model_override: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Config:
    """Resolve the active config from layered sources."""
    layers: list[dict] = []
    for p in _USER_CONFIG_DIRS:
        if p.exists():
            layers.append(_read_yaml(p))
            break
    project = (
        Path(config_path) if config_path else _project_config_path()
    )
    if project and project.exists():
        layers.append(_read_yaml(project))

    merged = _merge(*layers)
    profile_name, prof = _select_profile(merged, profile)
    cfg = _merge(merged, prof) if prof is not merged else merged
    # Top-level keys: db, llm: {provider, model}, hints, feedback, knowledge_store,
    # max_iterations, etc.
    raw = cfg

    llm_section = cfg.get("llm", {}) if isinstance(cfg.get("llm"), dict) else {}
    db_url = (
        db_override
        or os.environ.get("NL2SQL_DB_URL")
        or cfg.get("db")
    )
    llm_provider = (
        llm_section.get("provider")
        or cfg.get("llm_provider")
        or "anthropic"
    )
    llm_model = (
        model_override
        or os.environ.get("NL2SQL_LLM_MODEL")
        or llm_section.get("model")
        or cfg.get("llm_model")
        or ("claude-opus-4-7" if llm_provider == "anthropic" else "gpt-4o-mini")
    )

    return Config(
        profile=profile_name,
        db_url=db_url,
        llm_provider=llm_provider,
        llm_model=llm_model,
        hints_path=cfg.get("hints"),
        feedback_path=cfg.get("feedback"),
        knowledge_store=dict(cfg.get("knowledge_store", {}) or {}),
        max_iterations=int(cfg.get("max_iterations", 10)),
        max_rows_returned=int(cfg.get("max_rows_returned", 200)),
        query_timeout_s=float(cfg.get("query_timeout_s", 10.0)),
        require_select_only=bool(cfg.get("require_select_only", True)),
        deny_system_tables=bool(cfg.get("deny_system_tables", True)),
        raw=raw,
    )
