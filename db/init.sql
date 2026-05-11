-- RAG Knowledge Poisoning Experiment — pgvector schema
-- Auto-executed on first container start via docker-entrypoint-initdb.d/

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    chunk_id    TEXT UNIQUE NOT NULL,
    document    TEXT NOT NULL,
    embedding   VECTOR(1024) NOT NULL,       -- bge-m3 output dimension
    doc_id      TEXT NOT NULL,
    source      TEXT NOT NULL,               -- 'cuad' | 'phase1_poison'
    is_poison   BOOLEAN NOT NULL DEFAULT FALSE,
    attack_type TEXT,                        -- hijack | blocker | stealth | NULL
    chunk_index INT,
    inserted_at TIMESTAMP DEFAULT now()
);

-- HNSW index for fast cosine similarity search (pgvector recommended)
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
