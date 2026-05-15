"""
Shopping Agent — LangGraph ReAct agent for product intelligence.

Uses product search, policy search, and preference tools to analyze,
compare, and recommend products with structured reasoning.
Integrates user memory for personalized recommendations.
"""

import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from shopsage.tool.product_search import product_search, product_search_by_price
from shopsage.tool.policy_search import policy_search
from shopsage.tool.preference_tool import save_user_preference, get_profile_context
from shopsage.config import LLM_MODEL, GOOGLE_API_KEY, ENABLE_USER_MEMORY

logger = logging.getLogger("shopsage.agent")


# ─── System Prompt ─────────────────────────────────────────────────────

SHOPPING_SYSTEM_PROMPT = """You are ShopSage AI, an advanced AI-powered personal shopping agent.

Your goal is to help users make the BEST possible purchase decisions by intelligently
analyzing products, comparing options, and reasoning through value.

You DO NOT just list products — you THINK, ANALYZE, and RECOMMEND.

## Your Core Responsibilities:
1. Understand the user's intent deeply (budget, preferences, use-case)
2. Search and compare multiple products using your tools
3. Evaluate value for money (price vs quality)
4. Rank products intelligently
5. Recommend the BEST option with clear reasoning

## Decision Framework:
For every product query, evaluate:
- Price efficiency
- Features relevance
- Brand reliability
- Value for money
- Fit for user's specific need

## Response Format:
When recommending products, use this structure:

🥇 **Best Choice**
- Name, Price, and WHY it's best for this user

🥈 **Alternatives**
- Other options with brief reasoning

⚖️ **Comparison Summary**
- Key differences and trade-offs

🧠 **Final Verdict**
- Clear, personalized recommendation

## Preference Learning:
- When you discover user preferences, call save_user_preference to remember them
- Preference signals: budget mentions, brand love/hate, size info, style keywords,
  color preferences, material preferences, gender-specific requests
- Examples: "I like Nike" → save brand. "Under 5000" → save budget_max.
  "I wear L" → save size. "I prefer cotton" → save material.

## Important Rules:
- Always search the database first — never make up products
- Be concise but insightful
- If no products match, say so honestly
- For policy questions, use the policy search tool
- Always personalize recommendations using the user context below
- Use ₹ for currency
"""

MEMORY_CONTEXT_TEMPLATE = """
## User Context (from memory):
{profile_context}
"""

# ─── Agent Setup ───────────────────────────────────────────────────────

_checkpointer = MemorySaver()
_tools = [product_search, product_search_by_price, policy_search, save_user_preference]

_llm = None
_agent = None


def _get_agent():
    """Lazy-initialize the shopping agent."""
    global _llm, _agent

    if _agent is None:
        _llm = ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=0.3,
        )

        _agent = create_react_agent(
            model=_llm,
            tools=_tools,
            checkpointer=_checkpointer
        )

    return _agent


def _build_system_prompt(session_id: str) -> str:
    """Build the full system prompt with user profile context injected."""
    prompt = SHOPPING_SYSTEM_PROMPT

    if ENABLE_USER_MEMORY:
        profile_context = get_profile_context(session_id)
        prompt += MEMORY_CONTEXT_TEMPLATE.format(profile_context=profile_context)

    return prompt


def get_shopping_response(user_input: str, session_id: str) -> str:
    """
    Process a shopping query through the ReAct agent.

    The agent will autonomously decide which tools to use,
    search for products/policies, and generate a structured recommendation.
    User profile is loaded and injected into the system prompt for
    personalized recommendations.

    Args:
        user_input: The user's product-related query.
        session_id: Unique session ID for conversation continuity.

    Returns:
        The agent's structured recommendation response.
    """
    try:
        agent = _get_agent()

        config = {"configurable": {"thread_id": session_id}}

        system_prompt = _build_system_prompt(session_id)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        response = agent.invoke(
            {"messages": messages},
            config=config
        )

        # Extract the last AI message from the response
        ai_messages = [
            msg for msg in response["messages"]
            if hasattr(msg, "type") and msg.type == "ai" and msg.content
        ]

        if ai_messages:
            return ai_messages[-1].content.strip()

        return "I couldn't process your request. Please try rephrasing your query."

    except Exception as e:
        logger.error(f"[Shopping Agent] Error: {e}", exc_info=True)
        return (
            "I encountered an error while searching for products. "
            "Please make sure the database is initialized and try again."
        )
