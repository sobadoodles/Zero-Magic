def test_rank_chunks_by_vector_similarity():
    from app.semantic_search import rank_chunks

    chunks = [
        {"source": "brief.pdf", "page": 1, "text": "A profile setting."},
        {"source": "brief.pdf", "page": 2, "text": "Send a reminder."},
        {"source": "brief.pdf", "page": 3, "text": "Choose a due date."},
    ]

    # Small example vectors make the ranking predictable.
    vectors = [
        [1.0, 0.0],
        [0.0, 1.0],
        [0.6, 0.8],
    ]

    results = rank_chunks(chunks, vectors, [0.0, 1.0], limit=2)

    assert results == [chunks[1], chunks[2]]

def test_saved_index_can_be_loaded_and_searched(tmp_path):
    from app.semantic_search import load_index, rank_chunks, save_index

    chunks = [
        {"source": "brief.pdf", "page": 1, "text": "A profile setting."},
        {"source": "brief.pdf", "page": 2, "text": "Send a reminder."},
    ]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    index_file = tmp_path / "index.json"

    save_index(index_file, chunks, vectors, model_name="test-model")
    loaded = load_index(index_file)

    assert loaded["model"] == "test-model"
    assert loaded["chunks"] == chunks
    assert loaded["vectors"] == vectors
    assert rank_chunks(
        loaded["chunks"], loaded["vectors"], [0.0, 1.0], limit=1
    ) == [chunks[1]]


def test_create_index_uses_model_and_keeps_chunk_details(tmp_path):
    from app.semantic_search import load_index
    from scripts.index_documents import MODEL_NAME, create_index

    chunks = [
        {"source": "brief.pdf", "page": 2, "text": "Send a reminder."},
    ]

    class FakeModel:
        def embed(self, texts):
            assert texts == ["Send a reminder."]
            return [[0.0, 1.0]]

    index_file = tmp_path / "index.json"

    create_index(chunks, index_file, FakeModel())
    loaded = load_index(index_file)

    assert loaded["model"] == MODEL_NAME
    assert loaded["chunks"] == chunks
    assert loaded["vectors"] == [[0.0, 1.0]]


def test_search_index_embeds_question_and_ranks_saved_chunks():
    from scripts.search_semantic import search_index

    chunks = [
        {"source": "brief.pdf", "page": 1, "text": "A profile setting."},
        {"source": "brief.pdf", "page": 2, "text": "Send a reminder."},
    ]
    index = {
        "chunks": chunks,
        "vectors": [[1.0, 0.0], [0.0, 1.0]],
    }

    class FakeModel:
        def embed(self, texts):
            assert texts == ["When is the reminder?"]
            return iter([[0.0, 1.0]])

    results = search_index(index, "When is the reminder?", FakeModel(), limit=1)

    assert results == [chunks[1]]