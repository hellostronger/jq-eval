# 后端镜像：python:3.12-slim + requirements
# 依赖全部为预编译 wheel（PyMuPDF/lxml/pandas/cryptography 等均有官方 wheel），
# 无需 gcc 等系统编译链，slim 基础镜像即可安装
FROM python:3.12-slim

# 国内服务器构建时传镜像源加速：
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple docker compose -f deploy/docker-compose.app.yml build
# 不传则用官方源，海外环境零改动
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖再拷代码：requirements 不变时命中层缓存，改业务代码不重装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
