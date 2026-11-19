"""Application settings and environment configuration."""
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM Execution Mode: 'dev' (Ollama first) vs 'demo' (Groq/Gemini first)
    LLM_MODE: Literal["dev", "demo"] = "dev"

    # Endpoints & Models
    OPENAI_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "qwen3:8b"
    GROQ_API_KEY: str = ""
    GROQ_MODEL_1: str = "openai/gpt-oss-120b"
    GROQ_MODEL_2: str = "openai/gpt-oss-20b"
    GEMINI_API_KEY: str = ""
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    GEMINI_MODEL: str = "gemini-3.8-flash"

    # Database
    DATABASE_PATH: str = "coastal_water_network.sqlite"

    # Timeouts & Retries
    REQUEST_TIMEOUT: int = 45
    MAX_RETRIES: int = 1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
