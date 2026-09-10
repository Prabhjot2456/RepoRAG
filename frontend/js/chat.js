/**
 * chat.js — Chat UI logic.
 * Handles message rendering, conversation history, source cards, and file viewer.
 */

const Chat = (() => {
  let conversationId = null;
  let conversationHistory = [];
  let currentRepoId = null;
  let currentRepoMeta = null;
  let isSending = false;

  const $ = id => document.getElementById(id);

  // ── Init ──────────────────────────────────────────────────────────────────
  function init(repoId, repoMeta) {
    currentRepoId = repoId;
    currentRepoMeta = repoMeta;
    conversationId = null;
    conversationHistory = [];
    _clearMessages();
    _showChatUI();
    _focusInput();
  }

  function _showChatUI() {
    $('chat-messages').classList.remove('hidden');
    $('chat-input-area').classList.remove('hidden');
    $('progress-overlay').classList.add('hidden');
    $('file-viewer').classList.add('hidden');
  }

  // ── Send message ──────────────────────────────────────────────────────────
  async function sendMessage(question) {
    if (!question.trim() || isSending || !currentRepoId) return;
    isSending = true;

    _appendUserMessage(question);
    _clearInput();
    const typingEl = _appendTypingIndicator();

    conversationHistory.push({ role: 'user', content: question });

    try {
      const response = await API.chat(
        currentRepoId,
        question,
        conversationHistory.slice(0, -1), // history before this question
        conversationId,
      );

      conversationId = response.conversation_id;
      conversationHistory.push({ role: 'assistant', content: response.answer });

      typingEl.remove();
      _appendAssistantMessage(response.answer, response.sources, response.query_type);

    } catch (err) {
      typingEl.remove();
      _appendErrorMessage(err.message);
      conversationHistory.pop(); // Remove failed question
    } finally {
      isSending = false;
      _updateSendButton();
      _focusInput();
    }
  }

  // ── Message rendering ─────────────────────────────────────────────────────
  function _appendUserMessage(text) {
    const container = $('chat-messages');
    const group = _createEl('div', 'message-group user');
    const msg = _createEl('div', 'message user');
    msg.textContent = text;
    group.appendChild(msg);
    container.appendChild(group);
    _scrollToBottom();
    return group;
  }

  function _appendAssistantMessage(text, sources = [], queryType = null) {
    const container = $('chat-messages');
    const group = _createEl('div', 'message-group assistant');
    const msg = _createEl('div', 'message assistant');

    // Render markdown
    msg.innerHTML = MarkdownRenderer.render(text);
    MarkdownRenderer.highlight(msg);

    // Sources
    if (sources && sources.length > 0) {
      const sourcesSection = _createSourcesSection(sources);
      msg.appendChild(sourcesSection);
    }

    group.appendChild(msg);
    container.appendChild(group);
    _scrollToBottom();
    return group;
  }

  function _appendErrorMessage(text) {
    const container = $('chat-messages');
    const group = _createEl('div', 'message-group assistant');
    const msg = _createEl('div', 'message assistant');
    msg.innerHTML = `<span style="color:var(--accent-error)">⚠️ Error: ${_escape(text)}</span>`;
    group.appendChild(msg);
    container.appendChild(group);
    _scrollToBottom();
    return group;
  }

  function _appendTypingIndicator() {
    const container = $('chat-messages');
    const group = _createEl('div', 'message-group assistant');
    const indicator = _createEl('div', 'typing-indicator');
    indicator.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
    group.appendChild(indicator);
    container.appendChild(group);
    _scrollToBottom();
    return group;
  }

  // ── Sources ───────────────────────────────────────────────────────────────
  function _createSourcesSection(sources) {
    const section = _createEl('div', 'sources-section');
    const label = _createEl('div', 'sources-label');
    label.textContent = '📎 Sources';
    section.appendChild(label);

    const chips = _createEl('div', 'source-chips');
    sources.forEach((src, idx) => {
      const chip = _createEl('button', 'source-chip');
      const lines = src.start_line ? `:${src.start_line}-${src.end_line}` : '';
      chip.textContent = `${src.file_path}${lines}`;
      chip.title = src.symbol ? `Symbol: ${src.symbol}` : src.file_path;
      chip.addEventListener('click', () => _showSourceModal(src));
      chips.appendChild(chip);
    });

    section.appendChild(chips);
    return section;
  }

  // ── Source modal ──────────────────────────────────────────────────────────
  function _showSourceModal(source) {
    const modal = $('source-modal');
    const lines = source.start_line ? `Lines ${source.start_line}–${source.end_line}` : '';
    const symbol = source.symbol ? ` · ${source.symbol}` : '';

    modal.querySelector('.modal-header h3').textContent = source.file_path;
    modal.querySelector('.modal-meta').textContent =
      [source.language, lines, symbol].filter(Boolean).join(' · ');

    const preEl = modal.querySelector('.modal-content pre code');
    if (source.content_preview) {
      preEl.textContent = source.content_preview;
      if (typeof hljs !== 'undefined' && source.language) {
        try {
          preEl.innerHTML = hljs.highlight(source.content_preview, { language: source.language }).value;
        } catch (_) {
          preEl.textContent = source.content_preview;
        }
      }
    } else {
      preEl.textContent = 'No preview available.';
    }

    const ghLink = modal.querySelector('.modal-github-link');
    if (source.github_url) {
      ghLink.href = source.github_url;
      ghLink.style.display = 'inline-flex';
    } else {
      ghLink.style.display = 'none';
    }

    modal.classList.remove('hidden');
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function _clearMessages() {
    $('chat-messages').innerHTML = '';
  }

  function _clearInput() {
    $('question-input').value = '';
    $('question-input').style.height = 'auto';
  }

  function _scrollToBottom() {
    const container = $('chat-messages');
    container.scrollTop = container.scrollHeight;
  }

  function _focusInput() {
    const input = $('question-input');
    if (input) input.focus();
  }

  function _updateSendButton() {
    const btn = $('send-btn');
    if (btn) btn.disabled = isSending;
  }

  function _createEl(tag, className) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    return el;
  }

  function _escape(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── "Ask this" shortcut ───────────────────────────────────────────────────
  function askQuestion(text) {
    $('question-input').value = text;
    sendMessage(text);
  }

  // ── Add welcome message ───────────────────────────────────────────────────
  function showWelcome(repoName, suggestions) {
    const container = $('chat-messages');
    const group = _createEl('div', 'message-group assistant');
    const msg = _createEl('div', 'message assistant');

    const suggestionsHtml = suggestions.map(q =>
      `<button class="suggestion-btn" onclick="App.askSuggestion('${q.replace(/'/g, "\\'")}')">${q}</button>`
    ).join('');

    msg.innerHTML = `
      <strong>🎉 ${_escape(repoName)} is ready!</strong><br><br>
      I've analyzed this repository and can answer any questions about it. Here are some things you can ask:<br><br>
      ${suggestionsHtml}
    `;
    group.appendChild(msg);
    container.appendChild(group);
    _scrollToBottom();
  }

  return {
    init,
    sendMessage,
    askQuestion,
    showWelcome,
    showSourceModal: _showSourceModal,
  };
})();
