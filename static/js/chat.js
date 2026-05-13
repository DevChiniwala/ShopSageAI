/**
 * ShopSage AI — Chat Controller
 * Manages welcome → chat state transitions, message flow, and API communication
 */
'use strict';

// ─── DOM Cache ──────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const welcomeScreen = $('welcome-screen');
const chatScreen    = $('chat-screen');
const welcomeInput  = $('welcome-input');
const welcomeSend   = $('welcome-send');
const messageInput  = $('message-input');
const sendBtn       = $('send-btn');
const messagesEl    = $('chat-messages');
const backBtn       = $('back-btn');
const clearBtn      = $('clear-chat');
const chips         = document.querySelectorAll('.chip');

// ─── Session State ──────────────────────────────────────────────
let sessionId = _uuid();
let isSending = false;

function _uuid() {
    return crypto.randomUUID?.() ??
        'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
            const r = Math.random() * 16 | 0;
            return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
}

function _time() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ─── Screen Transitions ─────────────────────────────────────────
function switchToChat(initialMessage) {
    welcomeScreen.classList.add('fade-out');
    setTimeout(() => {
        welcomeScreen.classList.add('hidden');
        chatScreen.classList.remove('hidden');
        chatScreen.classList.add('visible');
        messageInput.focus();
        if (initialMessage) sendMessage(initialMessage);
    }, 500);
}

function switchToWelcome() {
    chatScreen.classList.remove('visible');
    chatScreen.classList.add('hidden');
    welcomeScreen.classList.remove('hidden', 'fade-out');
    welcomeInput.value = '';
    welcomeInput.focus();
    messagesEl.innerHTML = '';
    sessionId = _uuid();
}

// ─── Event Binding ──────────────────────────────────────────────
welcomeSend.addEventListener('click', () => {
    const text = welcomeInput.value.trim();
    if (text) switchToChat(text);
});

welcomeInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        const text = welcomeInput.value.trim();
        if (text) switchToChat(text);
    }
});

chips.forEach(chip => {
    chip.addEventListener('click', () => switchToChat(chip.dataset.query));
});

sendBtn.addEventListener('click', () => {
    const text = messageInput.value.trim();
    if (text && !isSending) sendMessage(text);
});

messageInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const text = messageInput.value.trim();
        if (text && !isSending) sendMessage(text);
    }
});

backBtn.addEventListener('click', switchToWelcome);
clearBtn.addEventListener('click', () => {
    messagesEl.innerHTML = '';
    sessionId = _uuid();
});

// ─── API Communication ──────────────────────────────────────────
async function sendMessage(text) {
    if (isSending) return;
    isSending = true;

    addUserMsg(text);
    messageInput.value = '';
    sendBtn.disabled = true;
    const typing = showTyping();

    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 60000);

        const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: sessionId }),
            signal: controller.signal
        });

        clearTimeout(timeout);
        const data = await res.json();
        if (data.session_id) sessionId = data.session_id;

        removeTyping(typing);
        addBotMsg(data.response, data.route);
    } catch (err) {
        removeTyping(typing);
        const msg = err.name === 'AbortError'
            ? 'Request timed out. The server might be busy — please try again.'
            : "Sorry, I couldn't connect to the server. Please check if it's running.";
        addBotMsg(msg, 'error');
    } finally {
        isSending = false;
        sendBtn.disabled = false;
        messageInput.focus();
    }
}

// ─── Message Rendering ──────────────────────────────────────────
function addUserMsg(text) {
    const el = document.createElement('div');
    el.className = 'message user';
    el.innerHTML = `
        <div class="msg-avatar">You</div>
        <div class="msg-bubble">
            <div>${escapeHtml(text)}</div>
            <div class="msg-meta">
                <span>${_time()}</span>
                <svg viewBox="0 0 16 16" fill="currentColor"><path d="M12.354 4.354a.5.5 0 00-.708-.708L5 10.293 2.354 7.646a.5.5 0 10-.708.708l3 3a.5.5 0 00.708 0l7-7z"/></svg>
            </div>
        </div>`;
    messagesEl.appendChild(el);
    scrollBottom();
}

function addBotMsg(text, route) {
    const el = document.createElement('div');
    el.className = 'message bot';

    const tags = {
        shopping: '<div class="route-tag shopping">🛒 Shopping</div>',
        chitchat: '<div class="route-tag chitchat">💬 Chat</div>'
    };

    el.innerHTML = `
        <div class="msg-avatar"><div class="bot-orb"></div></div>
        <div class="msg-bubble">
            ${tags[route] || ''}
            <div>${formatMd(text)}</div>
            <div class="msg-meta"><span>${_time()}</span></div>
        </div>`;
    messagesEl.appendChild(el);
    scrollBottom();
}

// ─── Typing Indicator ───────────────────────────────────────────
function showTyping() {
    const el = document.createElement('div');
    el.className = 'message bot';
    el.id = 'typing-indicator';
    el.innerHTML = `
        <div class="msg-avatar"><div class="bot-orb"></div></div>
        <div class="typing-dots"><span></span><span></span><span></span></div>`;
    messagesEl.appendChild(el);
    scrollBottom();
    return el;
}

function removeTyping(el) { el?.remove(); }

// ─── Utilities ──────────────────────────────────────────────────
function scrollBottom() {
    requestAnimationFrame(() => { messagesEl.scrollTop = messagesEl.scrollHeight; });
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatMd(text) {
    if (!text) return '';
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/^### (.*$)/gm, '<strong style="font-size:1.05em;display:block;margin:10px 0 4px">$1</strong>')
        .replace(/^## (.*$)/gm, '<strong style="font-size:1.1em;display:block;margin:12px 0 6px">$1</strong>')
        .replace(/^- (.*$)/gm, '&nbsp;&nbsp;•&nbsp; $1')
        .replace(/^(\d+)\. (.*$)/gm, '&nbsp;&nbsp;$1.&nbsp; $2')
        .replace(/\n/g, '<br>');
}
