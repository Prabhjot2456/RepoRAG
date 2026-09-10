/**
 * explorer.js — File explorer UI for the sidebar.
 */

const Explorer = (() => {
  let currentRepoId = null;
  let selectedPath = null;

  const $ = id => document.getElementById(id);

  // Language → emoji icon
  const LANG_ICONS = {
    python: '🐍', javascript: '🟨', typescript: '🔷', java: '☕',
    go: '🐹', rust: '🦀', ruby: '💎', php: '🐘', cpp: '⚙️',
    c: '⚙️', csharp: '🔷', swift: '🍎', kotlin: '🟣', scala: '🔴',
    markdown: '📝', json: '📋', yaml: '📋', toml: '📋',
    html: '🌐', css: '🎨', scss: '🎨',
    sql: '🗄️', bash: '💻', dockerfile: '🐳', text: '📄',
    default: '📄',
  };

  const DIR_ICONS = { open: '📂', closed: '📁' };

  function getIcon(node) {
    if (node.type === 'directory') return DIR_ICONS.closed;
    return LANG_ICONS[node.language] || LANG_ICONS.default;
  }

  // ── Load & render ─────────────────────────────────────────────────────────
  async function load(repoId) {
    currentRepoId = repoId;
    const container = document.getElementById('file-tree-container');
    container.innerHTML = '<div style="color:var(--text-muted);font-size:.8rem;padding:8px">Loading files...</div>';

    try {
      const tree = await API.getFileTree(repoId);
      container.innerHTML = '';
      renderTree(tree, container);
    } catch (err) {
      container.innerHTML = `<div style="color:var(--accent-error);font-size:.8rem;padding:8px">Failed to load file tree: ${err.message}</div>`;
    }
  }

  function renderTree(nodes, container, depth = 0) {
    nodes.forEach(node => {
      const nodeEl = document.createElement('div');
      nodeEl.className = 'tree-node';

      const label = document.createElement('div');
      label.className = 'tree-node-label';
      label.style.paddingLeft = `${depth * 8}px`;

      const icon = document.createElement('span');
      icon.className = 'node-icon';
      icon.textContent = getIcon(node);

      const name = document.createElement('span');
      name.className = 'node-name';
      name.textContent = node.name;

      label.appendChild(icon);
      label.appendChild(name);

      if (node.type === 'directory' && node.children && node.children.length > 0) {
        const toggle = document.createElement('span');
        toggle.className = 'tree-node-toggle';
        toggle.textContent = '▶';
        label.insertBefore(toggle, icon);

        const childContainer = document.createElement('div');
        childContainer.className = 'tree-node-children';
        childContainer.style.display = 'none';

        label.addEventListener('click', () => {
          const open = childContainer.style.display !== 'none';
          childContainer.style.display = open ? 'none' : 'block';
          toggle.classList.toggle('open', !open);
          icon.textContent = open ? DIR_ICONS.closed : DIR_ICONS.open;
        });

        renderTree(node.children, childContainer, depth + 1);
        nodeEl.appendChild(label);
        nodeEl.appendChild(childContainer);

      } else if (node.type === 'file') {
        label.addEventListener('click', () => {
          openFile(node.path, node.language);
          // Highlight selected
          document.querySelectorAll('.tree-node-label').forEach(el => el.classList.remove('selected'));
          label.classList.add('selected');
          selectedPath = node.path;
        });

        nodeEl.appendChild(label);
      } else {
        // Empty directory
        const dummyToggle = document.createElement('span');
        dummyToggle.className = 'tree-node-toggle';
        dummyToggle.style.visibility = 'hidden';
        label.insertBefore(dummyToggle, icon);
        nodeEl.appendChild(label);
      }

      container.appendChild(nodeEl);
    });
  }

  // ── Open file ─────────────────────────────────────────────────────────────
  async function openFile(filePath, language) {
    if (!currentRepoId) return;

    // Show file viewer panel
    document.getElementById('chat-messages').classList.add('hidden');
    document.getElementById('chat-input-area').classList.add('hidden');
    const viewer = document.getElementById('file-viewer');
    viewer.classList.remove('hidden');

    viewer.querySelector('.file-path').textContent = filePath;
    const contentEl = viewer.querySelector('.file-viewer-content');
    contentEl.innerHTML = '<div style="color:var(--text-muted);padding:12px">Loading...</div>';

    try {
      const data = await API.getFileContent(currentRepoId, filePath);
      const lang = language || data.language || '';

      let highlighted = data.content;
      if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
        try {
          highlighted = hljs.highlight(data.content, { language: lang }).value;
        } catch (_) {
          highlighted = _escape(data.content);
        }
      } else {
        highlighted = _escape(data.content);
      }

      contentEl.innerHTML = `<pre class="hljs"><code class="language-${lang}">${highlighted}</code></pre>`;

    } catch (err) {
      contentEl.innerHTML = `<div style="color:var(--accent-error);padding:12px">⚠️ ${err.message}</div>`;
    }
  }

  function closeFileViewer() {
    document.getElementById('file-viewer').classList.add('hidden');
    document.getElementById('chat-messages').classList.remove('hidden');
    document.getElementById('chat-input-area').classList.remove('hidden');
    selectedPath = null;
    document.querySelectorAll('.tree-node-label').forEach(el => el.classList.remove('selected'));
  }

  function _escape(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  return { load, openFile, closeFileViewer };
})();
