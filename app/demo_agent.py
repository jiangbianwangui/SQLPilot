"""
数据分析 Agent 的一键 demo（多轮）。

    python -m app.demo_agent            # 进入多轮对话 REPL
    python -m app.demo_agent "问题"      # 单次提问

不依赖 Docker/MySQL，用 SQLite 内存库即可跑通整条 Agent 链路。
"""

from __future__ import annotations

import sys

from .agents.data_agent import DataAnalysisAgent
from .core.llm import llm_chat
from .demo import build_demo_engine


def main() -> None:
    engine = build_demo_engine()
    agent = DataAnalysisAgent(engine, llm_chat=llm_chat)

    args = " ".join(sys.argv[1:]).strip()
    if args:
        reply = agent.run(args)
        print(reply.render())
        return

    print("=== SQLPilot 数据分析 Agent（多轮，输入空行或 exit 退出）===\n")
    while True:
        try:
            q = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not q:
            continue
        if q.lower() in ("exit", "quit"):
            print("再见。")
            break
        reply = agent.run(q)
        print("\n" + reply.render() + "\n")


if __name__ == "__main__":
    main()
