from app.core.config import Settings
from app.models.document_embedding import DocumentEmbedding


def test_production_vector_dimension_matches_supported_emrank_dimension():
    assert DocumentEmbedding.__table__.c.embedding_vector.type.dim == 2560
    assert Settings(_env_file=None).document_embedding_dimensions == 2560
