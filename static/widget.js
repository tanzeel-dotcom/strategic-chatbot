(function() {
    // Basic Configuration
    // In production, BASE_URL should be the full domain of your FastAPI server, e.g., 'https://your-chatbot-api.com'
    // For local testing, we auto-detect it based on where the script was loaded from, or default to localhost.
    const scripts = document.getElementsByTagName('script');
    let srcUrl = '';
    for (let i = 0; i < scripts.length; i++) {
        if (scripts[i].src.includes('widget.js')) {
            srcUrl = scripts[i].src;
            break;
        }
    }
    const BASE_URL = srcUrl ? new URL(srcUrl).origin : 'http://localhost:8000';
    
    // Determine the current website URL
    const WEBSITE_URL = window.location.origin;

    // Inject CSS
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `${BASE_URL}/style.css`;
    document.head.appendChild(link);

    // Global History
    let chatHistory = [];

    // Create Base HTML Structure
    const widgetHTML = `
        <div id="antigravity-chat-widget">
            <div id="ag-chat-window">
                <div id="ag-chat-header">
                    <div class="ag-header-info">
                        <h3>Support Agent</h3>
                        <p>We typically reply in minutes</p>
                    </div>
                    <button id="ag-close-button">
                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M13 1L1 13M1 1L13 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                </div>
                <div id="ag-chat-messages">
                    <div class="ag-message bot">
                        <p>Hi there! 👋 How can I help you today?</p>
                    </div>
                </div>
                <div class="ag-typing-indicator" id="ag-typing-indicator">
                    <div class="ag-typing-dot"></div>
                    <div class="ag-typing-dot"></div>
                    <div class="ag-typing-dot"></div>
                </div>
                <div id="ag-chat-input-area">
                    <input type="text" id="ag-chat-input" placeholder="Type your message..." />
                    <button id="ag-send-button">
                        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M2.01 21L23 12L2.01 3L2 10L17 12L2 14L2.01 21Z" />
                        </svg>
                    </button>
                </div>
            </div>
            <div id="ag-chat-bubble">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2C6.477 2 2 6.029 2 11C2 13.567 3.17 15.862 5.087 17.511C5.032 18.232 4.706 19.349 3.511 20.893C3.332 21.127 3.42 21.464 3.684 21.579C4.659 22.007 5.922 22.107 7.072 21.724C8.583 22.565 10.254 23 12 23C17.523 23 22 18.971 22 14C22 9.029 17.523 2 12 2ZM8 12.5C7.171 12.5 6.5 11.829 6.5 11C6.5 10.171 7.171 9.5 8 9.5C8.829 9.5 9.5 10.171 9.5 11C9.5 11.829 8.829 12.5 8 12.5ZM12 12.5C11.171 12.5 10.5 11.829 10.5 11C10.5 10.171 11.171 9.5 12 9.5C12.829 9.5 13.5 10.171 13.5 11C13.5 11.829 12.829 12.5 12 12.5ZM16 12.5C15.171 12.5 14.5 11.829 14.5 11C14.5 10.171 15.171 9.5 16 9.5C16.829 9.5 17.5 10.171 17.5 11C17.5 11.829 16.829 12.5 16 12.5Z"/>
                </svg>
            </div>
        </div>
    `;

    // Append to body
    const widgetContainer = document.createElement('div');
    widgetContainer.innerHTML = widgetHTML;
    document.body.appendChild(widgetContainer);

    // Elements
    const bubble = document.getElementById('ag-chat-bubble');
    const windowEl = document.getElementById('ag-chat-window');
    const closeBtn = document.getElementById('ag-close-button');
    const inputEl = document.getElementById('ag-chat-input');
    const sendBtn = document.getElementById('ag-send-button');
    const messagesEl = document.getElementById('ag-chat-messages');
    const typingIndicator = document.getElementById('ag-typing-indicator');

    // Toggle Window state
    bubble.addEventListener('click', () => {
        windowEl.classList.toggle('ag-open');
        if (windowEl.classList.contains('ag-open')) {
            bubble.style.transform = 'scale(0)';
            inputEl.focus();
        }
    });

    closeBtn.addEventListener('click', () => {
        windowEl.classList.remove('ag-open');
        bubble.style.transform = 'scale(1)';
    });

    // Send Message
    async function sendMessage() {
        const text = inputEl.value.trim();
        if (!text) return;

        // User message UI
        appendMessage('user', text);
        inputEl.value = '';
        
        // Show typing
        typingIndicator.classList.add('active');
        messagesEl.appendChild(typingIndicator); // move to bottom
        messagesEl.scrollTop = messagesEl.scrollHeight;

        try {
            // Setup an empty bot message we will continually update via stream
            const botMessageDiv = document.createElement('div');
            botMessageDiv.className = 'ag-message bot';
            // Placeholder for stream
            botMessageDiv.innerHTML = '<p></p>';
            messagesEl.appendChild(botMessageDiv);
            const contentP = botMessageDiv.querySelector('p');
            
            // Fetch streaming response
            const response = await fetch(`${BASE_URL}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    website_url: WEBSITE_URL,
                    history: chatHistory
                })
            });

            if (!response.ok) {
                throw new Error('API Error');
            }

            typingIndicator.classList.remove('active');

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let fullResponse = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                
                const chunk = decoder.decode(value, { stream: true });
                fullResponse += chunk;
                // Add basic Markdown formatting on the fly if needed
                // For a robust implementation, include a library like marked.js
                // Here we simply replace double newlines with <p> tags
                contentP.innerHTML = fullResponse.split('\\n\\n').join('</p><p>');
                messagesEl.scrollTop = messagesEl.scrollHeight;
            }

            // Update History
            chatHistory.push({ role: 'user', content: text });
            chatHistory.push({ role: 'assistant', content: fullResponse });

        } catch (error) {
            console.error(error);
            typingIndicator.classList.remove('active');
            appendMessage('bot', 'Oops... Something went wrong trying to reach the server.');
        }
    }

    function appendMessage(role, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `ag-message ${role}`;
        msgDiv.innerHTML = `<p>${text}</p>`;
        messagesEl.appendChild(msgDiv);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // Event Listeners for Input
    sendBtn.addEventListener('click', sendMessage);
    inputEl.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

})();
