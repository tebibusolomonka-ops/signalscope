from signalscope.db.autogenerate import include_object


def test_only_the_e5_index_is_left_out() -> None:
    assert include_object(None, "ix_chunk_embeddings_e5_small_hnsw", "index", True, None) is False
    assert include_object(None, "ix_embedding_jobs_status_available_at", "index", True, None)
    assert include_object(None, "chunk_embeddings", "table", True, None)
    assert include_object(None, "embedding", "column", False, None)
