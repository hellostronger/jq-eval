# Ragas 测试数据集生成器
from typing import List, Dict, Any
from langchain.schema import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
import logging
import asyncio
import re

from .adapters.base import DocumentAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ragas 0.4.3 的 JSON 解析容错
#
# ragas 的 `RagasOutputParser` 只有一条路：extract_json + Pydantic 校验。校验失败
# 就让 LLM 重写一段「修正后的输出串」，而那个修正 prompt（FixOutputFormat）的输出
# 模型是 `StringIO`（要求形如 {"text": "..."}）。上游模型如果原样再吐一遍 JSON，
# 二次校验必然失败；而那次 `super().parse(...)` 写在 try 之外，异常会直接捅穿整轮
# testset 生成。
#
# 实测代价：2026-10-31 那次跑到 1273 秒、30% 阶段整轮失败，报错
#   Failed to parse StringIO from completion {"name": "RAGFlow API ...", ...}
# 而它只是「修正步骤的回答没套 {"text": ...}」，不值得让整轮作废。
#
# 这里的替换只放宽解析，不改任何 prompt、不改生成逻辑：
#   1) 解析时依次尝试 extract_json、原文、以及从每个 {/[ 起括号配平的片段；
#   2) 再试一次「去掉尾随逗号」；
#   3) 若目标模型就是 StringIO，确定性地把原文包进去（修正步骤本来只需要一段文本）；
#   4) 仍然失败才让 LLM 修复一次，且修复结果同样走宽松解析（不再用 super().parse）。
# ---------------------------------------------------------------------------
_LENIENT_PARSER_INSTALLED = False


def _install_lenient_output_parser() -> bool:
    """替换 ragas 的输出解析器为容错版本（进程内幂等）。

    Returns:
        True 表示已启用（含此前已启用过的情况）。
    """
    global _LENIENT_PARSER_INSTALLED
    if _LENIENT_PARSER_INSTALLED:
        return True

    import ragas.prompt.pydantic_prompt as pp

    class LenientRagasOutputParser(pp.RagasOutputParser):
        """放宽 JSON 解析，避免「修正回答格式不对」把整轮生成带崩。"""

        @staticmethod
        def _candidates(text: str):
            text = (text or "").strip()
            if not text:
                return []

            out = []
            try:
                extracted = pp.extract_json(text)
            except Exception:  # noqa: BLE001 - 宽松解析不该自己抛
                extracted = None
            if extracted:
                out.append(extracted)
            out.append(text)

            # 「前面带推理正文」的形态：从每个括号起点做配平，取最外层片段
            for i, ch in enumerate(text):
                if ch not in "{[":
                    continue
                depth = 0
                in_str = False
                escaped = False
                for j in range(i, len(text)):
                    c = text[j]
                    if in_str:
                        if escaped:
                            escaped = False
                        elif c == "\\":
                            escaped = True
                        elif c == '"':
                            in_str = False
                        continue
                    if c == '"':
                        in_str = True
                    elif c in "{[":
                        depth += 1
                    elif c in "}]":
                        depth -= 1
                        if depth == 0:
                            out.append(text[i:j + 1])
                            break

            seen = set()
            uniq = []
            for cand in out:
                if cand and cand not in seen:
                    seen.add(cand)
                    uniq.append(cand)
            return uniq

        @classmethod
        def _try_parse(cls, model, text: str):
            last_err = None
            for cand in cls._candidates(text):
                variants = [cand, re.sub(r",\s*([}\]])", r"\1", cand)]
                for variant in variants:
                    try:
                        return model.model_validate_json(variant)
                    except Exception as e:  # noqa: BLE001
                        last_err = e
            if model is pp.StringIO:
                # 修正步骤：模型常直接回一段文本而不是 {"text": ...}，
                # 自由文本没有「格式错」可言，所以兜底包一层，绝不抛。
                return pp.StringIO(text=(text or "").strip())
            if last_err is not None:
                raise last_err
            raise ValueError("empty output string")

        async def parse_output_string(
            self,
            output_string: str,
            prompt_value,
            llm,
            callbacks,
            retries_left: int = 1,
        ):
            model = self.pydantic_object
            model_name = getattr(model, "__name__", str(model))

            try:
                return self._try_parse(model, output_string)
            except Exception as first_err:  # noqa: BLE001
                # 把原始输出打出来：主因一直没被记录过，没有它就查不动
                logger.warning(
                    "[ragas] 解析 %s 失败（%s），原始输出 %d 字符：%r",
                    model_name,
                    first_err,
                    len(output_string or ""),
                    (output_string or "")[:600],
                )

            if retries_left == 0:
                raise pp.RagasOutputParserException()

            try:
                prompt_text = (
                    prompt_value.to_string()
                    if hasattr(prompt_value, "to_string")
                    else str(prompt_value)
                )
                fixed = await pp.fix_output_format_prompt.generate(
                    llm=llm,
                    data=pp.OutputStringAndPrompt(
                        output_string=output_string or "",
                        prompt_value=prompt_text,
                    ),
                    callbacks=callbacks,
                    retries_left=max(0, retries_left - 1),
                )
            except Exception as repair_err:  # noqa: BLE001
                logger.warning("[ragas] 修复请求本身失败：%s", repair_err)
                raise pp.RagasOutputParserException()

            fixed_text = getattr(fixed, "text", "") or ""
            try:
                return self._try_parse(model, fixed_text)
            except Exception as repair_err:  # noqa: BLE001
                logger.warning(
                    "[ragas] 修复后仍解析 %s 失败（%s），修复输出 %d 字符：%r",
                    model_name,
                    repair_err,
                    len(fixed_text),
                    fixed_text[:600],
                )
                raise pp.RagasOutputParserException()

    pp.RagasOutputParser = LenientRagasOutputParser
    _LENIENT_PARSER_INSTALLED = True
    logger.info(
        "[ragas] 已启用容错 JSON 解析（替换 "
        "ragas.prompt.pydantic_prompt.RagasOutputParser）"
    )
    return True


class DatasetGenerator:
    """测试数据集生成器

    使用 Ragas 0.4.x 的 TestsetGenerator 从**已切分的文档片段**生成评估数据。

    与 0.1.x 的差别（决定了为什么用 generate_with_chunks 而不是 generate_with_langchain_docs）：
    - 0.4.x 把 langchain Document 建成 NodeType.DOCUMENT，而 prechunked 系列的
      transforms（NERExtractor 等）只处理 NodeType.CHUNK，于是 entities 属性
      永远为空，single-hop 合成器会抛 "No nodes found with the `entities` property"。
    - generate_with_chunks 直接把输入当 CHUNK 节点，并默认挂上
      default_transforms_for_prechunked，才是本项目（adapter 已切好片段）的正确入口。
    """

    # ragas 0.4.x 只有 single_hop 合成器在本项目的语料上可用：
    # multi-hop 需要同一实体的多个 chunk 集群，片段很少时直接判不可用。
    # 并发保持 1，避免把上游网关打满。
    RUN_MAX_WORKERS = 1
    RUN_TIMEOUT_SECONDS = 180

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
            distributions: 问题类型分布。ragas 0.4.x 已无 simple/reasoning/multi_context
                的等价概念，此参数仅为兼容调用方签名而保留（会被记录但不再生效）。

        Returns:
            生成的 QA 数据列表，每个包含:
                - question: 问题
                - ground_truth: 标准答案
                - contexts: 相关上下文列表
                - evolution_type: 问题类型（0.4.x 里是合成器名称）
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
        logger.info(
            f"ragas 0.4.x 仅支持 single_hop 合成器，已忽略类型分布: {distributions}"
        )

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
                "Ragas 未安装或版本不兼容。本项目依赖 ragas>=0.4（见 requirements.txt）。"
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

        Ragas 0.4.x API:
        - TestsetGenerator.from_langchain(llm, embedding_model)
        - generate_with_chunks(chunks, testset_size, query_distribution, run_config)
        """
        from ragas.testset import TestsetGenerator
        from ragas.testset.synthesizers.single_hop.specific import (
            SingleHopSpecificQuerySynthesizer,
        )
        from ragas.run_config import RunConfig

        # 必须在建 TestsetGenerator 之前装：解析器是 generate 时才实例化的，
        # 但先装能保证整轮（persona / 实体 / 问题合成）都走容错版本。
        _install_lenient_output_parser()

        run_config = RunConfig(
            max_workers=self.RUN_MAX_WORKERS,
            timeout=self.RUN_TIMEOUT_SECONDS,
        )

        generator = TestsetGenerator.from_langchain(
            self.llm,
            self.embeddings,
        )

        # 只用 single_hop：本项目语料按片段提供，multi-hop 需要多 chunk 实体集群。
        synthesizer = SingleHopSpecificQuerySynthesizer(llm=generator.llm)
        query_distribution = [(synthesizer, 1.0)]

        testset = generator.generate_with_chunks(
            chunks=documents,
            testset_size=test_size,
            query_distribution=query_distribution,
            run_config=run_config,
            raise_exceptions=True,
        )

        return testset

    def _convert_to_qa_records(self, testset) -> List[Dict[str, Any]]:
        """将 Ragas Testset 转换为 QARecord 格式

        Ragas 0.4.x 输出是 Testset(samples=[TestsetSample])，
        不再有 DataFrame / to_pandas()。
        - TestsetSample.eval_sample: SingleTurnSample
          - user_input       -> question
          - reference        -> ground_truth
          - reference_contexts / retrieved_contexts -> contexts
        - TestsetSample.synthesizer_name -> evolution_type
        """
        qa_records = []

        for sample in getattr(testset, "samples", []) or []:
            eval_sample = getattr(sample, "eval_sample", None)
            if eval_sample is None:
                continue

            question = getattr(eval_sample, "user_input", "") or ""
            ground_truth = getattr(eval_sample, "reference", "") or ""
            contexts = (
                getattr(eval_sample, "reference_contexts", None)
                or getattr(eval_sample, "retrieved_contexts", None)
                or []
            )
            evolution_type = getattr(sample, "synthesizer_name", "") or "unknown"

            # 问题或答案为空的行没有评估价值，直接丢弃（不编造）
            if not str(question).strip() or not str(ground_truth).strip():
                continue

            # 确保 contexts 是列表
            if isinstance(contexts, str):
                contexts = [contexts]
            elif not isinstance(contexts, list):
                contexts = []

            qa_records.append({
                "question": str(question).strip(),
                "ground_truth": str(ground_truth).strip(),
                "contexts": contexts,
                "evolution_type": evolution_type,
                "metadata": {
                    "source": "ragas_generated",
                    "evolution_type": evolution_type,
                },
            })

        return qa_records
