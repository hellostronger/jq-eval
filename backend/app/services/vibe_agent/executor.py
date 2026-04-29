# 工作流沙箱执行器
from typing import Dict, Any, Optional
import json
import asyncio
import sys
import os
import tempfile

# 尝试导入 agent-sandbox
try:
    from agent_sandbox import AsyncSandbox
    HAS_AGENT_SANDBOX = True
except ImportError:
    HAS_AGENT_SANDBOX = False
    AsyncSandbox = None
    print("Warning: agent-sandbox not installed, will use local subprocess execution")


class WorkflowExecutor:
    """工作流沙箱执行器

    支持两种执行方式：
    1. RemoteSandbox: 远程沙箱服务（通过 SANDBOX_URL 配置，使用 agent-sandbox SDK）
    2. LocalSubprocess: 本地子进程（备用方案，无依赖）
    """

    def __init__(
        self,
        timeout: int = None,
        max_memory_mb: int = None,
        sandbox_url: str = None,
    ):
        """
        Args:
            timeout: 执行超时时间（秒），默认从配置读取
            max_memory_mb: 最大内存限制（MB），默认从配置读取
            sandbox_url: 沙箱服务地址，配置则使用远程沙箱
        """
        from ...core.config import settings

        self.timeout = timeout or settings.SANDBOX_TIMEOUT
        self.max_memory_mb = max_memory_mb or settings.SANDBOX_MAX_MEMORY
        self.sandbox_url = sandbox_url or settings.SANDBOX_URL

        # 确定执行模式
        self.execution_mode = self._determine_mode()

        if self.execution_mode == "remote_sandbox":
            print(f"[VibeAgent] Using remote sandbox: {self.sandbox_url}")
        else:
            print("[VibeAgent] Using local subprocess execution")

    def _determine_mode(self) -> str:
        """确定执行模式"""
        # 如果配置了 SANDBOX_URL 且 agent-sandbox 已安装，使用远程沙箱
        if self.sandbox_url and self.sandbox_url.strip() != "" and HAS_AGENT_SANDBOX:
            return "remote_sandbox"

        return "local_subprocess"

    async def execute(
        self,
        python_code: str,
        input_data: Dict[str, Any],
        llm_config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """在沙箱中执行工作流代码"""
        start_time = asyncio.get_event_loop().time()

        try:
            if self.execution_mode == "remote_sandbox":
                result = await self._execute_remote(python_code, input_data, llm_config)
            else:
                result = await self._execute_subprocess(python_code, input_data, llm_config)

            execution_time = asyncio.get_event_loop().time() - start_time

            return {
                "status": result.get("status", "success"),
                "result": result.get("result", {}),
                "execution_time": execution_time,
                "error": result.get("error"),
                "execution_mode": self.execution_mode,
            }

        except asyncio.TimeoutError:
            execution_time = asyncio.get_event_loop().time() - start_time
            return {
                "status": "timeout",
                "error": f"执行超时（>{self.timeout}秒）",
                "execution_time": execution_time,
                "execution_mode": self.execution_mode,
            }

        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
                "execution_time": execution_time,
                "execution_mode": self.execution_mode,
            }

    async def _execute_remote(
        self,
        python_code: str,
        input_data: Dict[str, Any],
        llm_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """使用远程沙箱服务执行"""
        full_code = self._build_sandbox_code(python_code, input_data, llm_config)

        try:
            # 使用 AsyncSandbox 连接远程沙箱
            sandbox = AsyncSandbox(base_url=self.sandbox_url)

            # 执行代码
            result = await sandbox.jupyter.execute_code(code=full_code)

            if result.data and result.data.outputs:
                output = result.data.outputs[0].get("text", "{}")
                try:
                    return json.loads(output)
                except json.JSONDecodeError:
                    return {"status": "success", "result": {"raw_output": output}}

            return {"status": "error", "error": "No output from sandbox"}

        except Exception as e:
            return {"status": "error", "error": f"Remote sandbox error: {str(e)}"}

    async def _execute_subprocess(
        self,
        python_code: str,
        input_data: Dict[str, Any],
        llm_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """使用本地子进程执行（备用方案）"""
        full_script = self._build_execution_script(python_code, input_data, llm_config)

        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write(full_script)
            script_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise

            output = stdout.decode('utf-8') if stdout else ''
            error_output = stderr.decode('utf-8') if stderr else ''

            if proc.returncode != 0:
                return {
                    "status": "error",
                    "error": error_output or f"Process exited with code {proc.returncode}",
                }

            try:
                return json.loads(output.strip())
            except json.JSONDecodeError:
                return {"status": "success", "result": {"raw_output": output}}

        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def _build_sandbox_code(
        self,
        python_code: str,
        input_data: Dict[str, Any],
        llm_config: Dict[str, Any],
    ) -> str:
        """构建沙箱执行代码"""
        env_setup = ""
        if llm_config:
            env_setup = f'''
import os
os.environ["OPENAI_API_KEY"] = "{llm_config.get('api_key', '')}"
os.environ["OPENAI_API_URL"] = "{llm_config.get('api_url', 'https://api.openai.com/v1')}"
os.environ["OPENAI_MODEL"] = "{llm_config.get('model', 'gpt-4o-mini')}"
'''

        execution_wrapper = f'''
import json

_input_data = {json.dumps(input_data, ensure_ascii=False)}

_result = None
try:
    if 'execute' in dir():
        _result = execute(_input_data.get("input", ""))
    elif 'app' in dir():
        _result = app.invoke({{
            "input": _input_data.get("input", ""),
            "output": "",
            "context": {{}}
        }})
    else:
        _result = {{'error': "No execute function or app found"}}

    print(json.dumps({{'status': "success", 'result': _result}}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({{'status': "error", 'error': str(e)}}, ensure_ascii=False))
'''

        return env_setup + "\n" + python_code + "\n" + execution_wrapper

    def _build_execution_script(
        self,
        python_code: str,
        input_data: Dict[str, Any],
        llm_config: Dict[str, Any],
    ) -> str:
        """构建完整执行脚本"""
        return self._build_sandbox_code(python_code, input_data, llm_config) + '''
import sys
try:
    pass
except Exception as e:
    sys.exit(1)
'''

    async def test_code(
        self,
        python_code: str,
        test_cases: list = None,
    ) -> Dict[str, Any]:
        """测试生成的代码"""
        results = []
        test_cases = test_cases or [{"input": "test", "expected_output": None}]

        for test_case in test_cases:
            input_data = {"input": test_case.get("input", "")}
            expected = test_case.get("expected_output")

            exec_result = await self.execute(python_code, input_data)

            passed = True
            if expected and exec_result.get("status") == "success":
                actual = exec_result.get("result")
                passed = self._compare_results(expected, actual)

            results.append({
                "input": test_case.get("input"),
                "expected": expected,
                "actual": exec_result.get("result"),
                "passed": passed,
                "execution_time": exec_result.get("execution_time"),
                "error": exec_result.get("error"),
            })

        return {
            "total": len(results),
            "passed": sum(1 for r in results if r["passed"]),
            "failed": sum(1 for r in results if not r["passed"]),
            "results": results,
        }

    def _compare_results(self, expected: Any, actual: Any) -> bool:
        """比较结果"""
        if expected is None:
            return True

        if isinstance(expected, dict) and isinstance(actual, dict):
            return all(actual.get(k) == v for k, v in expected.items() if k in actual)

        return str(expected) == str(actual)


# 全局执行器实例
_executor_instance: Optional[WorkflowExecutor] = None


def get_executor(
    timeout: int = None,
    max_memory_mb: int = None,
    sandbox_url: str = None,
) -> WorkflowExecutor:
    """获取执行器实例"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = WorkflowExecutor(
            timeout=timeout,
            max_memory_mb=max_memory_mb,
            sandbox_url=sandbox_url,
        )
    return _executor_instance


def reset_executor():
    """重置执行器实例"""
    global _executor_instance
    _executor_instance = None