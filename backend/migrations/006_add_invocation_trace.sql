-- 调用结果的检索轨迹（trace）
-- 旧库升级用；开发环境由 Base.metadata.create_all 自动建表。
--
-- 背景：InvocationResult 只存 contexts / retrieval_ids，被测系统回传的检索轨迹
-- （向量/全文/图各通道的排序、树定位的轮次、是否掉进兜底取样）在落库时就丢了。
-- 于是 badcase 归因只能给出「漏召」这一个结论：到底是各通道都没捞到（索引/分片问题），
-- 还是某一路捞到了却在融合排序里被挤掉（配比/重排问题），两者要改的地方完全不同，
-- 光看 retrieval_ids 分不出来。
--
-- 可空 JSON：不回传轨迹的老系统保持 NULL，分析层据此区分「没轨迹」与「没命中」。

ALTER TABLE invocation_results
ADD COLUMN IF NOT EXISTS trace JSONB;
