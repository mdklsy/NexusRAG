"""LLM / Embedding 统一出口（OpenAI 兼容协议 + Ollama）。

业务层只 import 本模块的 get_llm_client / get_embedding_client，
不感知具体厂商。
"""

from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from app.core.config import get_settings


class LLMClient:
    def __init__(self, api_base: str, api_key: str, model: str):
        self.model = model
        self._client = AsyncOpenAI(base_url=api_base, api_key=api_key or "none")

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> tuple[str, dict]:
        """返回 (内容, usage)。usage 缺失时为空 dict。"""
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content or ""
        usage = {}
        if resp.usage:
            usage = {
                "tokens_in": resp.usage.prompt_tokens or 0,
                "tokens_out": resp.usage.completion_tokens or 0,
            }
        return content, usage

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[tuple[str, dict | None]]:
        """产出 (delta_text, None)；结束时产出 ("", usage)。"""
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        usage = None
        async for event in stream:
            if event.usage:
                usage = {
                    "tokens_in": event.usage.prompt_tokens or 0,
                    "tokens_out": event.usage.completion_tokens or 0,
                }
            if event.choices:
                delta = event.choices[0].delta
                if delta and delta.content:
                    yield delta.content, None
        yield "", usage

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> tuple[str, list[dict] | None]:
        """带 function calling 的非流式调用。

        返回 (content, tool_calls, usage)；tool_calls 为 None 表示无需调用工具。
        tool_calls 元素：{"id", "name", "arguments"(json 字符串)}。
        """
        kwargs: dict = {}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        choice = resp.choices[0]
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                }
                for tc in choice.message.tool_calls
            ]
        usage = {}
        if resp.usage:
            usage = {
                "tokens_in": resp.usage.prompt_tokens or 0,
                "tokens_out": resp.usage.completion_tokens or 0,
            }
        return choice.message.content or "", tool_calls, usage

    async def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """要求模型仅输出 JSON 文本（兼容不支持 json_mode 的端点）。"""
        messages = list(messages)
        messages[-1] = {
            **messages[-1],
            "content": messages[-1]["content"]
            + "\n\nOnly output valid JSON, no markdown fences, no explanation.",
        }
        content, _ = await self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return content


class EmbeddingClient:
    def __init__(self, api_base: str, api_key: str, model: str):
        self.model = model
        self._client = AsyncOpenAI(base_url=api_base, api_key=api_key or "none")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self._client.embeddings.create(
            model=self.model, input=texts, encoding_format="float"
        )
        return [item.embedding for item in resp.data]


def get_llm_client(app_llm_config: dict | None = None) -> LLMClient:
    """app_llm_config 可覆盖 model / api_base / api_key（应用级凭证优先于全局）。

    全局值 = 「设置」页的页面配置（system_settings 表）> .env。
    llm_config 中的 api_key_enc 为 AES 加密密文（由 API 层写入时加密）。
    """
    from app.core.runtime_settings import get_global

    g = get_global("llm")
    cfg = app_llm_config or {}
    model = cfg.get("model") or g["model"]

    api_base = cfg.get("api_base") or ""
    api_key = ""
    if cfg.get("api_key_enc"):
        from app.core.crypto import decrypt_secret

        try:
            api_key = decrypt_secret(cfg["api_key_enc"])
        except Exception:  # noqa: BLE001 解密失败回退全局
            api_key = ""
    if not api_base:
        api_base = g["api_base"]
    if not api_key:
        api_key = g["api_key"]
    return LLMClient(api_base, api_key, model)


def get_embedding_client() -> EmbeddingClient:
    from app.core.runtime_settings import get_global

    g = get_global("embedding")
    return EmbeddingClient(g["api_base"], g["api_key"], g["model"])
