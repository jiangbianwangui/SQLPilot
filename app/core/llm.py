"""
LLM 适配器 —— DeepSeek（OpenAI 兼容接口）。

为什么要单独一层：
    RetryLoop 只认一个签名 llm_generate(prompt) -> str。
    把「HTTP 调用 / 读配置 / 错误处理」全关在这个文件里，
    上层循环就完全不依赖具体厂商，换 Ollama / 通义只改环境变量。

配置从项目根目录的 .env 读（也可直接用环境变量）：
    LLM_API_KEY=sk-...
    LLM_BASE_URL=https://api.deepseek.com
    LLM_MODEL_ID=deepseek-chat
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx


def _load_dotenv() -> None:
    """极简 .env 加载：不覆盖已存在的环境变量，也不引额外依赖。"""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


class DeepSeekLLM:
    """DeepSeek chat 模型封装。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        _load_dotenv()
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = (
            base_url or os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
        ).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL_ID", "deepseek-chat")
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        """发一次 chat 请求，返回模型文本。"""
        if not self.api_key:
            raise RuntimeError("缺少 LLM_API_KEY，请在项目根目录 .env 里配置")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,  # 查数据库要确定性，别让它发挥
        }

        response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def chat(
        self, messages: list[dict], tools: Optional[list] = None
    ) -> "ChatResponse":
        """多轮 + 工具调用接口（OpenAI 兼容）。

        用于数据分析 Agent：把历史消息和工具定义发给模型，
        模型返回纯文本（最终回答）或 tool_calls（要执行的工具）。
        """
        if not self.api_key:
            raise RuntimeError("缺少 LLM_API_KEY，请在项目根目录 .env 里配置")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        msg = response.json()["choices"][0]["message"]
        content = msg.get("content") or ""
        raw_calls = msg.get("tool_calls") or []
        tool_calls: list[ToolCall] = []
        for tc in raw_calls:
            fn = tc.get("function", {})
            args_str = fn.get("arguments", "{}") or "{}"
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args)
            )
        return ChatResponse(content=content, tool_calls=tool_calls)


_llm_singleton: Optional[DeepSeekLLM] = None


def get_llm() -> DeepSeekLLM:
    """全局单例，避免每次调用重复读配置。"""
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = DeepSeekLLM()
    return _llm_singleton


def llm_generate(prompt: str) -> str:
    """模块级函数：正好是 RetryLoop 需要的签名。"""
    return get_llm().generate(prompt)


@dataclass
class ToolCall:
    """一次工具调用（模型返回）。"""

    id: str
    name: str
    arguments: dict

    def to_openai(self) -> dict:
        """转成 OpenAI 消息格式里 assistant 的 tool_calls 项。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class ChatResponse:
    """模型一次 chat 的返回。"""

    content: str = ""
    tool_calls: list = field(default_factory=list)


def llm_chat(messages: list[dict], tools: Optional[list] = None) -> ChatResponse:
    """模块级便捷函数：正好是 DataAnalysisAgent 需要的签名。"""
    return get_llm().chat(messages, tools)
