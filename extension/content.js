/**
 * content.js — Content script injected into GitHub pages.
 *
 * Responsibilities:
 *   - Inject a collapsible sidebar into GitHub's DOM
 *   - Auto-detect the current repository from the page URL
 *   - Read highlighted/selected code from the page
 *   - Manage the chat UI, send questions to the backend
 */

(function () {
  'use strict';

  // Prevent double-injection
  if (document.getElementById('reporag-sidebar')) return;

  // ── Constants ───────────────────────────────────────────────────────────────
  let API_BASE = 'https://reporag-backend-r1ye.onrender.com';
  let currentRepo = null;
  let currentRepoId = null;
  let conversationId = null;
  let conversationHistory = [];
  let isSending = false;
  let authUser = null;

  // ── Load settings ──────────────────────────────────────────────────────────
  function loadSettings() {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: 'get-api-base' }, (resp) => {
        if (resp && resp.apiBase) API_BASE = resp.apiBase;
        chrome.runtime.sendMessage({ type: 'get-auth' }, (authResp) => {
          if (authResp && authResp.user) authUser = authResp.user;
          resolve();
        });
      });
    });
  }

  // ── API Client ──────────────────────────────────────────────────────────────
  function apiHeaders() {
    const h = { 'Content-Type': 'application/json' };
    if (authUser && authUser.access_token) {
      h['Authorization'] = `Bearer ${authUser.access_token}`;
    }
    return h;
  }

  async function apiHealth() {
    try {
      const res = await fetch(`${API_BASE}/api/health`);
      return res.ok;
    } catch { return false; }
  }

  async function apiAnalyze(url) {
    const res = await fetch(`${API_BASE}/api/repositories/analyze`, {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ url, force_reindex: false }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Analysis failed');
    }
    return res.json();
  }

  function apiProgressStream(repoId) {
    return new EventSource(`${API_BASE}/api/repositories/${repoId}/status`);
  }

  async function apiGetRepo(repoId) {
    const res = await fetch(`${API_BASE}/api/repositories/${repoId}`, { headers: apiHeaders() });
    if (!res.ok) throw new Error('Repository not found');
    return res.json();
  }

  async function apiChat(repoId, question, history, convId) {
    const res = await fetch(`${API_BASE}/api/repositories/${repoId}/chat`, {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({
        question,
        conversation_history: history,
        conversation_id: convId,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Chat failed');
    }
    return res.json();
  }

  // ── GitHub URL Parser ───────────────────────────────────────────────────────
  function parseGitHubUrl(url) {
    if (!url) return null;
    const match = url.match(
      /^https?:\/\/github\.com\/([a-zA-Z0-9_\-\.]+)\/([a-zA-Z0-9_\-\.]+)/
    );
    if (!match) return null;
    return {
      owner: match[1],
      name: match[2],
      url: `https://github.com/${match[1]}/${match[2]}`,
    };
  }

  // ── Read selected code ──────────────────────────────────────────────────────
  function getSelectedCode() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return null;

    const text = selection.toString().trim();
    if (!text || text.length < 5) return null;

    // Try to find the file path from GitHub's DOM
    let filePath = null;
    const fileHeader = document.querySelector('[data-testid="breadcrumb-filename"], .file-header .file-info');
    if (fileHeader) {
      filePath = fileHeader.textContent.trim();
    }

    return { code: text, filePath };
  }

  // ── Escape HTML ─────────────────────────────────────────────────────────────
  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  // ── Markdown-like rendering ─────────────────────────────────────────────────
  function renderMarkdown(text) {
    // Simple markdown rendering for code blocks and inline code
    let html = escapeHtml(text);

    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      return `<pre class="rr-code-block"><code class="language-${lang}">${code}</code></pre>`;
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code class="rr-inline-code">$1</code>');

    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // ── Build the Sidebar DOM ─────────────────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════════

  function buildSidebar() {
    // Toggle button (floating)
    const toggleBtn = document.createElement('button');
    toggleBtn.id = 'reporag-toggle';
    toggleBtn.innerHTML = '🔍';
    toggleBtn.title = 'Toggle RepoRAG Sidebar';
    document.body.appendChild(toggleBtn);

    // Sidebar container
    const sidebar = document.createElement('div');
    sidebar.id = 'reporag-sidebar';
    sidebar.classList.add('rr-closed');

    sidebar.innerHTML = `
      <div class="rr-header">
        <div class="rr-header-left">
          <span class="rr-logo">🔍</span>
          <span class="rr-title">RepoRAG</span>
        </div>
        <div class="rr-header-right">
          <button class="rr-btn-icon rr-btn-close" title="Close sidebar">✕</button>
        </div>
      </div>

      <div class="rr-status" id="rr-status">
        <span class="rr-status-dot rr-status-checking"></span>
        <span class="rr-status-text">Checking connection...</span>
      </div>

      <div class="rr-repo-banner" id="rr-repo-banner" style="display:none;">
        <div class="rr-repo-name" id="rr-repo-name"></div>
        <button class="rr-btn-small" id="rr-analyze-btn">Analyze</button>
      </div>

      <div class="rr-progress" id="rr-progress" style="display:none;">
        <div class="rr-progress-text" id="rr-progress-text">Initializing...</div>
        <div class="rr-progress-bar">
          <div class="rr-progress-fill" id="rr-progress-fill" style="width:0%"></div>
        </div>
      </div>

      <div class="rr-messages" id="rr-messages"></div>

      <div class="rr-input-area" id="rr-input-area" style="display:none;">
        <div class="rr-selection-hint" id="rr-selection-hint" style="display:none;">
          <span>📋 Code selected — it will be included as context</span>
          <button class="rr-btn-icon rr-clear-selection" title="Clear">✕</button>
        </div>
        <div class="rr-input-box">
          <textarea
            id="rr-question-input"
            placeholder="Ask about this repository..."
            rows="1"
          ></textarea>
          <button id="rr-send-btn" title="Send">➤</button>
        </div>
      </div>
    `;

    document.body.appendChild(sidebar);
    return { toggleBtn, sidebar };
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // ── Sidebar Logic ─────────────────────────────────────────────────────────────
  // ══════════════════════════════════════════════════════════════════════════════

  async function init() {
    await loadSettings();

    const { toggleBtn, sidebar } = buildSidebar();

    const statusDot = sidebar.querySelector('.rr-status-dot');
    const statusText = sidebar.querySelector('.rr-status-text');
    const repoBanner = sidebar.querySelector('#rr-repo-banner');
    const repoName = sidebar.querySelector('#rr-repo-name');
    const analyzeBtn = sidebar.querySelector('#rr-analyze-btn');
    const progressEl = sidebar.querySelector('#rr-progress');
    const progressText = sidebar.querySelector('#rr-progress-text');
    const progressFill = sidebar.querySelector('#rr-progress-fill');
    const messagesEl = sidebar.querySelector('#rr-messages');
    const inputArea = sidebar.querySelector('#rr-input-area');
    const questionInput = sidebar.querySelector('#rr-question-input');
    const sendBtn = sidebar.querySelector('#rr-send-btn');
    const closeBtn = sidebar.querySelector('.rr-btn-close');
    const selectionHint = sidebar.querySelector('#rr-selection-hint');
    const clearSelectionBtn = sidebar.querySelector('.rr-clear-selection');

    let selectedCode = null;

    // ── Toggle sidebar ──────────────────────────────────────────────────────
    function toggleSidebar() {
      sidebar.classList.toggle('rr-closed');
      toggleBtn.classList.toggle('rr-active');
    }

    toggleBtn.addEventListener('click', toggleSidebar);
    closeBtn.addEventListener('click', toggleSidebar);

    // ── Backend health check ────────────────────────────────────────────────
    const healthy = await apiHealth();
    if (healthy) {
      statusDot.className = 'rr-status-dot rr-status-ok';
      statusText.textContent = 'Connected to backend';
    } else {
      statusDot.className = 'rr-status-dot rr-status-error';
      statusText.textContent = 'Backend offline — start the server';
    }

    // Show auth status
    if (authUser) {
      statusText.textContent = `Connected • ${authUser.login}`;
    }

    // ── Detect current repo ─────────────────────────────────────────────────
    function detectRepo() {
      const repo = parseGitHubUrl(window.location.href);
      if (repo) {
        currentRepo = repo;
        repoName.textContent = `${repo.owner}/${repo.name}`;
        repoBanner.style.display = 'flex';
      } else {
        repoBanner.style.display = 'none';
        currentRepo = null;
      }
    }

    detectRepo();

    // ── Listen for URL changes (SPA navigation) ─────────────────────────────
    const observer = new MutationObserver(() => {
      const newRepo = parseGitHubUrl(window.location.href);
      if (newRepo && (!currentRepo || newRepo.url !== currentRepo.url)) {
        currentRepo = newRepo;
        repoName.textContent = `${newRepo.owner}/${newRepo.name}`;
        repoBanner.style.display = 'flex';
      }
    });
    observer.observe(document.querySelector('head > title') || document.head, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    // ── Code selection detection ────────────────────────────────────────────
    document.addEventListener('mouseup', () => {
      const sel = getSelectedCode();
      if (sel) {
        selectedCode = sel;
        selectionHint.style.display = 'flex';
      }
    });

    clearSelectionBtn.addEventListener('click', () => {
      selectedCode = null;
      selectionHint.style.display = 'none';
    });

    // ── Analyze button ──────────────────────────────────────────────────────
    analyzeBtn.addEventListener('click', async () => {
      if (!currentRepo) return;
      analyzeBtn.disabled = true;
      analyzeBtn.textContent = '...';

      try {
        const result = await apiAnalyze(currentRepo.url);
        currentRepoId = result.repository_id;
        conversationId = null;
        conversationHistory = [];

        // Show progress
        progressEl.style.display = 'block';
        messagesEl.innerHTML = '';
        inputArea.style.display = 'none';

        // Open progress stream
        const es = apiProgressStream(currentRepoId);
        es.onmessage = async (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.status === 'stream_end') {
              es.close();
              return;
            }

            progressText.textContent = data.message;
            progressFill.style.width = `${data.progress || 0}%`;

            if (data.status === 'ready' || data.status === 'cached') {
              es.close();
              progressEl.style.display = 'none';
              inputArea.style.display = 'block';

              // Show welcome message
              try {
                const meta = await apiGetRepo(currentRepoId);
                appendMessage('assistant',
                  `🎉 <strong>${escapeHtml(meta.owner)}/${escapeHtml(meta.name)}</strong> is ready!<br><br>` +
                  `I've analyzed this repository (${meta.stats?.indexed_files || 0} files, ${meta.stats?.total_chunks || 0} chunks). Ask me anything!<br><br>` +
                  buildSuggestionButtons()
                );
              } catch {
                appendMessage('assistant', '✅ Repository ready! Ask me anything.');
              }
            } else if (data.status === 'failed') {
              es.close();
              progressEl.style.display = 'none';
              appendMessage('error', data.message);
            }
          } catch {}
        };

        es.onerror = () => es.close();

      } catch (err) {
        appendMessage('error', err.message);
      } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Analyze';
      }
    });

    // ── Suggestion buttons ──────────────────────────────────────────────────
    const SUGGESTIONS = [
      'What does this project do?',
      'Explain the architecture.',
      'How does it work end-to-end?',
      'What are the main technologies used?',
      'How do I run this project?',
      'What are the main APIs?',
    ];

    function buildSuggestionButtons() {
      return SUGGESTIONS.map(q =>
        `<button class="rr-suggestion-btn" data-question="${escapeHtml(q)}">${escapeHtml(q)}</button>`
      ).join('');
    }

    // ── Message rendering ───────────────────────────────────────────────────
    function appendMessage(type, content, sources) {
      const group = document.createElement('div');
      group.className = `rr-message-group rr-${type}`;

      const msg = document.createElement('div');
      msg.className = `rr-message rr-${type}`;

      if (type === 'user') {
        msg.textContent = content;
      } else if (type === 'error') {
        msg.innerHTML = `<span class="rr-error">⚠️ ${escapeHtml(content)}</span>`;
      } else {
        msg.innerHTML = renderMarkdown(content);

        // Source chips
        if (sources && sources.length > 0) {
          const sourcesEl = document.createElement('div');
          sourcesEl.className = 'rr-sources';
          sourcesEl.innerHTML = '<div class="rr-sources-label">📎 Sources</div>';
          const chips = document.createElement('div');
          chips.className = 'rr-source-chips';
          sources.forEach(src => {
            const chip = document.createElement('span');
            chip.className = 'rr-source-chip';
            const lines = src.start_line ? `:${src.start_line}-${src.end_line}` : '';
            chip.textContent = `${src.file_path}${lines}`;
            chip.title = src.symbol ? `Symbol: ${src.symbol}` : src.file_path;
            chips.appendChild(chip);
          });
          sourcesEl.appendChild(chips);
          msg.appendChild(sourcesEl);
        }
      }

      group.appendChild(msg);
      messagesEl.appendChild(group);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function appendTyping() {
      const group = document.createElement('div');
      group.className = 'rr-message-group rr-assistant';
      group.id = 'rr-typing';
      group.innerHTML = `<div class="rr-typing">
        <div class="rr-typing-dot"></div>
        <div class="rr-typing-dot"></div>
        <div class="rr-typing-dot"></div>
      </div>`;
      messagesEl.appendChild(group);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return group;
    }

    function removeTyping() {
      const el = document.getElementById('rr-typing');
      if (el) el.remove();
    }

    // ── Send message ────────────────────────────────────────────────────────
    async function sendMessage(question) {
      if (!question.trim() || isSending || !currentRepoId) return;
      isSending = true;
      sendBtn.disabled = true;

      // Build question with context if code is selected
      let fullQuestion = question;
      if (selectedCode) {
        const filePart = selectedCode.filePath ? ` from \`${selectedCode.filePath}\`` : '';
        fullQuestion = `Given this code${filePart}:\n\`\`\`\n${selectedCode.code}\n\`\`\`\n\n${question}`;
        selectedCode = null;
        selectionHint.style.display = 'none';
      }

      appendMessage('user', question);
      questionInput.value = '';
      questionInput.style.height = 'auto';
      const typingEl = appendTyping();

      conversationHistory.push({ role: 'user', content: fullQuestion });

      try {
        const response = await apiChat(
          currentRepoId,
          fullQuestion,
          conversationHistory.slice(0, -1),
          conversationId,
        );

        conversationId = response.conversation_id;
        conversationHistory.push({ role: 'assistant', content: response.answer });

        removeTyping();
        appendMessage('assistant', response.answer, response.sources);

      } catch (err) {
        removeTyping();
        appendMessage('error', err.message);
        conversationHistory.pop();
      } finally {
        isSending = false;
        sendBtn.disabled = false;
        questionInput.focus();
      }
    }

    // ── Input event handlers ────────────────────────────────────────────────
    sendBtn.addEventListener('click', () => {
      const q = questionInput.value.trim();
      if (q) sendMessage(q);
    });

    questionInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const q = questionInput.value.trim();
        if (q) sendMessage(q);
      }
    });

    questionInput.addEventListener('input', () => {
      questionInput.style.height = 'auto';
      questionInput.style.height = Math.min(questionInput.scrollHeight, 100) + 'px';
    });

    // ── Suggestion button clicks (event delegation) ──────────────────────────
    messagesEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.rr-suggestion-btn');
      if (btn) {
        const q = btn.dataset.question;
        if (q) sendMessage(q);
      }
    });

    // ── Listen for messages from background ──────────────────────────────────
    chrome.runtime.onMessage.addListener((message) => {
      if (message.type === 'repo-detected') {
        currentRepo = message.repo;
        repoName.textContent = `${message.repo.owner}/${message.repo.name}`;
        repoBanner.style.display = 'flex';
      }
      if (message.type === 'auth-changed') {
        authUser = message.user;
        if (authUser) {
          statusText.textContent = `Connected • ${authUser.login}`;
        }
      }
    });
  }

  // ── Initialize ──────────────────────────────────────────────────────────────
  init();
})();
