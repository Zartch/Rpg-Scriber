"""VectorIndex — in-RAM cosine-similarity index backed by SQLite embeddings."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from rag_lib.store import Database


class VectorIndex:
    """Lazy-loading in-RAM vector index for one db_path.

    Call ensure_loaded(db) before search(). Subsequent calls to ensure_loaded
    are incremental: only rows with id > self._max_id are fetched.
    """

    def __init__(self) -> None:
        self._matrix: np.ndarray | None = None   # shape (N, dim), float32
        self._chunk_ids: list[int] = []
        self._manual_ids: list[int] = []
        self._max_id: int = 0

    async def ensure_loaded(self, db: Database) -> None:
        rows = await db.embeddings.load_all(min_id=self._max_id)
        if not rows:
            return
        new_vecs = [
            np.frombuffer(r["vector"], dtype=np.float32)
            for r in rows
        ]
        block = np.stack(new_vecs)
        self._matrix = (
            np.vstack([self._matrix, block])
            if self._matrix is not None else block
        )
        self._chunk_ids.extend(r["chunk_id"] for r in rows)
        self._manual_ids.extend(r["manual_id"] for r in rows)
        self._max_id = rows[-1]["id"]

    def search(
        self,
        query_vec: list[float],
        *,
        k: int,
        threshold: float | None,
        manual_ids: list[int] | None,
    ) -> list[tuple[int, float]]:
        """Return list of (chunk_id, score) sorted by descending cosine similarity."""
        if self._matrix is None or not self._chunk_ids:
            return []

        q = np.array(query_vec, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm < 1e-10:
            return []
        q = q / q_norm

        if manual_ids is not None:
            manual_set = set(manual_ids)
            mask = np.array([mid in manual_set for mid in self._manual_ids])
            mat = self._matrix[mask]
            cids = [cid for cid, ok in zip(self._chunk_ids, mask) if ok]
        else:
            mat = self._matrix
            cids = self._chunk_ids

        if len(mat) == 0:
            return []

        norms = np.linalg.norm(mat, axis=1) + 1e-10
        scores = (mat @ q) / norms

        top_k = min(k, len(scores))
        idx = np.argsort(scores, kind="stable")[::-1][:top_k]
        results = [(cids[i], float(scores[i])) for i in idx]

        if threshold is not None:
            results = [(cid, s) for cid, s in results if s >= threshold]
        return results
