"""
Conversation Exporter — Export chat history as JSON or CSV.

Provides formatted exports for analytics, compliance, and user download.
"""

import csv
import json
import logging
import io
from dataclasses import asdict
from typing import List

from shopsage.history.conversation_store import Message

logger = logging.getLogger("shopsage.history.exporter")


def export_to_json(messages: List[Message], pretty: bool = True) -> str:
    """
    Export messages to a JSON string.

    Args:
        messages: List of Message dataclass instances.
        pretty: Whether to indent for readability.

    Returns:
        JSON string with all messages.
    """
    data = {
        "export_format": "shopsage_conversation_v1",
        "message_count": len(messages),
        "session_id": messages[0].session_id if messages else "",
        "messages": [asdict(m) for m in messages],
    }
    return json.dumps(data, indent=2 if pretty else None, ensure_ascii=False)


def export_to_csv(messages: List[Message]) -> str:
    """
    Export messages to a CSV string.

    Columns: id, session_id, role, content, route, timestamp

    Returns:
        CSV formatted string.
    """
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "session_id", "role", "content", "route", "timestamp"],
        quoting=csv.QUOTE_ALL,
    )
    writer.writeheader()
    for m in messages:
        writer.writerow(asdict(m))

    return output.getvalue()


def export_to_markdown(messages: List[Message]) -> str:
    """
    Export messages as a readable Markdown transcript.

    Useful for sharing conversation logs in reports or documentation.

    Returns:
        Markdown formatted string.
    """
    if not messages:
        return "# Empty Conversation\n\nNo messages found."

    session_id = messages[0].session_id
    lines = [
        f"# ShopSage AI — Conversation Transcript",
        f"",
        f"**Session:** `{session_id[:12]}…`  ",
        f"**Messages:** {len(messages)}  ",
        f"**Period:** {messages[0].timestamp} → {messages[-1].timestamp}",
        f"",
        "---",
        f"",
    ]

    for msg in messages:
        if msg.role == "user":
            lines.append(f"### 🧑 User")
            lines.append(f"> {msg.content}")
        elif msg.role == "assistant":
            lines.append(f"### 🤖 ShopSage AI")
            lines.append(f"{msg.content}")
        else:
            lines.append(f"### ⚙️ System")
            lines.append(f"*{msg.content}*")

        lines.append(f"")
        lines.append(f"<small>📅 {msg.timestamp} · Route: `{msg.route}`</small>")
        lines.append(f"")
        lines.append("---")
        lines.append(f"")

    return "\n".join(lines)
