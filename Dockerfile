# SQLPilot —— 自包含部署镜像（FastAPI + 文件型 SQLite 演示库，无需外部数据库）
#
# 兼容两类运行环境：
#   - 魔搭 ModelScope 创空间 / Hugging Face Spaces（以 UID 1000 非 root 运行，端口 7860）
#   - 本地 docker run（可用 root，端口由 PORT 环境变量决定）
# 基础镜像可通过 --build-arg 覆盖：中国大陆 Docker Hub 不可达时，
# 先 docker pull <镜像源>/library/python:3.11-slim，再指定 BASE_IMAGE 构建即可绕开。
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PORT=7860

# pip 走阿里云（包最全，实测清华 TUNA 对部分 wheel 会返回 403）。
# 境外构建可改为：docker build --build-arg PIP_INDEX=https://pypi.org/simple .
ARG PIP_INDEX=https://mirrors.aliyun.com/pypi/simple

# 多数托管平台（魔搭创空间 / Hugging Face Spaces）以 UID 1000 运行容器；
# 预先建好同名用户与 HOME，避免非 root 运行时 $HOME 不可写。
RUN useradd -m -u 1000 user

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -i "$PIP_INDEX" -r requirements.txt

COPY --chown=user . .
RUN chmod +x docker-entrypoint.sh

USER user
ENV HOME=/home/user

EXPOSE 7860

ENTRYPOINT ["./docker-entrypoint.sh"]
