"""后端开发服务器：等价于 `uvicorn app.main:app --reload`，但修掉了 Windows 上的重载卡死。

## 问题

uvicorn 热重载重启子进程时，Windows 分支走的是 `uvicorn/supervisors/basereload.py` 里的：

    os.kill(self.process.pid, signal.CTRL_C_EVENT)
    self.process.join()          # 没有超时

CTRL_C_EVENT 是控制台信号，要求目标是一个**进程组**；而 uvicorn 的子进程由
multiprocessing spawn 拉起，处在父进程的进程组里。信号因此送不到子进程
（在 IDE、隐藏窗口、输出被重定向 —— 也就是没有控制台 —— 的启动方式下更是直接无效），
子进程不死，而 join() 又没有超时，于是永久阻塞：日志停在 "Reloading..."，服务再也
不会起来，但监听端口还握着旧进程。

上游已知且未修：encode/uvicorn#2292、encode/uvicorn#1972（本仓库用到的 0.34.0 / 0.27.0 均未修）。

## 修法

把发往子进程的 CTRL_C_EVENT 换成 SIGTERM。Windows 上 os.kill 对 CTRL_C_EVENT
以外的信号一律走 TerminateProcess，必定生效，join() 能返回，重载恢复正常。

代价是子进程不执行 lifespan 关闭钩子 —— 开发环境可接受，POSIX 上 uvicorn 用的
`process.terminate()` 同样是一次硬杀。

## 用法

    python dev.py                  # 0.0.0.0:8000，开启热重载
    python dev.py --port 8011      # 换端口
    python dev.py --no-reload      # 关闭热重载，退化成普通 uvicorn
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

import uvicorn


def _patch_windows_reload() -> None:
    """把 uvicorn 重载用发往子进程的 CTRL_C_EVENT 换成必定生效的 SIGTERM。

    只改这一个信号，其余信号原样透传，并忽略「进程已退出」的错误 —— 那种情况下
    子进程本来就死了，join() 不会阻塞。
    """
    if sys.platform != "win32":
        return

    real_kill = os.kill

    def kill(pid: int, sig: int) -> None:
        if sig == signal.CTRL_C_EVENT:
            sig = signal.SIGTERM
        try:
            real_kill(pid, sig)
        except ProcessLookupError:
            pass

    os.kill = kill  # type: ignore[assignment]


def main() -> None:
    parser = argparse.ArgumentParser(description="JQ-Eval 后端开发服务器")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument("--no-reload", action="store_true", help="关闭热重载")
    args = parser.parse_args()

    # 切到 backend/ 目录：既能保证 app.main 可导入，也让热重载监听的就是应用代码，
    # 这样从仓库根目录或 IDE 里直接跑这个脚本都能工作。
    os.chdir(Path(__file__).resolve().parent)

    if not args.no_reload:
        _patch_windows_reload()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
    )


if __name__ == "__main__":
    main()
