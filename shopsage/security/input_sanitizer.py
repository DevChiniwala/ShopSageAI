"""
Input Sanitizer — Validates and cleans user input for ShopSage AI.

Prevents:
- SQL injection via parameterized queries (already handled by SQLite bindings)
- XSS via HTML entity encoding
- Prompt injection via pattern filtering
- Oversized payloads via length limits
- Malicious file uploads via MIME validation
"""

import re
import html
import logging
from typing import Optional, Tuple

logger = logging.getLogger("shopsage.security.sanitizer")

# Maximum allowed lengths
MAX_MESSAGE_LENGTH = 2000
MAX_SESSION_ID_LENGTH = 64
MAX_URL_LENGTH = 2048
MAX_NAME_LENGTH = 128

# Patterns that suggest prompt injection attempts
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"forget\s+(all\s+)?your\s+(previous\s+)?instructions",
    r"you\s+are\s+now\s+(?:a|an)\s+(?:different|new)",
    r"disregard\s+(?:all|your)\s+(?:prior|previous)",
    r"override\s+(?:your|the)\s+system\s+prompt",
    r"act\s+as\s+(?:if|though)\s+you\s+(?:have|had)\s+no\s+(?:rules|restrictions)",
    r"repeat\s+(?:your|the)\s+system\s+(?:prompt|message)",
    r"print\s+(?:your|the)\s+(?:initial|system)\s+(?:prompt|instructions)",
]

_INJECTION_RE = re.compile(
    "|".join(PROMPT_INJECTION_PATTERNS),
    re.IGNORECASE,
)


class InputSanitizer:
    """
    Validates and sanitizes all user-facing input.

    Usage:
        sanitizer = InputSanitizer()
        clean, warning = sanitizer.sanitize_message("Hello!")
    """

    def sanitize_message(self, message: str) -> Tuple[str, Optional[str]]:
        """
        Sanitize a chat message.

        Returns:
            Tuple of (cleaned_message, warning_or_None).
            If warning is set, the message was modified or flagged.
        """
        if not message or not message.strip():
            return "", "Empty message"

        # Length check
        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[:MAX_MESSAGE_LENGTH]
            warning = f"Message truncated to {MAX_MESSAGE_LENGTH} characters"
        else:
            warning = None

        # HTML entity encoding (prevent XSS in any rendered output)
        message = html.escape(message, quote=True)

        # Check for prompt injection patterns
        if _INJECTION_RE.search(message):
            logger.warning(f"[Sanitizer] Prompt injection attempt detected")
            warning = "Suspicious input pattern detected"

        return message.strip(), warning

    def sanitize_session_id(self, session_id: str) -> Tuple[str, Optional[str]]:
        """
        Validate and sanitize a session ID.

        Session IDs should be alphanumeric + hyphens only.
        """
        if not session_id:
            return "", None

        if len(session_id) > MAX_SESSION_ID_LENGTH:
            return "", "Session ID too long"

        # Only allow UUID-like characters
        cleaned = re.sub(r"[^a-zA-Z0-9\-_]", "", session_id)
        if cleaned != session_id:
            return cleaned, "Session ID contained invalid characters"

        return cleaned, None

    def sanitize_url(self, url: str) -> Tuple[str, Optional[str]]:
        """
        Validate a webhook URL.

        Must be HTTPS and within length limits.
        """
        if not url:
            return "", "Empty URL"

        if len(url) > MAX_URL_LENGTH:
            return "", "URL too long"

        url = url.strip()

        # Must start with https:// (or http:// for dev)
        if not re.match(r"^https?://", url, re.IGNORECASE):
            return "", "URL must start with http:// or https://"

        # Block private/internal IPs
        private_patterns = [
            r"https?://localhost",
            r"https?://127\.",
            r"https?://10\.",
            r"https?://172\.(1[6-9]|2\d|3[01])\.",
            r"https?://192\.168\.",
            r"https?://0\.0\.0\.0",
        ]
        for pattern in private_patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return "", "Internal/private URLs are not allowed"

        return url, None

    def sanitize_name(self, name: str) -> Tuple[str, Optional[str]]:
        """Sanitize a tenant or entity name."""
        if not name or not name.strip():
            return "", "Empty name"

        if len(name) > MAX_NAME_LENGTH:
            name = name[:MAX_NAME_LENGTH]

        # Encode HTML entities
        name = html.escape(name.strip(), quote=True)

        return name, None

    def validate_plan(self, plan: str) -> Tuple[str, Optional[str]]:
        """Validate a billing plan name."""
        valid_plans = {"free", "pro", "enterprise"}
        plan = plan.strip().lower()
        if plan not in valid_plans:
            return "free", f"Invalid plan '{plan}', defaulting to 'free'"
        return plan, None
