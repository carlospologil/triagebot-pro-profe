import os

# app.main crea `app` al importarse y necesita SECRET_KEY.
os.environ.setdefault("SECRET_KEY", "clave-solo-para-tests")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        secret_key="clave-solo-para-tests",
        database_path=str(tmp_path / "test.db"),
    )


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings))
