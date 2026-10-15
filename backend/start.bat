@echo off
chcp 65001 >nul
echo 🚀 启动 JQ-Eval 后端服务...

cd /d %~dp0

REM 检查虚拟环境
if not exist "venv" (
    echo 📦 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 安装依赖
echo 📥 安装依赖...
pip install -r requirements.txt -q

REM 启动服务
echo ✅ 启动服务...
echo 📍 API地址: http://localhost:8000
echo 📍 文档地址: http://localhost:8000/docs
echo.

REM 用 dev.py 而非 `uvicorn --reload`：后者的 Windows 重载会卡死在 "Reloading..."
python dev.py