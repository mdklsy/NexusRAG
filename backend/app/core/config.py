"""应用配置：环境变量统一入口。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # 基础
    env: str = "dev"
    secret_key: str = "please-change-me"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "*"

    # 存储
    database_url: str = "postgresql+asyncpg://nexusrag:nexusrag@localhost:5432/nexusrag"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # LLM（OpenAI 兼容协议）
    llm_api_base: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    ollama_base_url: str = ""  # 设置后 LLM 走本地 Ollama（自动拼 /v1）

    # Embedding（OpenAI 兼容协议）
    embedding_api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    embedding_api_key: str = ""
    embedding_model: str = "embedding-3"
    embedding_dim: int = 1024

    # Rerank API（Cohere 风格 POST /rerank：SiliconFlow / Jina / Cohere 均兼容）
    rerank_api_base: str = ""  # 空 = 未配置；如 https://api.siliconflow.cn/v1
    rerank_api_key: str = ""
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # 初始管理员
    admin_email: str = "admin@nexusrag.local"
    admin_password: str = "admin123"

    # 摄取
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 50

    # JWT
    access_token_expire_hours: int = 24

    @property
    def effective_llm_base(self) -> str:
        if self.ollama_base_url:
            base = self.ollama_base_url.rstrip("/")
            return base if base.endswith("/v1") else base + "/v1"
        return self.llm_api_base.rstrip("/")

    @property
    def effective_llm_key(self) -> str:
        return "ollama" if self.ollama_base_url else self.llm_api_key

    @property
    def effective_embedding_base(self) -> str:
        return self.embedding_api_base.rstrip("/")

    @property
    def effective_embedding_key(self) -> str:
        return self.embedding_api_key or self.effective_llm_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
