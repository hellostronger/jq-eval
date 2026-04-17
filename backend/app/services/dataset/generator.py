# Ragas 测试数据集生成器
from typing import List, Dict, Any, Optional
from langchain.schema import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
import logging
import asyncio

from .adapters.base import DocumentAdapter

logger = logging.getLogger(__name__)


class DatasetGenerator:
    """测试数据集生成器

    使用 Ragas TestsetGenerator 从文档自动生成测试数据
    """

    def __init__(self, llm: ChatOpenAI, embeddings: OpenAIEmbeddings):
        """初始化生成器

        Args:
            llm: LangChain LLM 实例
            embeddings: LangChain Embeddings 实例
        """
        self.llm = llm
        self.embeddings = embeddings

    async def generate(
        self,
        adapter: DocumentAdapter,
        test_size: int = 10,
        distributions: Dict[str, float] = None
    ) -> List[Dict[str, Any]]:
        """生成测试数据

        Args:
            adapter: 文档适配器，用于加载源文档
            test_size: 生成的问题数量
            distributions: 问题类型分布，默认:
                - simple: 0.5 (简单问题)
                - reasoning: 0.3 (推理问题)
                - multi_context: 0.2 (多上下文问题)

        Returns:
            生成的 QA 数据列表，每个包含:
                - question: 问题
                - ground_truth: 标准答案
                - contexts: 相关上下文列表
                - evolution_type: 问题类型
        """
        if distributions is None:
            distributions = {
                "simple": 0.5,
                "reasoning": 0.3,
                "multi_context": 0.2
            }

        # 1. 通过 Adapter 加载文档
        logger.info(f"开始加载文档，源信息: {adapter.get_source_info()}")
        documents = await adapter.load()

        if not documents:
            logger.warning("没有加载到任何文档")
            return []

        logger.info(f"加载了 {len(documents)} 个文档片段")

        # 2. 调用 Ragas TestsetGenerator (在同步环境中运行)
        try:
            testset = await asyncio.to_thread(
                self._run_ragas_generator,
                documents,
                test_size,
                distributions
            )

            # 3. 转换为 QARecord 格式
            qa_records = self._convert_to_qa_records(testset)

            logger.info(f"成功生成 {len(qa_records)} 条测试数据")
            return qa_records

        except ImportError as e:
            logger.error(f"Ragas 导入失败: {e}")
            raise RuntimeError(
                "Ragas 未安装或版本不兼容。请确保 ragas==0.1.7 已安装。"
            )
        except Exception as e:
            logger.error(f"生成测试数据失败: {e}")
            raise

    def _run_ragas_generator(
        self,
        documents: List[Document],
        test_size: int,
        distributions: Dict[str, float]
    ):
        """运行 Ragas TestsetGenerator (同步方法)

        Ragas 0.1.x 版本 API:
        - TestsetGenerator.from_langchain()
        - generate_with_langchain_docs()
        """
        from ragas.testset.generator import TestsetGenerator
        from ragas.testset.evolutions import simple, reasoning, multi_context

        # 创建生成器
        generator = TestsetGenerator.from_langchain(
            self.llm,
            self.embeddings
        )

        # 配置问题类型分布
        distribution_map = {
            simple: distributions.get("simple", 0.5),
            reasoning: distributions.get("reasoning", 0.3),
            multi_context: distributions.get("multi_context", 0.2),
        }

        # 生成测试数据
        testset = generator.generate_with_langchain_docs(
            documents=documents,
            test_size=test_size,
            distributions=distribution_map
        )

        return testset

    def _convert_to_qa_records(self, testset) -> List[Dict[str, Any]]:
        """将 Ragas Testset 转换为 QARecord 格式

        Ragas 0.1.x 输出格式 (DataFrame):
        - question: 问题
        - ground_truth: 标准答案
        - contexts: 上下文列表
        - evolution_type: 问题类型 (simple/reasoning/multi_context)
        """
        # 转换为 DataFrame
        df = testset.to_pandas()

        qa_records = []
        for _, row in df.iterrows():
            record = {
                "question": row.get("question", ""),
                "ground_truth": row.get("ground_truth", ""),
                "contexts": row.get("contexts", []),
                "evolution_type": row.get("evolution_type", "unknown"),
                "metadata": {
                    "source": "ragas_generated",
                    "evolution_type": row.get("evolution_type", "unknown"),
                }
            }

            # 确保 contexts 是列表
            if isinstance(record["contexts"], str):
                record["contexts"] = [record["contexts"]]
            elif not isinstance(record["contexts"], list):
                record["contexts"] = []

            qa_records.append(record)

        return qa_records


async def generate_test_data(
    llm: ChatOpenAI,
    embeddings: OpenAIEmbeddings,
    adapter: DocumentAdapter,
    test_size: int = 10,
    distributions: Dict[str, float] = None
) -> List[Dict[str, Any]]:
    """便捷函数：生成测试数据

    Args:
        llm: LLM 实例
        embeddings: Embeddings 实例
        adapter: 文档适配器
        test_size: 生成数量
        distributions: 问题类型分布

    Returns:
        QA 数据列表
    """
    generator = DatasetGenerator(llm, embeddings)
    return await generator.generate(
        adapter=adapter,
        test_size=test_size,
        distributions=distributions
    )