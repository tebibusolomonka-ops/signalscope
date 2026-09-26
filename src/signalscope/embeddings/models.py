from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmbeddingModelSpec:
    """Who runs an embedding model, which model it is and how long its vectors are."""

    provider: str
    model: str
    dimensions: int


# The local model for this phase. It is multilingual and made for retrieval.
MULTILINGUAL_E5_SMALL = EmbeddingModelSpec(
    provider="sentence_transformers",
    model="intfloat/multilingual-e5-small",
    dimensions=384,
)
