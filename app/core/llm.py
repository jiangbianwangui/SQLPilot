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

import os
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
