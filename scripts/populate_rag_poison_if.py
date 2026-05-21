"""
scripts/populate_rag_poison_if.py

One-shot script: loads n_clean_chunks CUAD chunks into rag_poison_if (is_original=TRUE).
Mirrors Phase 1 Step A but skips attack generation entirely.
Does NOT touch rag_poison or output/phase1/poison_chunks.json.

Usage:
    python scripts/populate_rag_poison_if.py
"""

import json
import os
import random
import sys
import uuid
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import ExperimentConfig

CONFIG_PATH = "configs/experiment_02_if.yaml"


def main() -> None:
    config = ExperimentConfig.from_yaml(CONFIG_PATH)
    db     = config.vector_db
    db_name = db.get("database", "rag_poison_if")

    print(f"[populate] Target DB : {db_name}")
    print(f"[populate] Clean chunks to load: {config.n_clean_chunks}")

    import psycopg2
    from pgvector.psycopg2 import register_vector

    conn = psycopg2.connect(
        host    = db.get("host",     "localhost"),
        port    = db.get("port",     5432),
        dbname  = db_name,
        user    = db.get("user",     "postgres"),
        password= os.environ.get("PGPASSWORD", "postgres"),
    )
    register_vector(conn)

    # Safety check: confirm this is not rag_poison
    with conn.cursor() as cur:
        cur.execute("SELECT current_database();")
        current = cur.fetchone()[0]
    if current == "rag_poison":
        print("[populate] ERROR: connected to rag_poison — aborting to protect original DB.")
        sys.exit(1)
    print(f"[populate] Connected to: {current}")

    # Clear existing data (safe: rag_poison_if is isolated)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks;")
        existing = cur.fetchone()[0]
    if existing > 0:
        print(f"[populate] {existing} existing rows found — clearing before re-populate...")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks;")
        conn.commit()

    # Load CUAD chunks
    chunks = _load_cuad_chunks(config)
    print(f"[populate] Loaded {len(chunks)} CUAD chunks. Embedding + inserting...")

    import ollama
    import tiktoken
    from tqdm import tqdm

    for chunk in tqdm(chunks, desc="  Embedding clean chunks", unit="chunk"):
        resp      = ollama.embed(model=config.embedding_model, input=chunk["document"])
        embedding = resp.embeddings[0]
        _insert(conn, chunk, embedding)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks WHERE is_original = TRUE;")
        n = cur.fetchone()[0]

    conn.close()
    print(f"[populate] Done. {n} clean chunks in {current} (is_original=TRUE).")


def _load_cuad_chunks(config: ExperimentConfig) -> list[dict]:
    import tiktoken
    from huggingface_hub import hf_hub_download

    chunking     = getattr(config, "chunking", {}) or {}
    enc          = tiktoken.get_encoding(chunking.get("tokenizer_encoding", "cl100k_base"))
    chunk_tokens = chunking.get("chunk_size_tokens", 300)
    overlap      = chunking.get("overlap_tokens",     50)
    max_chunks   = config.n_clean_chunks

    local_path = hf_hub_download(
        repo_id="theatticusproject/cuad",
        repo_type="dataset",
        filename="CUAD_v1/CUAD_v1.json",
    )
    with open(local_path, encoding="utf-8") as f:
        data = json.load(f)

    rng    = random.Random(config.seed)
    chunks: list[dict] = []

    for entry in data["data"]:
        context = entry["paragraphs"][0]["context"]
        if len(context) <= 200:
            continue
        tokens = enc.encode(context)
        idx, start = 0, 0
        while start < len(tokens):
            end  = min(start + chunk_tokens, len(tokens))
            text = enc.decode(tokens[start:end])
            if text.strip():
                chunks.append({
                    "chunk_id":    f"clean_{uuid.uuid4().hex[:8]}",
                    "document":    text,
                    "doc_id":      entry["title"],
                    "source":      "cuad",
                    "chunk_index": idx,
                })
                idx += 1
            start += chunk_tokens - overlap
        if len(chunks) >= max_chunks:
            break

    chunks = chunks[:max_chunks]
    rng.shuffle(chunks)
    return chunks


def _insert(conn, chunk: dict, embedding: list[float]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chunks
                (chunk_id, document, embedding, doc_id, source,
                 is_original, is_poison, chunk_index)
            VALUES (%s, %s, %s, %s, %s, TRUE, FALSE, %s)
            ON CONFLICT (chunk_id) DO NOTHING;
            """,
            (
                chunk["chunk_id"], chunk["document"], np.array(embedding),
                chunk["doc_id"],   chunk["source"],   chunk["chunk_index"],
            ),
        )
    conn.commit()


if __name__ == "__main__":
    main()
