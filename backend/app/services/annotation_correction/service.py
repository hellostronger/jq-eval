# 标注矫正服务实现
import json
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langchain_openai import ChatOpenAI

from app.models import InvocationResult, QARecord, InvocationBatch, AnnotationCorrection
from app.services.llm.llm_client import create_llm_from_model_id
from .prompts import (
    format_statement_extraction_prompt,
    format_difference_comparison_prompt,
    format_verification_question_prompt,
    format_evidence_verification_prompt,
    format_doubt_judgment_prompt,
)

logger = logging.getLogger(__name__)


class AnnotationCorrectionService:
    """标注矫正服务"""

    def __init__(self, db: AsyncSession, llm: ChatOpenAI):
        self.db = db
        self.llm = llm

    async def analyze_single(
        self,
        invocation_result_id: UUID,
        qa_record_id: UUID,
        batch_id: Optional[UUID] = None,
    ) -> AnnotationCorrection:
        """分析单条QA数据的差异"""
        start_time = time.time()

        # 创建矫正记录
        correction = AnnotationCorrection(
            invocation_result_id=invocation_result_id,
            qa_record_id=qa_record_id,
            batch_id=batch_id,
            status="analyzing",
        )
        self.db.add(correction)
        await self.db.commit()
        await self.db.refresh(correction)

        try:
            # 获取调用结果和QA记录
            result = await self._get_invocation_result(invocation_result_id)
            qa_record = await self._get_qa_record(qa_record_id)

            if not result or not qa_record:
                correction.status = "failed"
                correction.error = "未找到调用结果或QA记录"
                await self.db.commit()
                return correction

            # 检查必要数据
            if not result.answer or not qa_record.ground_truth:
                correction.status = "completed"
                correction.is_doubtful = False
                correction.summary = "缺少系统回复或标准答案，无法进行差异分析"
                await self.db.commit()
                return correction

            # 获取分片内容
            chunks = await self._get_chunks_from_result(result)

            # 执行差异分析
            difference_analysis, evidence_results = await self._analyze_differences(
                result.question,
                result.answer,
                qa_record.ground_truth,
                chunks,
            )

            # 更新矫正记录
            correction.different_statements = difference_analysis.get("all_differences", [])
            correction.evidence_results = evidence_results
            correction.is_doubtful = difference_analysis.get("is_doubtful", False)
            correction.doubt_reason = difference_analysis.get("doubt_reason")
            correction.summary = difference_analysis.get("summary")
            correction.status = "completed"
            correction.analysis_duration = f"{time.time() - start_time:.2f}s"

            await self.db.commit()
            await self.db.refresh(correction)

            return correction

        except Exception as e:
            logger.error(f"矫正分析失败: {e}")
            correction.status = "failed"
            correction.error = str(e)
            correction.analysis_duration = f"{time.time() - start_time:.2f}s"
            await self.db.commit()
            return correction

    async def analyze_batch(
        self,
        batch_id: UUID,
    ) -> List[AnnotationCorrection]:
        """批量分析一个批次的所有QA数据"""
        # 获取批次信息
        batch = await self._get_batch(batch_id)
        if not batch:
            raise ValueError(f"批次 {batch_id} 不存在")

        # 获取批次所有结果
        results = await self._get_batch_results(batch_id)

        corrections = []
        for result in results:
            correction = await self.analyze_single(
                invocation_result_id=result.id,
                qa_record_id=result.qa_record_id,
                batch_id=batch_id,
            )
            corrections.append(correction)

        return corrections

    async def _analyze_differences(
        self,
        question: str,
        system_answer: str,
        ground_truth: str,
        chunks: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """执行差异分析流程"""
        # 1. 抽取声明
        system_statements = await self._extract_statements(system_answer)
        ground_truth_statements = await self._extract_statements(ground_truth)

        # 2. 对比差异
        differences = await self._compare_differences(
            system_statements,
            ground_truth_statements,
        )

        # 3. 生成验证问题并验证证据
        evidence_results = []
        all_differences = []

        # 处理系统独有的声明
        for stmt in differences.get("system_only", []):
            verification_q = await self._generate_verification_question(stmt, "system_only", differences)
            evidence = await self._verify_evidence(stmt, verification_q, chunks)
            evidence_results.append(evidence)
            all_differences.append({
                "statement": stmt,
                "source": "system",
                "type": "unique",
                "verification_question": verification_q,
                "supported": evidence.get("supported", False),
            })

        # 处理标准答案独有的声明
        for stmt in differences.get("ground_truth_only", []):
            verification_q = await self._generate_verification_question(stmt, "ground_truth_only", differences)
            evidence = await self._verify_evidence(stmt, verification_q, chunks)
            evidence_results.append(evidence)
            all_differences.append({
                "statement": stmt,
                "source": "ground_truth",
                "type": "unique",
                "verification_question": verification_q,
                "supported": evidence.get("supported", False),
            })

        # 处理冲突声明
        for conflict in differences.get("conflicting", []):
            stmt = conflict.get("system_statement", "")
            verification_q = await self._generate_verification_question(stmt, "conflicting", differences)
            evidence = await self._verify_evidence(stmt, verification_q, chunks)
            evidence_results.append(evidence)
            all_differences.append({
                "statement": stmt,
                "source": "system",
                "type": "conflicting",
                "conflict_with": conflict.get("ground_truth_statement"),
                "conflict_description": conflict.get("conflict_description"),
                "verification_question": verification_q,
                "supported": evidence.get("supported", False),
            })

        # 4. 判断是否存疑
        doubt_judgment = await self._judge_doubt(
            question,
            system_answer,
            ground_truth,
            differences,
            evidence_results,
        )

        return {
            "all_differences": all_differences,
            "is_doubtful": doubt_judgment.get("is_doubtful", False),
            "doubt_reason": doubt_judgment.get("doubt_reason"),
            "summary": doubt_judgment.get("summary"),
        }, evidence_results

    async def _extract_statements(self, text: str) -> List[str]:
        """从文本中抽取声明"""
        prompt = format_statement_extraction_prompt(text)
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content
            # 解析JSON响应
            statements = json.loads(content.strip())
            if isinstance(statements, list):
                return statements
            return []
        except Exception as e:
            logger.warning(f"声明抽取失败: {e}")
            # 简单分句作为备选
            sentences = text.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").split("\n")
            return [s.strip() for s in sentences if s.strip()]

    async def _compare_differences(
        self,
        system_statements: List[str],
        ground_truth_statements: List[str],
    ) -> Dict[str, Any]:
        """对比两个声明列表的差异"""
        prompt = format_difference_comparison_prompt(
            system_statements,
            ground_truth_statements,
        )
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content
            differences = json.loads(content.strip())
            return differences
        except Exception as e:
            logger.warning(f"差异对比失败: {e}")
            return {
                "system_only": [],
                "ground_truth_only": [],
                "conflicting": [],
            }

    async def _generate_verification_question(
        self,
        statement: str,
        diff_type: str,
        differences: Dict[str, Any],
    ) -> str:
        """生成验证问题"""
        diff_str = json.dumps(differences, ensure_ascii=False)
        prompt = format_verification_question_prompt(statement, diff_type, diff_str)
        try:
            response = await self.llm.ainvoke(prompt)
            return response.content.strip()
        except Exception as e:
            logger.warning(f"问题生成失败: {e}")
            return f"请验证以下声明是否正确：{statement}"

    async def _verify_evidence(
        self,
        statement: str,
        question: str,
        chunks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """验证分片是否支持声明"""
        if not chunks:
            return {
                "statement": statement,
                "question": question,
                "supported": False,
                "supporting_chunks": [],
                "reason": "没有可用的分片",
            }

        prompt = format_evidence_verification_prompt(statement, question, chunks)
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content
            result = json.loads(content.strip())
            result["statement"] = statement
            result["question"] = question
            return result
        except Exception as e:
            logger.warning(f"证据验证失败: {e}")
            return {
                "statement": statement,
                "question": question,
                "supported": False,
                "supporting_chunks": [],
                "reason": f"验证失败: {e}",
            }

    async def _judge_doubt(
        self,
        question: str,
        system_answer: str,
        ground_truth: str,
        differences: Dict[str, Any],
        evidence_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """判断是否存疑"""
        prompt = format_doubt_judgment_prompt(
            question,
            system_answer,
            ground_truth,
            differences,
            evidence_results,
        )
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content
            result = json.loads(content.strip())
            return result
        except Exception as e:
            logger.warning(f"存疑判断失败: {e}")
            # 基于证据结果的简单判断
            unsupported_count = sum(1 for e in evidence_results if not e.get("supported", False))
            return {
                "is_doubtful": unsupported_count > 0,
                "doubt_reason": f"有{unsupported_count}条差异声明无证据支持",
                "summary": f"发现{len(evidence_results)}条差异，{unsupported_count}条无证据支持",
            }

    async def _get_invocation_result(self, result_id: UUID) -> Optional[InvocationResult]:
        """获取调用结果"""
        result = await self.db.execute(
            select(InvocationResult).where(InvocationResult.id == result_id)
        )
        return result.scalar_one_or_none()

    async def _get_qa_record(self, qa_id: UUID) -> Optional[QARecord]:
        """获取QA记录"""
        result = await self.db.execute(
            select(QARecord).where(QARecord.id == qa_id)
        )
        return result.scalar_one_or_none()

    async def _get_batch(self, batch_id: UUID) -> Optional[InvocationBatch]:
        """获取批次"""
        result = await self.db.execute(
            select(InvocationBatch).where(InvocationBatch.id == batch_id)
        )
        return result.scalar_one_or_none()

    async def _get_batch_results(self, batch_id: UUID) -> List[InvocationResult]:
        """获取批次所有结果"""
        result = await self.db.execute(
            select(InvocationResult).where(InvocationResult.batch_id == batch_id)
        )
        return result.scalars().all()

    async def _get_chunks_from_result(self, result: InvocationResult) -> List[Dict[str, Any]]:
        """从调用结果获取分片内容"""
        contexts = result.contexts or []
        chunks = []
        for i, ctx in enumerate(contexts):
            chunks.append({
                "chunk_index": i,
                "content": ctx,
            })
        return chunks


async def create_correction_service(
    db: AsyncSession,
    llm_model_id: UUID,
) -> AnnotationCorrectionService:
    """创建矫正服务实例"""
    llm = await create_llm_from_model_id(db, llm_model_id)
    if not llm:
        raise ValueError(f"无法创建LLM实例，模型ID: {llm_model_id}")
    return AnnotationCorrectionService(db, llm)