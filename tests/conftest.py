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
    lc_existing = sys.modules.get("langchain_google_genai")
    if lc_existing is None or not hasattr(lc_existing, "GoogleGenerativeAIEmbeddings"):
        try:
            import importlib

            lc_mod = importlib.import_module("langchain_google_genai")
            if not hasattr(lc_mod, "GoogleGenerativeAIEmbeddings"):
                raise ImportError("incomplete langchain_google_genai")
        except ImportError:
            lc_mod = ModuleType("langchain_google_genai")
            lc_mod.ChatGoogleGenerativeAI = MagicMock
            lc_mod.GoogleGenerativeAIEmbeddings = MagicMock
            sys.modules["langchain_google_genai"] = lc_mod

    if "langchain_core.prompts" not in sys.modules:
        prompts = ModuleType("langchain_core.prompts")
        prompts.PromptTemplate = MagicMock
        sys.modules["langchain_core.prompts"] = prompts

    if "langchain_core.tools" not in sys.modules:
        tools = ModuleType("langchain_core.tools")
        tools.tool = lambda fn: fn
        sys.modules["langchain_core.tools"] = tools

    if "langchain_classic.chains" not in sys.modules:
        chains = ModuleType("langchain_classic.chains")
        chains.ConversationChain = MagicMock
        sys.modules["langchain_classic.chains"] = chains

    if "langchain_classic.memory" not in sys.modules:
        memory = ModuleType("langchain_classic.memory")
        memory.ConversationBufferMemory = MagicMock
        sys.modules["langchain_classic.memory"] = memory

    if "langchain_classic" not in sys.modules:
        classic = ModuleType("langchain_classic")
        classic.chains = sys.modules["langchain_classic.chains"]
        classic.memory = sys.modules["langchain_classic.memory"]
        sys.modules["langchain_classic"] = classic
    # Ensure parent packages exist for dotted modules.
    langgraph_pkg = sys.modules.get("langgraph")
    if langgraph_pkg is None:
        langgraph_pkg = ModuleType("langgraph")
        langgraph_pkg.__path__ = []
        sys.modules["langgraph"] = langgraph_pkg

    checkpoint_pkg = sys.modules.get("langgraph.checkpoint")
    if checkpoint_pkg is None:
        checkpoint_pkg = ModuleType("langgraph.checkpoint")
        checkpoint_pkg.__path__ = []
        sys.modules["langgraph.checkpoint"] = checkpoint_pkg
        setattr(langgraph_pkg, "checkpoint", checkpoint_pkg)

    if "langgraph.prebuilt" not in sys.modules:
        prebuilt = ModuleType("langgraph.prebuilt")
        prebuilt.create_react_agent = MagicMock(return_value=MagicMock())
        sys.modules["langgraph.prebuilt"] = prebuilt
        setattr(langgraph_pkg, "prebuilt", prebuilt)

    if "langgraph.checkpoint.memory" not in sys.modules:
        memory = ModuleType("langgraph.checkpoint.memory")
        memory.MemorySaver = MagicMock
        sys.modules["langgraph.checkpoint.memory"] = memory
        setattr(checkpoint_pkg, "memory", memory)


_install_google_genai_mock()
_install_langchain_mocks()
