-- 文档解释（DocExplanation）功能下线：删除相关表（2026-09 重复面审计）
-- 依赖顺序：结果表 → 评估任务表 → 解释表（均为级联下游，反序删除）
DROP TABLE IF EXISTS doc_explanation_eval_results;
DROP TABLE IF EXISTS doc_explanation_evaluations;
DROP TABLE IF EXISTS doc_explanations;
