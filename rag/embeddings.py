"""Embedding backends supporting Gemini embeddings and deterministic hash fallback."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Literal
import zlib

import numpy as np

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")


def l2_normalize_rows(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize a 2D float32 matrix row-wise."""
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    return (arr / norms).astype(np.float32)


class EmbeddingBackend:
    """Unified embedding generator for Gemini (`gemini-embedding-001`) and offline hash fallback."""

    def __init__(
        self,
        provider: Literal["gemini", "hash"],
        api_key: str = "",
        model_name: str = "gemini-embedding-001",
        dim: int = 768,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model_name = model_name
        self.dim = dim
        self._client = None

    def _get_genai_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def embed_texts(
        self,
        texts: list[str],
        task_type: Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"] = "RETRIEVAL_DOCUMENT",
        cancel_event: threading.Event | None = None,
    ) -> np.ndarray:
        """Embed a list of strings into L2-normalized float32 vectors of shape (N, dim)."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        if self.provider == "gemini":
            return self._embed_gemini(texts, task_type=task_type, cancel_event=cancel_event)
        return self._embed_hash(texts)

    def _sleep_cancelable(
        self, seconds: float, cancel_event: threading.Event | None
    ) -> None:
        if cancel_event is not None:
            if cancel_event.wait(seconds):
                raise InterruptedError("Embedding generation cancelled.")
        else:
            time.sleep(seconds)

    def _embed_gemini(
        self,
        texts: list[str],
        task_type: str,
        cancel_event: threading.Event | None = None,
    ) -> np.ndarray:
        from google.genai import types

        client = self._get_genai_client()
        vectors: list[list[float]] = []
        batch_size = 24
        window_items = 0
        window_start = time.monotonic()

        for start in range(0, len(texts), batch_size):
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Embedding generation cancelled.")

            batch = [t if t.strip() else " " for t in texts[start : start + batch_size]]
            # Pace under Google Free Tier 100 embed-items/minute limit
            if window_items > 0 and window_items + len(batch) > 80:
                elapsed = time.monotonic() - window_start
                wait_s = max(1.0, 62.0 - elapsed)
                logger.info(
                    "Pacing Gemini embeddings for %.1fs to stay within Free Tier RPM quota",
                    wait_s,
                )
                self._sleep_cancelable(wait_s, cancel_event)
                window_items = 0
                window_start = time.monotonic()

            contents = [
                types.Content(parts=[types.Part.from_text(text=item)]) for item in batch
            ]
            for attempt in range(2):
                try:
                    resp = client.models.embed_content(
                        model=self.model_name,
                        contents=contents,
                        config=types.EmbedContentConfig(
                            task_type=task_type,
                            output_dimensionality=self.dim,
                        ),
                    )
                    break
                except Exception as exc:
                    msg = str(exc)
                    if attempt == 0 and ("429" in msg or "RESOURCE_EXHAUSTED" in msg):
                        match = re.search(r"retry in (\d+(?:\.\d+)?)s", msg, re.I)
                        delay = float(match.group(1)) + 2.0 if match else 62.0
                        logger.warning(
                            "Gemini embedding rate-limited; retrying in %.1fs", delay
                        )
                        self._sleep_cancelable(min(delay, 70.0), cancel_event)
                        window_items = 0
                        window_start = time.monotonic()
                    else:
                        raise

            for emb in resp.embeddings:
                vectors.append(list(emb.values))
            window_items += len(batch)
        return l2_normalize_rows(np.array(vectors, dtype=np.float32))

    def _embed_hash(self, texts: list[str]) -> np.ndarray:
        """Deterministic signed feature hashing (unigrams, bigrams, char 4-grams)."""
        mat = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row_idx, text in enumerate(texts):
            tokens = _TOKEN_RE.findall(text.lower())
            for token in tokens:
                self._accumulate_feature(mat, row_idx, f"u:{token}", 1.5)
                if len(token) >= 4:
                    for i in range(len(token) - 3):
                        self._accumulate_feature(mat, row_idx, f"c:{token[i:i+4]}", 0.35)
            for i in range(len(tokens) - 1):
                self._accumulate_feature(mat, row_idx, f"b:{tokens[i]}_{tokens[i+1]}", 1.1)
        return l2_normalize_rows(mat)

    def _accumulate_feature(
        self, mat: np.ndarray, row_idx: int, feature: str, weight: float
    ) -> None:
        raw = feature.encode("utf-8")
        idx = zlib.crc32(raw) % self.dim
        sign = 1.0 if (zlib.adler32(raw) & 1) == 0 else -1.0
        mat[row_idx, idx] += sign * weight
