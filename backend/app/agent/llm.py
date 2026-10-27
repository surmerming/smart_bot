"""LLM 客户端：DeepSeek API（OpenAI 兼容）流式/非流式调用。

- 有 API Key 时走真实 DeepSeek（deepseek-chat / V3 非推理，TTFT < 1s）
- 无 Key 或 LLM_MODE=mock 时走 MockLLM（规则化输出，可离线跑通全链路）
"""
from __future__ import annotations

import logging
import re
from typing import AsyncGenerator, Optional

from app.config import settings

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None


class MockLLM:
    """离线 Mock：按任务类型返回规则化输出，用于开发与自动化测试。"""

    _QUERY_RE = re.compile(
        r"(?:用户消息|用户问题)[：:]\s*(.+?)(?:\n(?:情绪等级|分类|结果|语义关系)[：:]|$)", re.S
    )

    async def stream_chat(self, messages: list[dict], **kwargs) -> AsyncGenerator[str, None]:
        text = self._answer(messages)
        # 模拟流式：按 6 字切块
        for i in range(0, len(text), 6):
            yield text[i:i + 6]

    async def complete(self, messages: list[dict], **kwargs) -> str:
        return self._answer(messages)

    @staticmethod
    def _task_hint(messages: list[dict]) -> str:
        return "\n".join(m.get("content", "") for m in messages if m.get("role") in ("system", "user"))

    @classmethod
    def _real_query(cls, messages: list[dict]) -> str:
        """从「用户消息/用户问题：」标记后提取真实用户输入，避免把 Prompt 模板当查询。"""
        for m in reversed(messages):
            if m.get("role") != "user":
                continue
            content = m.get("content", "")
            match = cls._QUERY_RE.search(content)
            if match:
                return match.group(1).strip()
            return content.strip()
        return ""

    def _answer(self, messages: list[dict]) -> str:
        hint = self._task_hint(messages)
        user = self._real_query(messages)
        if "情绪等级" in hint:
            # 简单规则模拟情绪分级（真实场景由 DeepSeek 判断）
            if any(k in user for k in ("投诉", "举报", "曝光", "12315", "315", "报警", "诈骗", "起诉")):
                return "LEVEL_3"
            if any(k in user for k in ("破", "坏", "再也不买", "气死", "太慢")):
                return "LEVEL_2"
            return "LEVEL_0"
        if "改写后" in hint and "标准问法" in hint:
            # Query Rewrite：Mock 不实质改写，原样返回（保证离线检索行为稳定）
            return user
        if "user_intent" in hint and "只输出 JSON" in hint:
            # L3 结构化事实提取：Mock 返回稳定 JSON
            import json as _json

            return _json.dumps(
                {"user_intent": user[:24], "order_info": "无", "product": "无", "request": "无"},
                ensure_ascii=False,
            )
        if "不超过 100 字" in hint and "摘要" in hint:
            # L2 摘要压缩：Mock 简单截断模拟
            return (user[:50] + "…") if len(user) > 50 else user
        if "IN_KNOWLEDGE" in hint and "OUT_OF_SCOPE" in hint:
            return "IN_KNOWLEDGE"
        if "只输出 true 或 false" in hint:
            # 明显超纲问题 Mock 判 false，其余 true
            if any(k in user for k in ("老板是谁", "天气", "写首诗", "诗", "地址在哪里", "1加1", "吃了没")):
                return "false"
            return "true"
        if "ENTAILMENT" in hint and "CONTRADICTION" in hint:
            return "ENTAILMENT"
        if "幽默润色" in hint or "只能调整语气" in hint:
            return f"{user}～放心冲！"
        # 兜底：模拟知识库事实版回答
        ctx = user.strip()
        return f"（Mock）知识库检索结果：{ctx[:40]}"


class DeepSeekClient:
    """真实 DeepSeek 客户端（OpenAI 兼容）。"""

    def __init__(self) -> None:
        if AsyncOpenAI is None:  # pragma: no cover
            raise RuntimeError("openai 库未安装，请先 pip install -r requirements.txt")
        self._client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=30.0,
            max_retries=2,
        )
        self._model = settings.DEEPSEEK_MODEL

    async def stream_chat(self, messages: list[dict], temperature: float = 0.7) -> AsyncGenerator[str, None]:
        """SSE 流式：逐 token 产出。"""
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def complete(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 50) -> str:
        """非流式：短输出任务（情绪/意图/布尔判断等），延迟优先。"""
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        return (resp.choices[0].message.content or "").strip()


class LLM:
    """统一入口：根据配置自动切换 真实 / Mock。"""

    def __init__(self) -> None:
        self._real: Optional[DeepSeekClient] = None
        self._mock = MockLLM()
        if settings.use_real_llm:
            try:
                self._real = DeepSeekClient()
                logger.info("LLM 模式：真实 DeepSeek API (%s)", settings.DEEPSEEK_MODEL)
            except Exception as exc:  # pragma: no cover
                logger.warning("DeepSeek 客户端初始化失败，降级 Mock：%s", exc)
                self._real = None

    @property
    def is_mock(self) -> bool:
        return self._real is None

    async def stream_chat(self, messages: list[dict], temperature: float = 0.7) -> AsyncGenerator[str, None]:
        if self._real:
            async for token in self._real.stream_chat(messages, temperature=temperature):
                yield token
        else:
            async for token in self._mock.stream_chat(messages, temperature=temperature):
                yield token

    async def complete(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 50) -> str:
        if self._real:
            return await self._real.complete(messages, temperature=temperature, max_tokens=max_tokens)
        return await self._mock.complete(messages, temperature=temperature, max_tokens=max_tokens)


llm = LLM()
