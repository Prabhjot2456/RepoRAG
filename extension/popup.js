/**
 * popup.js — Logic for the RepoRAG extension popup.
 *
 * Manages:
 *   - Backend URL configuration & connection testing
 *   - GitHub OAuth login/logout
 */

const DEFAULT_API_BASE = 'http://localhost:8000';

const $ = (id) => document.getElementById(id);

// ── Initialize ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  // Load saved API base
  chrome.runtime.sendMessage({ type: 'get-api-base' }, (resp) => {
    const apiBase = resp?.apiBase || DEFAULT_API_BASE;
    $('api-base-input').value = apiBase;
    checkConnection(apiBase);
  });

  // Load auth state
  chrome.runtime.sendMessage({ type: 'get-auth' }, (resp) => {
    if (resp?.user) {
      showLoggedIn(resp.user);
    } else {
      showLoggedOut();
    }
  });

  // Save button
  $('save-btn').addEventListener('click', () => {
    const apiBase = $('api-base-input').value.trim() || DEFAULT_API_BASE;
    chrome.runtime.sendMessage({ type: 'set-api-base', apiBase }, () => {
      checkConnection(apiBase);
    });
  });

  // Login button
  $('login-btn').addEventListener('click', async () => {
    const apiBase = $('api-base-input').value.trim() || DEFAULT_API_BASE;
    try {
      const res = await fetch(`${apiBase}/api/auth/github/login`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || 'OAuth not configured on the server.');
        return;
      }
      const data = await res.json();
      // Open GitHub OAuth in a new window
      const authWindow = window.open(data.url, 'GitHub Login', 'width=600,height=700');

      // Listen for the OAuth callback
      window.addEventListener('message', (event) => {
        if (event.data?.type === 'github-oauth-success') {
          chrome.runtime.sendMessage({
            type: 'set-auth',
            user: event.data.user,
          }, () => {
            showLoggedIn(event.data.user);
          });
        }
      });
    } catch (err) {
      alert('Failed to start OAuth flow. Is the backend running?');
    }
  });

  // Logout button
  $('logout-btn').addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'clear-auth' }, () => {
      showLoggedOut();
    });
  });
});

// ── Connection check ──────────────────────────────────────────────────────────

async function checkConnection(apiBase) {
  const statusEl = $('connection-status');
  const dot = statusEl.querySelector('.status-dot');
  const text = statusEl.querySelector('.status-text');

  dot.className = 'status-dot status-checking';
  text.textContent = 'Checking...';

  try {
    const res = await fetch(`${apiBase}/api/health`, { signal: AbortSignal.timeout(5000) });
    if (res.ok) {
      dot.className = 'status-dot status-ok';
      text.textContent = 'Connected to backend';
    } else {
      dot.className = 'status-dot status-error';
      text.textContent = `Backend returned ${res.status}`;
    }
  } catch {
    dot.className = 'status-dot status-error';
    text.textContent = 'Backend offline';
  }
}

// ── Auth UI ───────────────────────────────────────────────────────────────────

function showLoggedIn(user) {
  $('auth-logged-out').style.display = 'none';
  $('auth-logged-in').style.display = 'block';
  $('user-name').textContent = user.name || user.login;
  $('user-login').textContent = `@${user.login}`;
  if (user.avatar_url) {
    $('user-avatar').src = user.avatar_url;
  }
}

function showLoggedOut() {
  $('auth-logged-out').style.display = 'block';
  $('auth-logged-in').style.display = 'none';
}
