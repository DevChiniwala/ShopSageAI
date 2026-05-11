"""
Chitchat Chain - Handles general conversation using Gemini with memory.

Maintains per-session conversation history using ConversationBufferMemory
for natural multi-turn interactions.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_classic.chains import ConversationChain
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.prompts import PromptTemplate
from shopsage.config import LLM_MODEL, GOOGLE_API_KEY

CHITCHAT_PROMPT = PromptTemplate(
    input_variables=["history", "input"],
    template="""You are ShopSage AI, a friendly and intelligent shopping assistant.

You are currently in a casual conversation. Be warm, helpful, and personable.
If the user asks what you can do, tell them about your shopping capabilities:
- Search products by color, size, brand, price, or any criteria
- Compare products and recommend the best options
- Answer questions about policies (returns, shipping, etc.)
- Have friendly conversations

Keep responses concise but engaging. Use emojis sparingly to add personality.

Previous conversation:
{history}

User: {input}
ShopSage AI:""",
)

# ─── Session Memory Store ──────────────────────────────────────────────

_session_memories: dict[str, ConversationBufferMemory] = {}


def _get_memory(session_id: str) -> ConversationBufferMemory:
    """Get or create a conversation memory for a session."""
    if session_id not in _session_memories:
        _session_memories[session_id] = ConversationBufferMemory(
            human_prefix="User", ai_prefix="ShopSage AI"
        )
    return _session_memories[session_id]


def get_chitchat_response(user_input: str, session_id: str) -> str:
    """
    Generate a chitchat response using Gemini with conversation memory.

    Args:
        user_input: The user's message.
        session_id: Unique session identifier for memory persistence.

    Returns:
        The AI's conversational response.
    """
    try:
        llm = ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=0.7,
        )

        memory = _get_memory(session_id)

        chain = ConversationChain(
            llm=llm, memory=memory, prompt=CHITCHAT_PROMPT, verbose=False
        )

        response = chain.predict(input=user_input)
        return response.strip()

    except Exception as e:
        print(f"[Chitchat] Error: {e}")
        return (
            "I'm having a bit of trouble right now. "
            "Could you try asking me again? 😊"
        )
