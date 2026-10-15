#!/bin/bash
# SQLPilot 容器启动脚本：用 uvicorn 拉起 FastAPI 服务。
set -e

PORT="${PORT:-7860}"
exec uvicorn app.server:app --host 0.0.0.0 --port "$PORT"
