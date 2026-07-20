import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["USE_FIXTURES"] = "true"

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
