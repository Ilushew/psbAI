const API_URL = "/api/v1";
const SESSION_STORAGE_KEY = "psbai_session_id";

const state = {
    sessionId: localStorage.getItem(SESSION_STORAGE_KEY),
    activeChatId: null,
    chats: [],
    sending: false,
};

const elements = {
    chatList: document.getElementById("chat-list"),
    newChatButton: document.getElementById("new-chat"),
    conversation: document.getElementById("conversation"),
    welcome: document.getElementById("welcome"),
    messages: document.getElementById("messages"),
    messageForm: document.getElementById("message-form"),
    messageInput: document.getElementById("message-input"),
    sendButton: document.getElementById("send-button"),
};

async function apiRequest(path, options = {}) {
    const response = await fetch(`${API_URL}${path}`, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...options.headers,
        },
    });

    const data = await response.json().catch(() => null);

    if (!response.ok) {
        throw new Error(data?.error || `Ошибка сервера: ${response.status}`);
    }

    return data;
}

// Session

async function createSession() {
    const session = await apiRequest("/sessions", {
        method: "POST",
    });

    state.sessionId = session.id;
    localStorage.setItem(SESSION_STORAGE_KEY, session.id);
}

async function initializeSession() {
    if (!state.sessionId) {
        await createSession();
        return;
    }

    try {
        await loadChats();
    } catch {
        // Сохранённая сессия могла быть удалена.
        await createSession();
    }
}

// Chats

async function loadChats() {
    state.chats = await apiRequest(
        `/sessions/${state.sessionId}/chats`
    );

    renderChats();

    if (state.chats.length > 0) {
        await selectChat(state.chats[0].id);
    } else {
        showWelcome();
    }
}

async function createChat(title) {
    const chat = await apiRequest("/chats", {
        method: "POST",
        body: JSON.stringify({
            session_id: state.sessionId,
            title,
        }),
    });

    state.chats.unshift(chat);
    state.activeChatId = chat.id;

    renderChats();
    clearMessages();

    return chat;
}

function renderChats() {
    elements.chatList.replaceChildren();

    if (state.chats.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-chats";
        empty.textContent = "Здесь пока нет диалогов";
        elements.chatList.append(empty);
        return;
    }

    for (const chat of state.chats) {
        const item = document.createElement("div");

        item.className = "chat-item";
        item.textContent = chat.title;
        item.title = chat.title;

        if (chat.id === state.activeChatId) {
            item.classList.add("active");
        }

        item.addEventListener("click", () => selectChat(chat.id));

        elements.chatList.append(item);
    }
}

async function selectChat(chatId) {
    state.activeChatId = chatId;
    renderChats();
    clearMessages();

    try {
        const messages = await apiRequest(`/chats/${chatId}/messages`);

        for (const item of messages) {
            renderMessage(
                item.message,
                item.sources || []
            );
        }

        updateWelcome();
    } catch (error) {
        showError(error.message);
    }
}

function startNewChat() {
    state.activeChatId = null;
    renderChats();
    clearMessages();
    updateWelcome();
    elements.messageInput.focus();
}

// Messages

async function sendMessage(content) {
    if (state.sending || !content.trim()) {
        return;
    }

    state.sending = true;
    setSending(true);

    try {
        if (!state.activeChatId) {
            const title = content.trim().slice(0, 60);
            await createChat(title);
        }

        const chatId = state.activeChatId;

        const userMessage = {
            role: "user",
            content,
            created_at: new Date().toISOString(),
        };

        renderMessage(userMessage);
        elements.messageInput.value = "";
        resizeTextarea();
        updateWelcome();

        try {
            const result = await apiRequest(
                `/chats/${chatId}/messages`,
                {
                    method: "POST",
                    body: JSON.stringify({ content }),
                }
            );

            renderMessage(
                result.message,
                result.sources || []
            );
        } catch (error) {
            showError(
                `Не удалось получить ответ ассистента. ${error.message}`
            );
        }

        renderChats();
        scrollToBottom();
    } catch (error) {
        showError(error.message);
    } finally {
        state.sending = false;
        setSending(false);
        elements.messageInput.focus();
    }
}

function renderMessage(message, sources = []) {
    const wrapper = document.createElement("div");
    wrapper.className = `message ${message.role}`;

    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent =
        message.role === "user" ? "Вы" : "ПСБ AI";

    const content = document.createElement("div");
    content.className = "message-content";
    content.textContent = message.content;

    wrapper.append(label, content);
    elements.messages.append(wrapper);

    if (sources.length > 0) {
        const sourcesContainer = document.createElement("div");
        sourcesContainer.className = "sources";

        const title = document.createElement("div");
        title.className = "sources-title";
        title.textContent = "Источники";

        sourcesContainer.append(title);

        for (const source of sources) {
            const card = document.createElement("div");
            card.className = "source-card";

            const name = document.createElement("div");
            name.className = "source-name";
            name.textContent = source.document_id;

            const text = document.createElement("div");
            text.className = "source-text";
            text.textContent = source.text;

            card.append(name, text);
            sourcesContainer.append(card);
        }

        elements.messages.append(sourcesContainer);
    }

    updateWelcome();
    scrollToBottom();
}

function showError(message) {
    const error = document.createElement("div");
    error.className = "error-message";
    error.textContent = message;

    elements.messages.append(error);
    updateWelcome();
    scrollToBottom();
}

function clearMessages() {
    elements.messages.replaceChildren();
    updateWelcome();
}

function showWelcome() {
    clearMessages();
    elements.welcome.style.display = "block";
}

function updateWelcome() {
    const hasMessages = elements.messages.children.length > 0;
    elements.welcome.style.display = hasMessages ? "none" : "block";
}

function scrollToBottom() {
    elements.conversation.scrollTop =
        elements.conversation.scrollHeight;
}

function setSending(sending) {
    elements.sendButton.disabled = sending;
    elements.messageInput.disabled = sending;
    elements.sendButton.textContent = sending ? "…" : "↑";
}

// Input

function resizeTextarea() {
    elements.messageInput.style.height = "auto";
    elements.messageInput.style.height =
        `${elements.messageInput.scrollHeight}px`;
}

elements.messageForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const content = elements.messageInput.value.trim();

    if (!content) {
        return;
    }

    await sendMessage(content);
});

elements.messageInput.addEventListener("input", resizeTextarea);

elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        elements.messageForm.requestSubmit();
    }
});

elements.newChatButton.addEventListener("click", startNewChat);

document.querySelectorAll(".suggestion").forEach((button) => {
    button.addEventListener("click", () => {
        elements.messageInput.value = button.dataset.question;
        elements.messageForm.requestSubmit();
    });
});

// Application startup

async function init() {
    try {
        await initializeSession();

        if (state.chats.length === 0) {
            await loadChats();
        }
    } catch (error) {
        showError(`Не удалось запустить приложение. ${error.message}`);
    }
}

init();