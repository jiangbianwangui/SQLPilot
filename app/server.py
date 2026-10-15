"""SQLPilot Web 服务 —— 把 text-to-SQL 引擎 + 多步数据分析 Agent 包成 HTTP 服务。

启动：
    uvicorn app.server:app --host 0.0.0.0 --port 7860

能力：
    GET  /api/health           健康检查
    GET  /api/ask?q=...       单步 SQLAgent（选表 → 生成 → 执行 → 自修复）
    POST /api/agent           多步 DataAnalysisAgent（ReAct 工具调用 + 会话记忆）
    POST /api/reset           清空某会话记忆
    GET  /                   极简聊天前端

演示库：默认用 SQLite 文件库（自带示例 shop 数据），无需外部数据库。
大模型：读环境变量 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL_ID（ModelScope 上设为 Secret）。
        设置 SQLPILOT_FAKE_LLM=1 可无 Key 跑通闭环（演示/离线用）。
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from sqlalchemy import create_engine, text

from .demo import _DDL, _ROWS, build_demo_engine
from .agents.sql_agent import SQLAgent
from .agents.data_agent import DataAnalysisAgent
from .core.llm import ToolCall, ChatResponse, llm_chat, llm_generate

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

USE_FAKE = os.getenv("SQLPILOT_FAKE_LLM") == "1"

# ---------------------------------------------------------------------------
# 真 / 假 LLM 切换
# ---------------------------------------------------------------------------
def _fake_generate(prompt: str) -> str:
    """演示用假 LLM：从 prompt 里抠出问题关键词，返回一条固定 SELECT。"""
    q = prompt
    if "【用户问题】" in prompt:
        q = prompt.split("【用户问题】")[-1]
    ql = q.lower()
    if "客户" in q or "customer" in ql:
        return (
            "SELECT c.name, SUM(o.amount) AS total FROM customers c "
            "JOIN orders o ON o.customer_id=c.id GROUP BY c.name "
            "ORDER BY total DESC LIMIT 10"
        )
    if "产品" in q or "product" in ql:
        return "SELECT name, price, stock FROM products ORDER BY price DESC LIMIT 10"
    if "订单" in q or "order" in ql:
        return "SELECT * FROM orders ORDER BY created_at DESC LIMIT 10"
    return "SELECT * FROM products LIMIT 10"


def _fake_chat(messages: list[dict], tools=None) -> ChatResponse:
    """演示用假 LLM：按对话里已有的工具结果，走 inspect → run_sql → 回答 三步。"""
    has_inspect = any(
        m.get("role") == "tool" and m.get("name") == "inspect_schema" for m in messages
    )
    has_runsql = any(
        m.get("role") == "tool" and m.get("name") == "run_sql" for m in messages
    )
    if not has_inspect:
        return ChatResponse(
            content="", tool_calls=[ToolCall(id="t1", name="inspect_schema", arguments={})]
        )
    if not has_runsql:
        return ChatResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="t2",
                    name="run_sql",
                    arguments={
                        "sql": (
                            "SELECT c.name, SUM(o.amount) AS total FROM customers c "
                            "JOIN orders o ON o.customer_id=c.id GROUP BY c.name "
                            "ORDER BY total DESC LIMIT 10"
                        )
                    },
                )
            ],
        )
    return ChatResponse(
        content=(
            "根据查询结果，消费总额最高的是「张三」（北京，等级 3），"
            "累计消费 4078 元（订单 3999 + 79）。（演示模式：以上为模拟回答）"
        )
    )


_llm_generate = _fake_generate if USE_FAKE else llm_generate
_llm_chat = _fake_chat if USE_FAKE else llm_chat


# ---------------------------------------------------------------------------
# 引擎与会话（进程内单例；演示场景足够）
# ---------------------------------------------------------------------------
_DB_PATH = os.path.join(tempfile.gettempdir(), "sqlpilot_demo.db")
if os.path.exists(_DB_PATH):
    os.remove(_DB_PATH)
_engine = build_demo_engine(_DB_PATH)

_single_agent = SQLAgent(_engine, llm_generate=_llm_generate)
_sessions: dict[str, DataAnalysisAgent] = {}


def _get_agent(session_id: str) -> DataAnalysisAgent:
    if session_id not in _sessions:
        _sessions[session_id] = DataAnalysisAgent(_engine, llm_chat=_llm_chat)
    return _sessions[session_id]


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(title="SQLPilot API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "engine": "sqlite-file-demo", "fake_llm": USE_FAKE}


@app.get("/api/ask")
def ask(question: str = Query(..., description="用自然语言描述你想查的内容")):
    """单步 text-to-SQL：输入中文问题，返回生成的 SQL + 结果 + 重试过程。"""
    try:
        ans = _single_agent.ask(question)
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": f"LLM 未配置：{e}。请配置 LLM_API_KEY，或设 SQLPILOT_FAKE_LLM=1 演示。"},
        )
    return {
        "ok": ans.ok,
        "question": ans.question,
        "sql": ans.sql,
        "tables": ans.tables,
        "columns": ans.columns,
        "rows": ans.rows,
        "attempts": [
            {"index": a.index, "sql": a.sql, "ok": a.ok, "error": a.error}
            for a in ans.attempts
        ],
        "error": ans.error,
        "elapsed": round(ans.elapsed, 2),
    }


class AgentReq(BaseModel):
    question: str
    session_id: Optional[str] = "default"


@app.post("/api/agent")
def agent(req: AgentReq):
    """多步数据分析 Agent：工具调用 + 会话记忆 + 反思重规划。"""
    try:
        a = _get_agent(req.session_id)
        reply = a.run(req.question)
    except RuntimeError as e:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": f"LLM 未配置：{e}。请配置 LLM_API_KEY，或设 SQLPILOT_FAKE_LLM=1 演示。"},
        )
    return {
        "ok": reply.ok,
        "text": reply.text,
        "session_id": req.session_id,
        "trace": [
            {"tool": name, "args": args, "result": str(result)}
            for (name, args, result) in reply.trace
        ],
    }


class ResetReq(BaseModel):
    session_id: Optional[str] = "default"


@app.post("/api/reset")
def reset(req: ResetReq):
    _sessions.pop(req.session_id, None)
    return {"ok": True, "session_id": req.session_id}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))
