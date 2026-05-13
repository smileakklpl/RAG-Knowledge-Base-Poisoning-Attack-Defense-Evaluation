from dataclasses import dataclass, field, fields
from typing import Dict, List
import yaml


@dataclass
class ExperimentConfig:
    # Models
    attacker_model:    str
    target_model:      str
    embedding_model:   str
    # Evaluation
    evaluation_mode:   str         = "human"
    # Experiment parameters
    top_k:             List[int]   = field(default_factory=lambda: [5])
    poison_ratio:      List[float] = field(default_factory=lambda: [0.05])
    seed:              int         = 42
    # Phase 1 thresholds
    max_iter:          int         = 4
    sim_threshold:     float       = 0.75
    stealth_threshold: float       = 0.60
    payload_threshold: float       = 0.70
    # Phase 2: clean chunks to load from CUAD (1 = fast test, 500+ = full experiment)
    n_clean_chunks:    int         = 1
    # Phase 2: max poison chunks to inject (None = use all from Phase 1)
    n_poison_chunks:   int         = None
    # Vector DB connection (password via PGPASSWORD env var)
    vector_db:         Dict        = field(default_factory=lambda: {
        "host":     "localhost",
        "port":     5432,
        "database": "rag_poison",
        "user":     "postgres",
        "table":    "chunks",
    })

    @classmethod
    def from_yaml(cls, path: str) -> "ExperimentConfig":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
