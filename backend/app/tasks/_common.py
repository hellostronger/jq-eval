# Celery 任务公共工具
import asyncio


def run_async(coro):
    """在同步环境（Celery worker）中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
