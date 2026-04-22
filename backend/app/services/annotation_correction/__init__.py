# 标注矫正服务模块
from .service import AnnotationCorrectionService, create_correction_service
from .prompts import (
    format_statement_extraction_prompt,
    format_difference_comparison_prompt,
    format_verification_question_prompt,
    format_evidence_verification_prompt,
    format_doubt_judgment_prompt,
)

__all__ = [
    "AnnotationCorrectionService",
    "create_correction_service",
    "format_statement_extraction_prompt",
    "format_difference_comparison_prompt",
    "format_verification_question_prompt",
    "format_evidence_verification_prompt",
    "format_doubt_judgment_prompt",
]