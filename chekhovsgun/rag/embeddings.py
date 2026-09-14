"""Pluggable embedding backends.

The default backend is deliberately dependency-free: ChekhovsGun must produce
useful results the moment it is cloned, with no API key and no model download.
The hashed backend is weaker than a neural encoder, which is exactly why
retrieval fuses it with BM25 (see :mod:`chekhovsgun.rag.retriever`) — the two
fail in different places. Point ``embedding.backend`` at ``openai`` or
``sentence-transformers`` for a real semantic upgrade with no other changes.
"""

from __future__ import annotations

import hashlib
import logging
import math
from abc import ABC, abstractmethod
from collections import Counter

import numpy as np

from ..config import EmbeddingConfig
from .text import tokenize

log = logging.getLogger(__name__)


class Embedder(ABC):
    """Maps text to unit-length float32 vectors."""

    name: str = "base"
    dimensions: int = 512

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an ``(len(texts), dimensions)`` float32 matrix, L2-normalised."""

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    @property
    def signature(self) -> str:
        """Identifies the vector space. Changing it invalidates the index."""
        return f"{self.name}:{self.dimensions}"


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.maximum(norms, 1e-9, out=norms)
    return (matrix / norms).astype(np.float32, copy=False)


class HashingEmbedder(Embedder):
    """Signed feature hashing over the shared CJK-aware tokenizer.

    Two tricks keep this usable despite having no learned semantics:
    * sublinear term frequency (``1 + log tf``) so a repeated filler word cannot
      swamp the vector;
    * a signed hash (``+1``/``-1`` per feature) so colliding features cancel out
      on average instead of always reinforcing each other.
    """

    name = "local-hash"

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = max(64, int(dimensions))

    def _index_and_sign(self, token: str) -> tuple[int, float]:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dimensions, 1.0 if (value >> 63) & 1 else -1.0

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            counts = Counter(tokenize(text))
            if not counts:
                continue
            for token, count in counts.items():
                index, sign = self._index_and_sign(token)
                # Longer tokens (CJK bigrams, real words) are more specific than
                # single characters, so let them carry more weight.
                specificity = 1.0 + 0.35 * min(len(token), 4)
                matrix[row, index] += sign * (1.0 + math.log(count)) * specificity
        return _l2_normalize(matrix)


class OpenAIEmbedder(Embedder):
    """Any OpenAI-compatible ``/embeddings`` endpoint.

    Works unchanged against OpenAI, DashScope, SiliconFlow, Together, vLLM and
    Ollama — only ``base_url`` and ``model`` differ.
    """

    name = "openai"

    def __init__(self, config: EmbeddingConfig) -> None:
        import httpx  # imported lazily so the local backend needs no network stack

        self.model = config.model or "text-embedding-3-small"
        self.batch_size = max(1, config.batch_size)
        base = (config.base_url or "https://api.openai.com/v1").rstrip("/")
        self._url = f"{base}/embeddings"
        self._client = httpx.Client(
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
        )
        self.dimensions = config.dimensions or 1536

    @property
    def signature(self) -> str:
        return f"openai:{self.model}:{self.dimensions}"

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [t if t.strip() else " " for t in texts[start : start + self.batch_size]]
            payload: dict = {"model": self.model, "input": batch}
            response = self._client.post(self._url, json=payload)
            response.raise_for_status()
            data = response.json()["data"]
            data.sort(key=lambda row: row.get("index", 0))
            vectors.extend(row["embedding"] for row in data)
        matrix = np.asarray(vectors, dtype=np.float32)
        self.dimensions = matrix.shape[1]
        return _l2_normalize(matrix)


class SentenceTransformerEmbedder(Embedder):
    """Local neural encoder. Best quality/privacy trade-off if you can spare the RAM."""

    name = "sentence-transformers"

    def __init__(self, config: EmbeddingConfig) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model_name = config.model or "paraphrase-multilingual-MiniLM-L12-v2"
        self._model = SentenceTransformer(self.model_name)
        self.dimensions = int(self._model.get_sentence_embedding_dimension())
        self.batch_size = max(1, config.batch_size)

    @property
    def signature(self) -> str:
        return f"st:{self.model_name}:{self.dimensions}"

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        matrix = self._model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return _l2_normalize(np.asarray(matrix, dtype=np.float32))


def get_embedder(config: EmbeddingConfig) -> Embedder:
    """Build the configured embedder, falling back to the local one on failure."""
    backend = (config.backend or "local").strip().lower()
    try:
        if backend in {"openai", "openai-compatible", "api"}:
            if not config.api_key:
                raise ValueError("embedding backend 'openai' needs an API key")
            return OpenAIEmbedder(config)
        if backend in {"sentence-transformers", "st", "sbert"}:
            return SentenceTransformerEmbedder(config)
    except Exception as exc:  # pragma: no cover - depends on the environment
        log.warning("embedding backend %r unavailable (%s); falling back to local", backend, exc)
    return HashingEmbedder(config.dimensions)
