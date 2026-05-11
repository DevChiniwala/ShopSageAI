"""Policy Search Tool - FAISS-based RAG for company policies."""
import os
from langchain_core.tools import tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from shopsage.config import FAISS_INDEX_PATH, EMBEDDING_MODEL, TOP_K_RESULTS, GOOGLE_API_KEY


def _load_faiss_index():
    """Load the FAISS index from disk."""
    if not os.path.exists(FAISS_INDEX_PATH):
        return None

    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=GOOGLE_API_KEY
    )
    return FAISS.load_local(
        FAISS_INDEX_PATH,
        embeddings,
        allow_dangerous_deserialization=True
    )


@tool
def policy_search(query: str) -> str:
    """
    Search company policies, guidelines, and information.

    Use this tool when the user asks about:
    - Return or refund policies
    - Shipping and delivery information
    - Privacy policy
    - Warranty information
    - Size guides
    - Customer support or contact info
    - Any company rules or guidelines

    Examples:
    - "What's your return policy?"
    - "How long does shipping take?"
    - "Do you have a warranty?"
    - "What's the size guide?"
    - "How can I contact support?"

    Args:
        query: The policy-related question from the user.

    Returns:
        Relevant policy information extracted from company documents.
    """
    vector_store = _load_faiss_index()
    if vector_store is None:
        return (
            "Policy database is not available. Please run "
            "'python scripts/init_db.py' to initialize it."
        )

    results = vector_store.similarity_search(query, k=TOP_K_RESULTS)

    if not results:
        return "No relevant policy information found for your query."

    policy_text = "\n\n".join(
        f"--- Policy Excerpt {i+1} ---\n{doc.page_content}"
        for i, doc in enumerate(results)
    )

    return f"Here is the relevant policy information:\n\n{policy_text}"
