from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RerankerModelSpec:
    """Who runs a reranking model and which model it is."""

    provider: str
    model: str


# The local reranker for this phase. It was trained on mMARCO, a multilingual
# version of the MS MARCO passage ranking data.
MMARCO_MINILM = RerankerModelSpec(
    provider="sentence_transformers",
    model="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
)
