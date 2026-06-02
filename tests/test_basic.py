import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

def test_app_is_fastapi_instance():
    """Verify that the imported app is a FastAPI instance."""
    assert isinstance(app, FastAPI)

def test_health_check():
    """Test the root/health check endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    # Add additional assertions here based on expected JSON output if needed
