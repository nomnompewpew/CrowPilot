from __future__ import annotations

from typing import List


def split_into_chunks(text: str, chunk_size: int, overlap: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    if chunk_size <= 0:
        return [text]

    overlap = max(0, min(overlap, chunk_size - 1)) if chunk_size > 1 else 0
    chunks: List[str] = []

    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == length:
            break
        start = end - overlap

    return chunks
