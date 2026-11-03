-- 调用批次取样范围（qa_limit / qa_offset）
-- 旧库升级用；开发环境由 Base.metadata.create_all 自动建表。
--
-- 背景：批次原先只能整数据集跑。2556 题的 MultiHop 或每题几分钟的 UltraData
-- 想"先试 40 题"只能再建一个小数据集，同一份语料因此在库里留下多份副本，
-- 评估口径也各不相通。这里给批次自己带上取样范围。
-- 两列都可空，空值＝沿用旧行为（跑整个数据集），老批次不受影响。

ALTER TABLE invocation_batches
ADD COLUMN IF NOT EXISTS qa_limit INTEGER;

ALTER TABLE invocation_batches
ADD COLUMN IF NOT EXISTS qa_offset INTEGER;
