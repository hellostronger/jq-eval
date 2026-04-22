# RAG系统适配器工厂
from typing import Dict, Any, Type
from .base import BaseRAGAdapter


# 适配器注册表（延迟导入）
ADAPTER_REGISTRY: Dict[str, str] = {
    "dify": "app.services.adapters.dify_adapter.DifyAdapter",
    "coze": "app.services.adapters.coze_adapter.CozeAdapter",
    "fastgpt": "app.services.adapters.fastgpt_adapter.FastGPTAdapter",
    "n8n": "app.services.adapters.n8n_adapter.N8nAdapter",
    "custom": "app.services.adapters.custom_adapter.CustomAdapter",
    "direct_llm": "app.services.adapters.direct_llm_adapter.DirectLLMAdapter",
}


class AdapterFactory:
    """RAG系统适配器工厂"""

    @staticmethod
    def create(system_type: str, config: Dict[str, Any]) -> BaseRAGAdapter:
        """创建适配器实例"""
        if system_type not in ADAPTER_REGISTRY:
            raise ValueError(f"不支持的系统类型: {system_type}")

        # 动态导入适配器类
        module_path = ADAPTER_REGISTRY[system_type]
        parts = module_path.rsplit(".", 1)
        module_name = parts[0]
        class_name = parts[1]

        import importlib
        module = importlib.import_module(module_name)
        adapter_class: Type[BaseRAGAdapter] = getattr(module, class_name)

        return adapter_class(config)

    @staticmethod
    def get_supported_systems() -> list:
        """获取支持的系统列表"""
        return list(ADAPTER_REGISTRY.keys())