from app.core.config import Settings


def test_database_url_normalizes_standard_postgresql_scheme_to_psycopg():
    settings = Settings(database_url="postgresql://user:pass@db.example/test")
    assert settings.database_url == "postgresql+psycopg://user:pass@db.example/test"


def test_database_url_preserves_explicit_psycopg_scheme():
    value = "postgresql+psycopg://user:pass@db.example/test"
    settings = Settings(database_url=value)
    assert settings.database_url == value


def test_local_keyword_embeddings_are_disabled_by_default():
    settings = Settings(database_url="postgresql+psycopg://user:pass@db.example/test")
    assert settings.keyword_local_embeddings_enabled is False
