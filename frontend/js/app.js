/**
 * app.js — Main application controller.
 */

const App = (() => {
  let currentRepoId = null;
  let currentRepoMeta = null;
  let progressEventSource = null;

  const $ = id => document.getElementById(id);

  const SUGGESTIONS = [
    'What does this project do?',
    'Explain the architecture.',
    'How does the application work end-to-end?',
    'What are the main technologies used?',
    'Explain the folder structure.',
    'How do I run this project?',
    'Where is authentication implemented?',
    'What are the main APIs?',
    'What database does this project use?',
    'Explain the most important files.',
  ];

  // ── Startup ───────────────────────────────────────────────────────────────
  async function init() {
    MarkdownRenderer.init();
    _bindEvents();
    await _checkBackendHealth();
    _showLanding();
    _loadRecentRepositories();
  }

  async function _checkBackendHealth() {
    try {
      const ok = await API.health();
      if (!ok) _toast('Backend not reachable. Is the server running on port 8000?', 'error', 6000);
    } catch (_) {
      _toast('Cannot connect to backend. Start the server with: python -m uvicorn app.main:app', 'error', 8000);
    }
  }

  // ── Landing ───────────────────────────────────────────────────────────────
  function _showLanding() {
    $('landing').classList.remove('hidden');
    $('workspace').classList.add('hidden');
  }

  function _showWorkspace() {
    $('landing').classList.add('hidden');
    $('workspace').classList.remove('hidden');
  }

  async function _loadRecentRepositories() {
    try {
      const repos = await API.listRepositories();
      if (repos.length === 0) return;
      const ready = repos.filter(r => r.status === 'ready');
      if (ready.length === 0) return;

      // Show recent chips on landing
      const container = $('recent-repos');
      if (!container) return;
      container.innerHTML = '<div style="font-size:.8rem;color:var(--text-muted);margin-bottom:8px">Recent repositories:</div>';

      ready.slice(0, 5).forEach(repo => {
        const chip = document.createElement('div');
        chip.className = 'example-chip';
        chip.textContent = `${repo.owner}/${repo.name}`;
        chip.title = repo.url;
        chip.addEventListener('click', () => {
          $('repo-url-input').value = repo.url;
          _loadExistingRepository(repo.repository_id, repo.url);
        });
        container.appendChild(chip);
      });
    } catch (_) {}
  }

  // ── Analyze ───────────────────────────────────────────────────────────────
  async function analyzeRepository() {
    const url = $('repo-url-input').value.trim();
    if (!url) {
      _toast('Please enter a GitHub repository URL', 'error');
      return;
    }

    const btn = $('analyze-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Analyzing...';

    try {
      const result = await API.analyzeRepository(url);
      currentRepoId = result.repository_id;

      _showWorkspace();
      _showProgress('Initializing analysis...', 0);
      _openProgressStream(currentRepoId);

    } catch (err) {
      _toast(err.message, 'error', 6000);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '🔍 Analyze';
    }
  }

  async function _loadExistingRepository(repoId, url) {
    currentRepoId = repoId;
    _showWorkspace();

    // Attempt to re-use cached — trigger ingestion (will detect cache hit)
    const btn = $('analyze-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';

    try {
      await API.analyzeRepository(url);
      _showProgress('Checking for updates...', 0);
      _openProgressStream(repoId);
    } catch (err) {
      _toast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = '🔍 Analyze';
    }
  }

  // ── Progress stream ────────────────────────────────────────────────────────
  function _openProgressStream(repoId) {
    if (progressEventSource) {
      progressEventSource.close();
    }

    progressEventSource = API.openProgressStream(repoId);

    progressEventSource.onmessage = async (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.status === 'stream_end') {
          progressEventSource.close();
          return;
        }

        _updateProgressStep(data.status, data.message, data.progress || 0);

        if (data.status === 'ready' || data.status === 'cached') {
          progressEventSource.close();
          await _onRepositoryReady(repoId);
        } else if (data.status === 'failed') {
          progressEventSource.close();
          _toast(data.message, 'error', 8000);
        }
      } catch (_) {}
    };

    progressEventSource.onerror = () => {
      progressEventSource.close();
    };
  }

  function _showProgress(message, progress) {
    $('progress-overlay').classList.remove('hidden');
    $('chat-messages').classList.add('hidden');
    $('chat-input-area').classList.add('hidden');
    $('file-viewer').classList.add('hidden');

    const fill = document.querySelector('.progress-bar-fill');
    if (fill) fill.style.width = `${progress}%`;

    const steps = document.querySelector('.progress-steps');
    if (steps) {
      steps.innerHTML = `<div class="progress-step active"><span class="step-icon">⏳</span>${_escape(message)}</div>`;
    }
  }

  const STATUS_ORDER = [
    'fetching', 'scanning', 'parsing', 'chunking',
    'embedding', 'indexing', 'summarizing', 'ready', 'cached'
  ];
  const STATUS_LABELS = {
    pending: 'Initializing', fetching: '🌐 Fetching repository',
    scanning: '🔍 Scanning files', parsing: '📖 Parsing files',
    chunking: '✂️ Creating chunks', embedding: '🧠 Generating embeddings',
    indexing: '💾 Building index', summarizing: '📊 Finalizing',
    ready: '✅ Ready', cached: '✅ Ready (cached)', failed: '❌ Failed',
  };

  let _progressLog = [];

  function _updateProgressStep(status, message, progress) {
    // Add to log
    _progressLog.push({ status, message });

    // Update bar
    const fill = document.querySelector('.progress-bar-fill');
    if (fill) fill.style.width = `${progress}%`;

    // Rebuild steps list
    const stepsEl = document.querySelector('.progress-steps');
    if (!stepsEl) return;
    stepsEl.innerHTML = '';

    _progressLog.forEach((entry, i) => {
      const step = document.createElement('div');
      const isLast = i === _progressLog.length - 1;
      const isDone = !isLast && !['failed'].includes(entry.status);
      const isFailed = entry.status === 'failed';

      step.className = `progress-step ${isDone ? 'done' : isLast ? 'active' : ''}  ${isFailed ? 'failed' : ''}`;
      step.innerHTML = `<span class="step-icon">${isDone ? '✓' : isFailed ? '✗' : '⏳'}</span>${_escape(entry.message)}`;
      stepsEl.appendChild(step);
    });

    stepsEl.scrollTop = stepsEl.scrollHeight;
  }

  // ── Repository ready ───────────────────────────────────────────────────────
  async function _onRepositoryReady(repoId) {
    _progressLog = [];
    try {
      const meta = await API.getRepository(repoId);
      currentRepoMeta = meta;

      _populateSidebar(meta);
      await Explorer.load(repoId);

      // Switch to chat
      Chat.init(repoId, meta);
      $('progress-overlay').classList.add('hidden');

      Chat.showWelcome(`${meta.owner}/${meta.name}`, SUGGESTIONS.slice(0, 6));

    } catch (err) {
      _toast('Failed to load repository data: ' + err.message, 'error');
    }
  }

  // ── Sidebar ────────────────────────────────────────────────────────────────
  function _populateSidebar(meta) {
    // Info tab
    const infoPanel = $('sidebar-info');
    const stats = meta.stats || {};
    const techs = (meta.technologies || []).slice(0, 12);

    infoPanel.innerHTML = `
      <div class="repo-info-card">
        <h3>${_escape(meta.name || 'Unknown')}</h3>
        <div class="repo-owner">by ${_escape(meta.owner || 'Unknown')}</div>
        ${meta.description ? `<div class="repo-desc">${_escape(meta.description)}</div>` : ''}
        <div class="repo-stats">
          <div class="stat-item"><div class="stat-value">${stats.indexed_files || 0}</div><div class="stat-label">Files</div></div>
          <div class="stat-item"><div class="stat-value">${_fmtNum(stats.total_chunks)}</div><div class="stat-label">Chunks</div></div>
          <div class="stat-item"><div class="stat-value">${_fmtNum(stats.total_lines)}</div><div class="stat-label">Lines</div></div>
          <div class="stat-item"><div class="stat-value">${meta.stars != null ? _fmtNum(meta.stars) : '—'}</div><div class="stat-label">Stars</div></div>
        </div>
        ${techs.length ? `<div class="tech-chips">${techs.map(t => `<span class="tech-chip">${_escape(t.name)}</span>`).join('')}</div>` : ''}
      </div>

      <div class="suggested-questions">
        <h4>Quick Questions</h4>
        ${SUGGESTIONS.map(q => `<button class="suggestion-btn" onclick="App.askSuggestion('${q.replace(/'/g, "\\'")}')">${_escape(q)}</button>`).join('')}
      </div>
    `;
  }

  // ── Event bindings ─────────────────────────────────────────────────────────
  function _bindEvents() {
    // Analyze button
    $('analyze-btn').addEventListener('click', analyzeRepository);

    // Hero CTA analyze button
    const heroBtn = $('hero-analyze-btn');
    if (heroBtn) {
      heroBtn.addEventListener('click', () => {
        const heroUrl = $('hero-repo-url').value.trim();
        if (heroUrl) $('repo-url-input').value = heroUrl;
        analyzeRepository();
      });
    }

    // Enter key in URL input
    $('repo-url-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') analyzeRepository();
    });

    // Enter key in hero URL input
    const heroInput = $('hero-repo-url');
    if (heroInput) {
      heroInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          $('repo-url-input').value = heroInput.value.trim();
          analyzeRepository();
        }
      });
      // Sync hero input with header input
      heroInput.addEventListener('input', () => {
        $('repo-url-input').value = heroInput.value;
      });
    }

    // Send button
    $('send-btn').addEventListener('click', () => {
      const q = $('question-input').value.trim();
      if (q) Chat.sendMessage(q);
    });

    // Enter key in question input (Shift+Enter = newline)
    $('question-input').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const q = $('question-input').value.trim();
        if (q) Chat.sendMessage(q);
      }
    });

    // Auto-resize textarea
    $('question-input').addEventListener('input', () => {
      const el = $('question-input');
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    });

    // Sidebar tabs
    document.querySelectorAll('.sidebar-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.sidebar-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        $('sidebar-' + tab.dataset.tab).classList.add('active');
      });
    });

    // Source modal close
    $('source-modal').addEventListener('click', e => {
      if (e.target === $('source-modal')) _closeSourceModal();
    });
    document.querySelector('.modal-close').addEventListener('click', _closeSourceModal);

    // File viewer back button
    const backBtn = document.getElementById('file-viewer-back');
    if (backBtn) backBtn.addEventListener('click', Explorer.closeFileViewer);

    // Keyboard shortcuts
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        _closeSourceModal();
        Explorer.closeFileViewer();
      }
    });

    // Example chips on landing
    document.querySelectorAll('.example-chip[data-url]').forEach(chip => {
      chip.addEventListener('click', () => {
        $('repo-url-input').value = chip.dataset.url;
        const heroUrlInput = $('hero-repo-url');
        if (heroUrlInput) heroUrlInput.value = chip.dataset.url;
      });
    });
  }

  function _closeSourceModal() {
    $('source-modal').classList.add('hidden');
  }

  // ── Public: ask a suggestion ───────────────────────────────────────────────
  function askSuggestion(question) {
    // Switch to chat view if file viewer is open
    Explorer.closeFileViewer();
    $('question-input').value = question;
    Chat.sendMessage(question);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function _toast(message, type = 'info', duration = 4000) {
    const container = $('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icons = { error: '⚠️', success: '✓', info: 'ℹ️' };
    toast.innerHTML = `<span>${icons[type] || ''}</span><span>${_escape(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), duration);
  }

  function _escape(str) {
    return String(str || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _fmtNum(n) {
    if (n == null) return '0';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
  }

  return { init, analyzeRepository, askSuggestion };
})();

document.addEventListener('DOMContentLoaded', () => App.init());
