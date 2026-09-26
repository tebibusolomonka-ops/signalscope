"""Runs a retrieval dataset through SignalScope search and scores the results."""

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.hybrid_service import candidate_count, fuse
from signalscope.domain.search.repository import (
    MAX_CANDIDATE_LIMIT,
    PUBLIC_SEARCH_LIMIT,
    SearchRepository,
)
from signalscope.domain.search.vector_repository import VectorSearchRepository
from signalscope.embeddings.provider import EmbeddingInputRole, EmbeddingProvider, embed
from signalscope.evaluation.corpus import (
    DatasetChunks,
    EvaluationCorpus,
    chunk_dataset,
    evaluation_corpus,
)
from signalscope.evaluation.dataset import RetrievalDataset
from signalscope.evaluation.metrics import MetricsSummary, QueryMetrics, evaluate_query, summarize

DEFAULT_KS = (1, 5, 10)
# Search returns chunks, and several can come from one document. Asking for
# the most candidates leaves enough distinct documents for the largest k.
SEARCH_DEPTH = MAX_CANDIDATE_LIMIT

Timer = Callable[[], float]


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Query times in milliseconds."""

    mean_ms: float
    p50_ms: float
    p95_ms: float


@dataclass(frozen=True, slots=True)
class RetrievalReport:
    mode: str
    dataset: str
    ks: tuple[int, ...]
    metrics: MetricsSummary
    queries: tuple[QueryMetrics, ...]
    latency: LatencySummary


def check_ks(ks: Sequence[int]) -> tuple[int, ...]:
    """Return the k values sorted and without repeats, or raise ValueError."""
    if not ks:
        raise ValueError("at least one k is needed")
    for k in ks:
        if not 1 <= k <= PUBLIC_SEARCH_LIMIT:
            raise ValueError(f"k must be between 1 and {PUBLIC_SEARCH_LIMIT}, got {k}")
    return tuple(sorted(set(ks)))


def summarize_latency(seconds: Sequence[float]) -> LatencySummary:
    if not seconds:
        raise ValueError("at least one time is needed")
    ordered = sorted(seconds)
    return LatencySummary(
        mean_ms=sum(ordered) / len(ordered) * 1000,
        p50_ms=_percentile(ordered, 50) * 1000,
        p95_ms=_percentile(ordered, 95) * 1000,
    )


class RankedQueries:
    """Collects the ranked document keys and the time of each query."""

    def __init__(self, dataset: RetrievalDataset, ks: tuple[int, ...]) -> None:
        self.dataset = dataset
        self.ks = ks
        self.results: list[QueryMetrics] = []
        self.seconds: list[float] = []

    def add(self, query_index: int, ranked_keys: list[str], seconds: float) -> None:
        query = self.dataset.queries[query_index]
        self.results.append(
            evaluate_query(query.key, ranked_keys, query.relevant_documents, self.ks)
        )
        self.seconds.append(seconds)

    def report(self, mode: str) -> RetrievalReport:
        return RetrievalReport(
            mode=mode,
            dataset=self.dataset.name,
            ks=self.ks,
            metrics=summarize(self.results, self.ks),
            queries=tuple(self.results),
            latency=summarize_latency(self.seconds),
        )


async def evaluate_lexical(
    session_factory: async_sessionmaker[AsyncSession],
    dataset: RetrievalDataset,
    ks: Sequence[int] = DEFAULT_KS,
    timer: Timer = time.perf_counter,
) -> RetrievalReport:
    """Score PostgreSQL full text search on the dataset.

    The dataset is loaded into a temporary corpus that is rolled back at the end.
    """
    checked = check_ks(ks)
    ranked = RankedQueries(dataset, checked)
    async with evaluation_corpus(session_factory, dataset, chunk_dataset(dataset)) as (
        session,
        corpus,
    ):
        repository = SearchRepository(session)
        for index, query in enumerate(dataset.queries):
            started = timer()
            results = await repository.search(
                query.text, limit=SEARCH_DEPTH, source_id=corpus.source_id
            )
            elapsed = timer() - started
            keys = corpus.keys_of([result.document_id for result in results])
            ranked.add(index, keys, elapsed)
    return ranked.report("lexical")


@dataclass(frozen=True, slots=True)
class PreparedVectors:
    """Everything the model has to embed for one run, made before the database work."""

    chunks: dict[str, list[TextChunk]]
    # One vector per chunk, by (document key, chunk position).
    passages: dict[tuple[str, int], list[float]]
    # One vector per query, in dataset order.
    queries: list[list[float]]


async def prepare_vectors(
    provider: EmbeddingProvider, dataset: RetrievalDataset
) -> PreparedVectors:
    """Embed every chunk as a passage and every query as a query.

    This runs the model, which can be slow, so it happens before the
    evaluation transaction opens.
    """
    chunks = chunk_dataset(dataset)
    places = [(key, chunk.position) for key, items in chunks.items() for chunk in items]
    texts = [chunk.text for items in chunks.values() for chunk in items]
    passage_vectors = await embed(provider, texts, EmbeddingInputRole.PASSAGE)
    query_vectors = await embed(
        provider, [query.text for query in dataset.queries], EmbeddingInputRole.QUERY
    )
    return PreparedVectors(chunks, dict(zip(places, passage_vectors, strict=True)), query_vectors)


async def evaluate_semantic(
    session_factory: async_sessionmaker[AsyncSession],
    dataset: RetrievalDataset,
    provider: EmbeddingProvider,
    ks: Sequence[int] = DEFAULT_KS,
    timer: Timer = time.perf_counter,
) -> RetrievalReport:
    """Score vector search with provider on the dataset.

    A document counts as found at the place of its best chunk. The timings
    cover the database search only, because the queries are embedded first.
    """
    checked = check_ks(ks)
    vectors = await prepare_vectors(provider, dataset)
    ranked = RankedQueries(dataset, checked)
    async with evaluation_corpus(session_factory, dataset, vectors.chunks) as (session, corpus):
        await add_embeddings(session, corpus, vectors.chunks, vectors.passages, provider)
        repository = VectorSearchRepository(session)
        for index, query_vector in enumerate(vectors.queries):
            started = timer()
            results = await repository.search(
                query_vector,
                provider=provider.provider_name,
                model=provider.model_name,
                dimensions=provider.dimensions,
                limit=SEARCH_DEPTH,
                source_id=corpus.source_id,
            )
            elapsed = timer() - started
            ranked.add(index, corpus.keys_of([result.document_id for result in results]), elapsed)
    return ranked.report("semantic")


async def evaluate_hybrid(
    session_factory: async_sessionmaker[AsyncSession],
    dataset: RetrievalDataset,
    provider: EmbeddingProvider,
    ks: Sequence[int] = DEFAULT_KS,
    timer: Timer = time.perf_counter,
) -> RetrievalReport:
    """Score hybrid search, with the same candidates and fusion as the API.

    Each query collects full text and vector candidates for the largest public
    limit and merges them with the real Reciprocal Rank Fusion code. A document
    counts at the place of its best chunk. The timings cover both searches and
    the fusion, not the query embedding.
    """
    checked = check_ks(ks)
    vectors = await prepare_vectors(provider, dataset)
    ranked = RankedQueries(dataset, checked)
    candidates = candidate_count(PUBLIC_SEARCH_LIMIT)
    async with evaluation_corpus(session_factory, dataset, vectors.chunks) as (session, corpus):
        await add_embeddings(session, corpus, vectors.chunks, vectors.passages, provider)
        lexical = SearchRepository(session)
        nearest = VectorSearchRepository(session)
        for index, (query, query_vector) in enumerate(
            zip(dataset.queries, vectors.queries, strict=True)
        ):
            started = timer()
            lexical_results = await lexical.search(
                query.text, limit=candidates, source_id=corpus.source_id
            )
            vector_results = await nearest.search(
                query_vector,
                provider=provider.provider_name,
                model=provider.model_name,
                dimensions=provider.dimensions,
                limit=candidates,
                source_id=corpus.source_id,
            )
            fused = fuse(lexical_results, vector_results, PUBLIC_SEARCH_LIMIT)
            elapsed = timer() - started
            ranked.add(index, corpus.keys_of([result.document_id for result in fused]), elapsed)
    return ranked.report("hybrid")


async def add_embeddings(
    session: AsyncSession,
    corpus: EvaluationCorpus,
    chunks: DatasetChunks,
    passages: dict[tuple[str, int], list[float]],
    provider: EmbeddingProvider,
) -> None:
    """Store the prepared chunk vectors in the evaluation transaction."""
    session.add_all(
        ChunkEmbedding(
            chunk_id=corpus.chunk_ids[(key, chunk.position)],
            provider=provider.provider_name,
            model=provider.model_name,
            dimensions=provider.dimensions,
            chunk_text_hash=chunk.text_hash,
            embedding=passages[(key, chunk.position)],
        )
        for key, items in chunks.items()
        for chunk in items
    )
    await session.flush()


def _percentile(ordered: list[float], percent: float) -> float:
    """Linear interpolation between the closest ranks, as numpy does by default."""
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
