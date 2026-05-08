"""
Semantic Router - Classifies user queries using embedding-based cosine similarity.

Uses the semantic-router library with Google Generative AI embeddings
to route queries to either 'shopping' or 'chitchat' handlers.
"""

import os
from typing import List
from semantic_router import Route, RouteLayer
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from shopsage.config import EMBEDDING_MODEL, GOOGLE_API_KEY


class GoogleGenAIEncoder:
    """Wrapper to make GoogleGenerativeAIEmbeddings compatible with semantic-router."""

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self.client = GoogleGenerativeAIEmbeddings(
            model=model_name, google_api_key=GOOGLE_API_KEY
        )

    def __call__(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts and return their vector representations."""
        return self.client.embed_documents(texts)


# ─── Route Definitions ─────────────────────────────────────────────────

shopping_route = Route(
    name="shopping",
    utterances=[
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
)

chitchat_route = Route(
    name="chitchat",
    utterances=[
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
)

# ─── Router Initialization ─────────────────────────────────────────────

_encoder = None
_route_layer = None


def _get_route_layer() -> RouteLayer:
    """Lazy-initialize the route layer to avoid startup delays."""
    global _encoder, _route_layer

    if _route_layer is None:
        _encoder = GoogleGenAIEncoder()
        _route_layer = RouteLayer(
            encoder=_encoder, routes=[shopping_route, chitchat_route]
        )

    return _route_layer


def classify_query(text: str) -> str:
    """
    Classify a user query as either 'shopping' or 'chitchat'.

    Args:
        text: The user's input query.

    Returns:
        'shopping' if the query is product/policy related,
        'chitchat' if it's general conversation,
        'chitchat' as fallback if no route matches.
    """
    try:
        route_layer = _get_route_layer()
        result = route_layer(text)

        if result and result.name:
            return result.name

        # Default fallback
        return "chitchat"

    except Exception as e:
        print(f"[Router] Classification error: {e}")
        return "chitchat"
