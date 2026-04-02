#!/bin/bash

# JQ-Eval Backend 启动脚本

echo "🚀 启动 JQ-Eval 后端服务..."

# 切换到后端目录
cd "$(dirname "$0")"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "📦 创建虚拟环境..."
    python -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null

# 安装依赖
echo "📥 安装依赖..."
pip install -r requirements.txt -q

# 启动服务
echo "✅ 启动服务..."
echo "📍 API地址: http://localhost:8000"
echo "📍 文档地址: http://localhost:8000/docs"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload