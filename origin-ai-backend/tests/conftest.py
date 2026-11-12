"""Pytest configuration and test fixtures."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure test settings
os.environ["ENVIRONMENT"] = "testing"
os.environ["DEBUG"] = "true"

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.tools import tool_registry, init_tools


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Configures isolated test workspace and sqlite in-memory / temporary test database."""
    temp_workspace = Path(tempfile.mkdtemp(prefix="origin_test_workspace_"))
    settings.WORKSPACE_DIR = temp_workspace

    test_db_file = temp_workspace / "test_origin.db"
    test_db_url = f"sqlite:///{test_db_file}"
    settings.DATABASE_URL = test_db_url

    test_engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    init_tools()

    yield

    # Teardown
    shutil.rmtree(temp_workspace, ignore_errors=True)


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app) as test_client:
        yield test_client

