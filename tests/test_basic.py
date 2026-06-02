"""Basic FastAPI app smoke tests (lazy import so conftest mocks apply first)."""

import pytest
from fastapi import FastAPI


@pytest.fixture(scope="module")
def app_instance():
    """Load the app after conftest installs import stubs."""
    from app import app

    return app


@pytest.fixture(scope="module")
def client(app_instance):
    from starlette.testclient import TestClient

    with TestClient(app_instance) as test_client:
        yield test_client


def test_app_is_fastapi_instance(app_instance):
    """Verify that the imported app is a FastAPI instance."""
    assert isinstance(app_instance, FastAPI)


def test_health_check(client):
    """Test the root endpoint serves the chat UI."""
    response = client.get("/")
    assert response.status_code == 200
