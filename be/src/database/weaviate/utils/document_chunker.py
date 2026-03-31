from __future__ import annotations

from chonkie import RecursiveChunker  # pyright:ignore
from chonkie import RecursiveRules  # pyright:ignore


def chonk_text(
    full_text: str, max_chunk_size: int = 2048, min_characters_per_chunk=200
) -> list[str]:
    chunker = RecursiveChunker(
        tokenizer="character",
        chunk_size=max_chunk_size,
        rules=RecursiveRules(),
        min_characters_per_chunk=min_characters_per_chunk,
    )
    chunks = chunker.chunk(full_text)
    return [chunk.text for chunk in chunks]
