"""Runs a retrieval dataset through SignalScope search and scores the results."""

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.hybrid_service import HybridSearchResult, candidate_count, fuse
from signalscope.domain.search.repository import (
    MAX_CANDIDATE_LIMIT,
    PUBLIC_SEARCH_LIMIT,
    SearchRepository,
)
from signalscope.domain.search.reranked_service import rerank_candidate_count
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
from signalscope.reranking.provider import RerankerProvider, rerank_scores

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
    # Search time per query.
    latency: LatencySummary
    # Reranker time per query, for the reranked mode only.
    reranking_latency: LatencySummary | None = None


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

    def report(
        self, mode: str, reranking_seconds: Sequence[float] | None = None
    ) -> RetrievalReport:
        return RetrievalReport(
            mode=mode,
            dataset=self.dataset.name,
            ks=self.ks,
            metrics=summarize(self.results, self.ks),
            queries=tuple(self.results),
            latency=summarize_latency(self.seconds),
            reranking_latency=(
                None if reranking_seconds is None else summarize_latency(reranking_seconds)
            ),
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
    async with evaluation_corpus(session_factory, dataset, vectors.chunks) as (session, corpus):
        await add_embeddings(session, corpus, vectors.chunks, vectors.passages, provider)
        lexical = SearchRepository(session)
        nearest = VectorSearchRepository(session)
        for index, (query, query_vector) in enumerate(
            zip(dataset.queries, vectors.queries, strict=True)
        ):
            started = timer()
            fused = await _hybrid_candidates(
                lexical, nearest, query.text, query_vector, provider, corpus, PUBLIC_SEARCH_LIMIT
            )
            elapsed = timer() - started
            ranked.add(index, corpus.keys_of([result.document_id for result in fused]), elapsed)
    return ranked.report("hybrid")


async def evaluate_reranked(
    session_factory: async_sessionmaker[AsyncSession],
    dataset: RetrievalDataset,
    provider: EmbeddingProvider,
    reranker: RerankerProvider,
    ks: Sequence[int] = DEFAULT_KS,
    timer: Timer = time.perf_counter,
) -> RetrievalReport:
    """Score hybrid search reordered by reranker, as the reranked search API does.

    Each query collects the hybrid candidates the API would rerank for the
    largest k. The transaction is closed before the reranker runs, and its time
    is reported apart from the search time. A document counts at the place of
    its best chunk after reranking.
    """
    checked = check_ks(ks)
    vectors = await prepare_vectors(provider, dataset)
    texts = {
        (key, chunk.position): chunk.text
        for key, items in vectors.chunks.items()
        for chunk in items
    }
    search_seconds: list[float] = []
    # For each query: (document key, chunk text) of every candidate, in hybrid order.
    candidates: list[list[tuple[str, str]]] = []
    async with evaluation_corpus(session_factory, dataset, vectors.chunks) as (session, corpus):
        await add_embeddings(session, corpus, vectors.chunks, vectors.passages, provider)
        places = {chunk_id: place for place, chunk_id in corpus.chunk_ids.items()}
        lexical = SearchRepository(session)
        nearest = VectorSearchRepository(session)
        for query, query_vector in zip(dataset.queries, vectors.queries, strict=True):
            started = timer()
            fused = await _hybrid_candidates(
                lexical,
                nearest,
                query.text,
                query_vector,
                provider,
                corpus,
                rerank_candidate_count(max(checked)),
            )
            search_seconds.append(timer() - started)
            candidates.append(
                [(places[result.chunk_id][0], texts[places[result.chunk_id]]) for result in fused]
            )

    ranked = RankedQueries(dataset, checked)
    reranking_seconds = []
    for index, (query, found) in enumerate(zip(dataset.queries, candidates, strict=True)):
        started = timer()
        scores = await rerank_scores(reranker, query.text, [text for _, text in found])
        reranking_seconds.append(timer() - started)
        # sorted() is stable, so equal scores keep the hybrid order.
        order = sorted(range(len(found)), key=lambda position: -scores[position])
        ranked.add(index, [found[position][0] for position in order], search_seconds[index])
    return ranked.report("reranked", reranking_seconds)


async def _hybrid_candidates(
    lexical: SearchRepository,
    nearest: VectorSearchRepository,
    text: str,
    vector: list[float],
    provider: EmbeddingProvider,
    corpus: EvaluationCorpus,
    limit: int,
) -> list[HybridSearchResult]:
    """Run both searches and fuse them, as HybridSearchService does."""
    candidates = candidate_count(limit)
    lexical_results = await lexical.search(text, limit=candidates, source_id=corpus.source_id)
    vector_results = await nearest.search(
        vector,
        provider=provider.provider_name,
        model=provider.model_name,
        dimensions=provider.dimensions,
        limit=candidates,
        source_id=corpus.source_id,
    )
    return fuse(lexical_results, vector_results, limit)


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
