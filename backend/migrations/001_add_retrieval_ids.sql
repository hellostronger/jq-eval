-- Migration: Add retrieval_ids column to invocation_results table
-- This column stores the chunk IDs retrieved by the RAG system for retrieval metrics calculation

-- Add retrieval_ids column
ALTER TABLE invocation_results
ADD COLUMN IF NOT EXISTS retrieval_ids JSONB;

-- Add comment
COMMENT ON COLUMN invocation_results.retrieval_ids IS '检索到的chunk ID列表，用于MRR@K、HitRate@K等检索指标计算';