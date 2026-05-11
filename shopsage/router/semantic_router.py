"""
Semantic Router - Classifies user queries using embedding-based cosine similarity.

Uses Google Generative AI embeddings to compute similarity between
user queries and pre-defined route utterances, routing to either
'shopping' or 'chitchat' handlers.
"""
import numpy as np
from google import genai
from shopsage.config import GOOGLE_API_KEY

# Initialize the Google GenAI client
_client = genai.Client(api_key=GOOGLE_API_KEY)

# ─── Route Definitions ─────────────────────────────────────────────────

ROUTES = {
    "shopping": [
        "Show me red shirts",
        "What jackets do you have?",
        "I'm looking for blue dresses",
        "Do you have Nike shoes?",
        "Products under 2000 rupees",
        "What's available in size M?",
        "Compare these two products",
        "Which is the best value shirt?",
        "Show me women's clothing",
        "I need a formal shirt for men",
        "What brands do you carry?",
        "Do you have this in stock?",
        "What's the price of this item?",
        "Find me cotton t-shirts",
        "Recommend something for summer",
        "What are your cheapest options?",
        "Show me premium brands",
        "I want to buy a jacket",
        "Any discounts on shoes?",
        "What materials are available?",
        "What's your return policy?",
        "How long does shipping take?",
        "Do you offer warranties?",
        "What's the size guide?",
        "How can I contact support?",
        "What are the delivery charges?",
        "Can I return this product?",
        "What's your privacy policy?",
        "Do you ship internationally?",
        "What payment methods do you accept?",
    ],
    "chitchat": [
        "Hello!",
        "How are you?",
        "What's your name?",
        "Tell me a joke",
        "What's the weather like?",
        "Good morning",
        "Thanks for your help",
        "Who created you?",
        "What can you do?",
        "Tell me about yourself",
        "How's it going?",
        "Have a nice day",
        "You're awesome",
        "I'm bored",
        "What's the meaning of life?",
        "Tell me something interesting",
        "Goodbye",
        "See you later",
        "Nice talking to you",
        "What's up?",
    ],
}

# ─── Embedding Cache ───────────────────────────────────────────────────

_route_embeddings: dict[str, np.ndarray] | None = None


def _embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of texts using Google's embedding model."""
    result = _client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=texts,
    )
    return np.array([e.values for e in result.embeddings])


def _embed_query(text: str) -> np.ndarray:
    """Embed a single query text."""
    result = _client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=text,
    )
    return np.array(result.embeddings[0].values)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between vector a and matrix b."""
    a_norm = a / (np.linalg.norm(a) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)
    return np.dot(b_norm, a_norm)


def _get_route_embeddings() -> dict[str, np.ndarray]:
    """Lazy-initialize route embeddings (computed once, cached in memory)."""
    global _route_embeddings

    if _route_embeddings is None:
        print("[Router] Computing route embeddings (one-time)...")
        _route_embeddings = {}
        for route_name, utterances in ROUTES.items():
            _route_embeddings[route_name] = _embed_texts(utterances)
        print("[Router] Route embeddings cached ✓")

    return _route_embeddings


# ─── Public API ────────────────────────────────────────────────────────

SCORE_THRESHOLD = 0.75


def classify_query(text: str) -> str:
    """
    Classify a user query as either 'shopping' or 'chitchat'.

    Uses cosine similarity between the query embedding and
    pre-computed route utterance embeddings.

    Args:
        text: The user's input query.

    Returns:
        'shopping' if the query is product/policy related,
        'chitchat' if it's general conversation,
        'chitchat' as fallback if no route matches confidently.
    """
    try:
        route_embs = _get_route_embeddings()
        query_emb = _embed_query(text)

        best_route = "chitchat"
        best_score = -1.0

        for route_name, emb_matrix in route_embs.items():
            similarities = _cosine_similarity(query_emb, emb_matrix)
            max_score = float(np.max(similarities))

            if max_score > best_score:
                best_score = max_score
                best_route = route_name

        print(f"[Router] Query: '{text[:50]}...' → {best_route} (score: {best_score:.3f})")

        if best_score < SCORE_THRESHOLD:
            return "chitchat"

        return best_route

    except Exception as e:
        print(f"[Router] Classification error: {e}")
        return "chitchat"
