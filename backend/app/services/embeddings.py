from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from os import getenv
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"


def embedding_model() -> str:
    return (getenv("OPENAI_EMBED_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()


def embedding_enabled() -> bool:
    return bool((getenv("OPENAI_API_KEY") or "").strip())


@dataclass
class EmbeddingRuntimeStatus:
    enabled: bool
    model: str
    provider: str = "openai"
    purpose: str = "semantic matching for metric descriptions, captions, and analytics context"
    notes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def embedding_status() -> EmbeddingRuntimeStatus:
    notes = [
        "Use SQL for exact metric values, counts, dates, and arithmetic.",
        "Use embeddings only to match natural-language metric questions to metric context and related post/media text.",
    ]
    if not embedding_enabled():
        notes.append("OPENAI_API_KEY is not set, so runtime embedding calls are disabled.")
    return EmbeddingRuntimeStatus(enabled=embedding_enabled(), model=embedding_model(), notes=notes)


def content_hash(text_value: str) -> str:
    normalized = " ".join(str(text_value or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def embed_texts(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to create embeddings.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(model=model or embedding_model(), input=texts)
    ordered = sorted(response.data, key=lambda item: item.index)
    return [list(item.embedding) for item in ordered]


def vector_to_json(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def vector_from_json(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        return [float(item) for item in value]
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return [float(item) for item in parsed]
    except Exception:
        return []
    return []


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
