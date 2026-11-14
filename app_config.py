"""Central configuration for Northstar HR Policy & Operations Agentic RAG + MCP."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import random
from typing import Literal

import numpy as np
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API & Models
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    llm_provider: Literal["auto", "gemini", "mock"] = Field(
        default="auto", validation_alias="LLM_PROVIDER"
    )
    gemini_model: str = Field(
        default="gemini-3.5-flash-lite", validation_alias="GEMINI_MODEL"
    )
    embedding_provider: Literal["auto", "gemini", "hash"] = Field(
        default="auto", validation_alias="EMBEDDING_PROVIDER"
    )
    gemini_embedding_model: str = Field(
        default="gemini-embedding-001", validation_alias="GEMINI_EMBEDDING_MODEL"
    )
    embedding_dim: int = Field(default=768, validation_alias="EMBEDDING_DIM")

    # MCP Transport
    mcp_transport: Literal["stdio", "streamable-http"] = Field(
        default="stdio", validation_alias="MCP_TRANSPORT"
    )
    mcp_server_url: str = Field(
        default="http://127.0.0.1:8001/mcp", validation_alias="MCP_SERVER_URL"
    )

    # RAG & Safety Parameters
    rag_top_k: int = Field(default=5, validation_alias="RAG_TOP_K")
    rag_min_rrf_score: float = Field(
        default=0.008, validation_alias="RAG_MIN_RRF_SCORE"
    )
    chunk_size_words: int = Field(default=350, validation_alias="CHUNK_SIZE_WORDS")
    chunk_overlap_words: int = Field(
        default=60, validation_alias="CHUNK_OVERLAP_WORDS"
    )
    random_seed: int = Field(default=42, validation_alias="RANDOM_SEED")
    max_agent_steps: int = Field(default=8, validation_alias="MAX_AGENT_STEPS")

    # Runtime / Paths
    app_host: str = Field(default="0.0.0.0", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    policies_dir: Path = PROJECT_ROOT / "policies"
    mock_data_dir: Path = PROJECT_ROOT / "mock_data"
    rag_index_dir: Path = PROJECT_ROOT / "data" / "rag_index"
    eval_dir: Path = PROJECT_ROOT / "evaluation"

    @property
    def has_valid_gemini_key(self) -> bool:
        """Return True when GEMINI_API_KEY is configured with a non-placeholder value."""
        key = (self.gemini_api_key or "").strip()
        return bool(key) and key != "your_gemini_api_key_here"

    @property
    def effective_llm_provider(self) -> Literal["gemini", "mock"]:
        """Resolve `auto` LLM provider based on GEMINI_API_KEY availability."""
        if self.llm_provider == "auto":
            return "gemini" if self.has_valid_gemini_key else "mock"
        return self.llm_provider

    @property
    def effective_embedding_provider(self) -> Literal["gemini", "hash"]:
        """Resolve `auto` embedding provider based on GEMINI_API_KEY availability."""
        if self.embedding_provider == "auto":
            return "gemini" if self.has_valid_gemini_key else "hash"
        return self.embedding_provider


def apply_determinism(seed: int = 42) -> None:
    """Seed Python and NumPy PRNGs for deterministic execution."""
    random.seed(seed)
    np.random.seed(seed)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance and seed PRNGs."""
    settings = Settings()
    apply_determinism(settings.random_seed)
    return settings
