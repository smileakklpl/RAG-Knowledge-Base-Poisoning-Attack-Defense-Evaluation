-- Migration 01: Add trust_score column for Isolation Forest defense
-- Target database: rag_poison_if  (DO NOT run on rag_poison)
-- Run after init.sql has already created the chunks table.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS trust_score FLOAT;

COMMENT ON COLUMN chunks.trust_score IS
    'Isolation Forest anomaly score [0,1]. NULL = original clean chunk (Phase 1). '
    'Higher value = more anomalous embedding = more suspicious.';
