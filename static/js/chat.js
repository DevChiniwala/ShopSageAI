/**
 * ShopSage AI — Chat Interaction Logic
 */

const messagesContainer = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');

// Session ID for conversation continuity
let sessionId = crypto.randomUUID ? crypto.randomUUID() : generateUUID();

function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
        const r = Math.random() * 16 | 0;
        return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
}

// ─── Initialize ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    addBotMessage(
        `Hey there! 👋 I'm **ShopSage AI**, your intelligent shopping companion.\n\n` +
        `Here's what I can help you with:\n` +
        `🔍 **Search products** — "Show me red shirts"\n` +
        `📊 **Compare & recommend** — "Best jacket under ₹5000"\n` +
        `📋 **Policy questions** — "What's your return policy?"\n` +
        `💬 **Just chat** — "How are you?"\n\n` +
        `What are you looking for today?`,
        'chitchat'
    );
    messageInput.focus();
});

// ─── Event Listeners ───────────────────────────────────────────
sendBtn.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// ─── Send Message ──────────────────────────────────────────────
async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text) return;

    // Add user message
    addUserMessage(text);
    messageInput.value = '';
    sendBtn.disabled = true;

    // Show typing indicator
    const typingEl = showTypingIndicator();

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                session_id: sessionId
            })
        });

        const data = await response.json();

        // Update session ID if returned
        if (data.session_id) {
            sessionId = data.session_id;
        }

        // Remove typing, add response
        removeTypingIndicator(typingEl);
        addBotMessage(data.response, data.route);

    } catch (error) {
        console.error('Chat error:', error);
        removeTypingIndicator(typingEl);
        addBotMessage(
            "Sorry, I'm having trouble connecting. Please check if the server is running and try again.",
            'error'
        );
    }

    sendBtn.disabled = false;
    messageInput.focus();
}

// ─── Add User Message ──────────────────────────────────────────
function addUserMessage(text) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message user';
    messageEl.innerHTML = `
        <div class="message-avatar">You</div>
        <div class="message-content">${escapeHtml(text)}</div>
    `;
    messagesContainer.appendChild(messageEl);
    scrollToBottom();
}

// ─── Add Bot Message ───────────────────────────────────────────
function addBotMessage(text, route = '') {
    const messageEl = document.createElement('div');
    messageEl.className = 'message bot';

    let badgeHtml = '';
    if (route === 'shopping') {
        badgeHtml = '<span class="route-badge shopping">🛒 Shopping</span>';
    } else if (route === 'chitchat') {
        badgeHtml = '<span class="route-badge chitchat">💬 Chat</span>';
    }

    messageEl.innerHTML = `
        <div class="message-avatar">AI</div>
        <div class="message-content">
            ${badgeHtml}
            <div>${formatMarkdown(text)}</div>
        </div>
    `;
    messagesContainer.appendChild(messageEl);
    scrollToBottom();
}

// ─── Typing Indicator ──────────────────────────────────────────
function showTypingIndicator() {
    const typingEl = document.createElement('div');
    typingEl.className = 'message bot';
    typingEl.id = 'typing-indicator';
    typingEl.innerHTML = `
        <div class="message-avatar">AI</div>
        <div class="typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    messagesContainer.appendChild(typingEl);
    scrollToBottom();
    return typingEl;
}

function removeTypingIndicator(el) {
    if (el && el.parentNode) {
        el.parentNode.removeChild(el);
    }
}

// ─── Utilities ─────────────────────────────────────────────────
function scrollToBottom() {
    requestAnimationFrame(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatMarkdown(text) {
    if (!text) return '';

    return text
        // Bold: **text**
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        // Italic: *text*
        .replace(/(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')
        // Inline code: `code`
        .replace(/`(.*?)`/g, '<code>$1</code>')
        // Headers: ### text
        .replace(/^### (.*$)/gm, '<strong style="font-size:1.05em;display:block;margin-top:10px;">$1</strong>')
        // Bullet points: - item
        .replace(/^- (.*$)/gm, '• $1')
        // Numbered lists: 1. item
        .replace(/^(\d+)\. (.*$)/gm, '<span style="opacity:0.6">$1.</span> $2')
        // Line breaks
        .replace(/\n/g, '<br>');
}
