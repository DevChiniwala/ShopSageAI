"""
Pytest configuration — ensures project root is in sys.path and mocks Google GenAI
when the real SDK is unavailable (CI / minimal installs).
"""
import sys
import os
from types import ModuleType
from unittest.mock import MagicMock

# Add project root to path so 'shopsage' package can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _install_google_genai_mock() -> None:
    """Provide a minimal google.genai stub so app/router imports succeed in CI."""
    try:
        from google import genai  # noqa: F401
        return
    except ImportError:
        pass

    google_pkg = sys.modules.get("google")
    if google_pkg is None:
        google_pkg = ModuleType("google")
        google_pkg.__path__ = []  # namespace package
        sys.modules["google"] = google_pkg

    genai_mod = ModuleType("google.genai")
    mock_client = MagicMock()
    mock_client.models.embed_content.return_value = MagicMock(
        embeddings=[MagicMock(values=[0.0] * 8)]
    )
    genai_mod.Client = MagicMock(return_value=mock_client)
    sys.modules["google.genai"] = genai_mod
    google_pkg.genai = genai_mod


def _install_langchain_mocks() -> None:
    """Stub LangChain / LangGraph so agent and API router imports succeed in CI."""
    if "langchain_google_genai" not in sys.modules:
        lc_mod = ModuleType("langchain_google_genai")
        lc_mod.ChatGoogleGenerativeAI = MagicMock
        sys.modules["langchain_google_genai"] = lc_mod

    if "langgraph.prebuilt" not in sys.modules:
        prebuilt = ModuleType("langgraph.prebuilt")
        prebuilt.create_react_agent = MagicMock(return_value=MagicMock())
        sys.modules["langgraph.prebuilt"] = prebuilt

    if "langgraph.checkpoint.memory" not in sys.modules:
        memory = ModuleType("langgraph.checkpoint.memory")
        memory.MemorySaver = MagicMock
        sys.modules["langgraph.checkpoint.memory"] = memory


_install_google_genai_mock()
_install_langchain_mocks()
