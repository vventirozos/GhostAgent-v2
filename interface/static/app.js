import * as matrixGraphFace from './matrix_graph.js';

let activeFace = matrixGraphFace;

const chatLog = document.getElementById('chat-log');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const activityIcon = document.getElementById('activity-icon');
const fullscreenBtn = document.getElementById('fullscreen-btn');
const statusText = document.getElementById('status-text');
const connectionDot = document.getElementById('connection-dot');
const plannerMonologue = document.getElementById('planner-monologue');

let ws;
let monologueTimeout;
let chatHistory = [];
const wsUrl = `ws://${window.location.host}/ws`;

const WORKING_ICONS = new Set(['🧠', '🔍', '⚙️', '🔨', '⚡', '💡', '📡', '💾', '🛡️', '🔑', '🔓', '🚀', '🔮', '🧬', '🔬', '🔭', '🩺', '🧩', '📈', '📊', '📋']);
const IDLE_ICONS = new Set(['✅', '❌', '🛑', '😴', '💤']);

let isProcessingRequest = false;

function connectWebSocket() {
    ws = new WebSocket(wsUrl);
    ws.onopen = () => {
        if (statusText) statusText.textContent = "SYSTEM ONLINE";
        if (connectionDot) {
            connectionDot.style.boxShadow = "0 0 10px #00ff9d";
            connectionDot.style.backgroundColor = "#00ff9d";
        }
    };
    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'log') {
                const icon = extractIcon(data.content);
                const flashColor = getIconColor(icon);

                const isMonologue = data.content.includes("PLANNER MONOLOGUE");
                if (isMonologue) {
                    activeFace.triggerSmallPulse();
                } else {
                    activeFace.triggerPulse(flashColor); // Always heartbeat on new log
                }

                if (icon) {
                    updateActivityIcon(icon);
                    updateStateFromIcon(icon);
                    if (['❌', '🛑', '⚠️', '🔥'].includes(icon)) activeFace.triggerSpike();
                }
                flashActivityIcon();
                if (data.is_error) activeFace.triggerSpike();

                // Check for Planner Monologue
                const plannerMatch = data.content.match(/PLANNER MONOLOGUE\s*:\s*(.*)/);
                if (plannerMatch && plannerMatch[1]) {
                    showPlannerMonologue(plannerMatch[1]);
                }
            }
        } catch (e) { console.error("WebSocket Error:", e); }
    };
    ws.onclose = () => {
        if (statusText) statusText.textContent = "DISCONNECTED";
        if (connectionDot) {
            connectionDot.style.backgroundColor = "#ff2a2a";
            connectionDot.style.boxShadow = "none";
        }
        setTimeout(connectWebSocket, 3000);
    };
}

function showPlannerMonologue(text) {
    if (!plannerMonologue) return;
    plannerMonologue.textContent = text.trim();
    plannerMonologue.classList.add('visible');

    // Clear any existing hide timer so it stays visible while updating
    clearTimeout(monologueTimeout);

    // If we are NOT currently processing a request (e.g. late logs after reply),
    // ensure we still auto-hide after a short delay so it doesn't get stuck open.
    if (!isProcessingRequest) {
        monologueTimeout = setTimeout(hidePlannerMonologue, 2000);
    }
}

function hidePlannerMonologue() {
    if (!plannerMonologue) return;
    plannerMonologue.classList.remove('visible');
}

function extractIcon(logLine) {
    const match = logLine.match(/(\p{Extended_Pictographic})/u);
    return match ? match[0] : null;
}

function getIconColor(icon) {
    if (['🧠', '💡', '🔮', '🧬', '🧩'].includes(icon)) return '#00f3ff';
    if (['✅', '🔧', '🔨', '⚙️', '🛡️', '🔓'].includes(icon)) return '#00ff9d';
    if (['🔍', '💾', '📈', '📊', '📋', '🔑'].includes(icon)) return '#ffaa00';
    if (['📡', '⚡', '🚀', '🔭'].includes(icon)) return '#1e90ff';
    if (['❌', '🛑', '⚠️', '🔥'].includes(icon)) return '#ff2a2a';
    if (['😴', '💤', '🩺', '🔬'].includes(icon)) return '#ffffff';
    return '#bd00ff';
}

let iconHideTimeout;
function updateActivityIcon(icon) {
    if (activityIcon) {
        activityIcon.textContent = icon;
        activityIcon.style.opacity = '1';
        clearTimeout(iconHideTimeout);

        if (!isProcessingRequest) {
            iconHideTimeout = setTimeout(() => {
                if (!isProcessingRequest) {
                    activityIcon.style.opacity = '0';
                    setTimeout(() => {
                        // Ensure we don't clear an icon that just faded back in
                        if (activityIcon.style.opacity === '0') {
                            activityIcon.textContent = '';
                            activityIcon.style.opacity = '1';
                        }
                    }, 300);
                }
            }, 2000);
        }
    }
}

let workTimer;
function updateStateFromIcon(icon) {
    if (isProcessingRequest) return; // Prevent logs from turning off the active state during a request

    if (WORKING_ICONS.has(icon)) {
        activeFace.setWorkingState(true);
        if (activityIcon) activityIcon.classList.add('working');
        clearTimeout(workTimer);
        workTimer = setTimeout(() => {
            if (!isProcessingRequest) {
                activeFace.setWorkingState(false);
                if (activityIcon) activityIcon.classList.remove('working');
            }
        }, 2000);
    } else if (IDLE_ICONS.has(icon)) {
        activeFace.setWorkingState(false);
        if (activityIcon) activityIcon.classList.remove('working');
    }
}

let iconTimeout;
function flashActivityIcon() {
    if (activityIcon && !activityIcon.classList.contains('working')) {
        activityIcon.style.transform = "scale(1.2)";
        clearTimeout(iconTimeout);
        iconTimeout = setTimeout(() => { activityIcon.style.transform = "scale(1)"; }, 150);
    }
}

function addMessage(role, text) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    // Use marked.parse if available (it is added in index.html)
    if (window.marked) {
        div.innerHTML = marked.parse(text);
    } else {
        div.textContent = text;
    }
    chatLog.appendChild(div);
    scrollToBottom();
    return div;
}

function scrollToBottom() {
    requestAnimationFrame(() => { chatLog.scrollTo({ top: chatLog.scrollHeight, behavior: 'smooth' }); });
}

// Auto-expand textarea height organically
chatInput.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
    if (this.value === '') this.style.height = 'auto';
});

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isProcessingRequest) return;

    chatInput.value = '';
    chatInput.style.height = 'auto'; // Reset height perfectly
    addMessage('user', text);

    if (text === '/clear') {
        chatLog.innerHTML = '';
        chatHistory = [];
        const msg = addMessage('system', 'Context cleared');
        setTimeout(() => { msg.remove(); }, 2000);

        return;
    }

    // Explicitly lock the blob into an active state
    isProcessingRequest = true;
    activeFace.setWorkingState(true);
    activeFace.setWaitingState(true);
    if (activityIcon) {
        clearTimeout(iconHideTimeout);
        activityIcon.style.opacity = '1';
        activityIcon.textContent = '🧠';
        activityIcon.classList.add('working');
    }

    try {
        chatHistory.push({ role: "user", content: text });
        const payload = { model: "Qwen3-8B-Instruct-2507", messages: chatHistory };
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();

        if (data.error && data.error !== "") {
            addMessage('system', `Error: ${data.error}`);
            activeFace.triggerSpike();
        } else {
            let content = "No response";
            if (data.choices && data.choices[0] && data.choices[0].message) content = data.choices[0].message.content;
            else if (data.message && data.message.content) content = data.message.content;
            else if (data.response) content = data.response;
            else if (data.content) content = data.content;
            else content = JSON.stringify(data);
            addMessage('agent', content);
            chatHistory.push({ role: "assistant", content: content });
        }
    } catch (e) {
        chatHistory.pop();
        addMessage('system', `Network Error: ${e.message}`);
        activeFace.triggerSpike();
    } finally {
        isProcessingRequest = false;
        activeFace.setWorkingState(false);
        activeFace.setWaitingState(false);
        if (activityIcon) {
            activityIcon.classList.remove('working');
            updateActivityIcon('✅');
        }
        setTimeout(scrollToBottom, 100);

        // Auto-hide planner monologue 2 seconds after reply
        monologueTimeout = setTimeout(hidePlannerMonologue, 2000);
    }
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

if (fullscreenBtn) {
    fullscreenBtn.addEventListener('click', () => { document.body.classList.toggle('zen-mode'); });
}

// Global toggle for Zen Mode (Persistent Key)
document.addEventListener('keydown', (e) => {
    // Toggle with 'Z' unless user is typing in the chat input
    if (e.key.toLowerCase() === 'z' && document.activeElement !== chatInput) {
        document.body.classList.toggle('zen-mode');
    }
});

if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => {
        scrollToBottom();
        document.body.style.height = window.visualViewport.height + 'px';
        window.scrollTo(0, 0);
    });
}

document.addEventListener('dblclick', function (event) { event.preventDefault(); }, { passive: false });

setTimeout(() => {
    const sysMsg = document.getElementById('init-msg');
    if (sysMsg) {
        sysMsg.style.transition = 'opacity 1s ease';
        sysMsg.style.opacity = '0';
        setTimeout(() => sysMsg.remove(), 1000);
    }
}, 2000);

activeFace.init();
connectWebSocket();
