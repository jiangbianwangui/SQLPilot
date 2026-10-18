"""SQLPilot 的 Gradio 入口（魔搭 ModelScope 创空间 Gradio 类型部署）。

复用 app.server 里已经初始化好的引擎与 LLM 注入（含 USE_FAKE 兜底），
把单步 text-to-SQL 与多步数据分析 Agent 包装成两个 Tab：
  - 单步查询：自然语言 -> SQLAgent -> SQL + 执行结果 + 自然语言答案
  - 多步分析 Agent：ReAct 工具调用循环 + 会话记忆（inspect_schema/run_sql/diagnose/plot）

演示库为文件型 SQLite（/tmp/sqlpilot_demo.db），无需任何外部数据库。
"""

import gradio as gr

from app.server import _engine, _llm_generate, _llm_chat
from app.agents.sql_agent import SQLAgent
from app.agents.data_agent import DataAnalysisAgent


single_agent = SQLAgent(_engine, llm_generate=_llm_generate)


def single_fn(question: str) -> str:
    if not (question or "").strip():
        return "请输入一个自然语言问题。"
    return single_agent.ask(question).render_markdown()


def respond(message: str, history, state):
    history = history or []
    if not (message or "").strip():
        return "", history, state
    if state is None:
        state = DataAnalysisAgent(_engine, llm_chat=_llm_chat)
    reply = state.run(message)
    history.append((message, reply.render_markdown()))
    return "", history, state


with gr.Blocks(title="SQLPilot") as demo:
    gr.Markdown(
        "# SQLPilot\n"
        "自然语言查数据库 + 多步数据分析 Agent。演示库为内置文件型 SQLite，无需外部数据库。"
    )

    with gr.Tabs():
        with gr.Tab("单步查询 (text-to-SQL)"):
            gr.Markdown("输入一句自然语言，SQLPilot 自动选表、生成 SQL、执行并返回结果。")
            q = gr.Textbox(
                label="自然语言问题",
                placeholder="例如：北京客户一共花了多少钱？",
                lines=2,
            )
            gr.Examples(
                examples=[
                    "北京客户一共花了多少钱？",
                    "每个城市有多少客户？",
                    "订单金额最高的 5 笔是多少？",
                ],
                inputs=q,
                label="点一下试试",
            )
            btn1 = gr.Button("运行查询", variant="primary")
            out1 = gr.Markdown()
            btn1.click(single_fn, q, out1)

        with gr.Tab("多步分析 Agent"):
            gr.Markdown(
                "多轮对话。Agent 会自行决定调用哪些工具（看表结构 / 跑 SQL / 诊断 / 画图），"
                "并记住上下文。回复里包含「推理过程」与「回答」。"
            )
            chatbot = gr.Chatbot(label="对话（含工具调用轨迹）", height=520)
            txt = gr.Textbox(
                label="消息",
                placeholder="例如：分析各城市客户的消费总额，并画成柱状图",
            )
            state = gr.State(None)
            txt.submit(respond, [txt, chatbot, state], [txt, chatbot, state])

    gr.Markdown("--- \nSQLPilot · text-to-SQL + 多步数据分析 Agent · 自实现引擎（不依赖外部 Agent 框架）")


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
