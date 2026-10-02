/**
 * background.js — Service worker for the RepoRAG Chrome Extension.
 *
 * Responsibilities:
 *   - Detect when the user navigates to a GitHub repo page
 *   - Notify the content script of the current repo context
 *   - Handle messages from the popup and content scripts
 *   - Store user auth state
 */

const API_BASE_KEY = 'reporag_api_base';
const DEFAULT_API_BASE = 'https://reporag-backend-r1ye.onrender.com';

// ── Tab URL monitoring ────────────────────────────────────────────────────────

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

// Listen for tab URL changes and notify content scripts
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    const repo = parseGitHubUrl(tab.url);
    if (repo) {
      chrome.tabs.sendMessage(tabId, {
        type: 'repo-detected',
        repo,
      }).catch(() => {});
    }
  }
});

// ── Message handling ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'get-api-base') {
    chrome.storage.local.get(API_BASE_KEY, (result) => {
      sendResponse({ apiBase: result[API_BASE_KEY] || DEFAULT_API_BASE });
    });
    return true; // async response
  }

  if (message.type === 'set-api-base') {
    chrome.storage.local.set({ [API_BASE_KEY]: message.apiBase }, () => {
      sendResponse({ success: true });
    });
    return true;
  }

  if (message.type === 'get-auth') {
    chrome.storage.local.get('reporag_user', (result) => {
      sendResponse({ user: result.reporag_user || null });
    });
    return true;
  }

  if (message.type === 'set-auth') {
    chrome.storage.local.set({ reporag_user: message.user }, () => {
      sendResponse({ success: true });
    });
    return true;
  }

  if (message.type === 'clear-auth') {
    chrome.storage.local.remove('reporag_user', () => {
      sendResponse({ success: true });
    });
    return true;
  }

  // OAuth callback message from the callback HTML page
  if (message.type === 'github-oauth-success') {
    chrome.storage.local.set({ reporag_user: message.user }, () => {
      // Notify all tabs that auth changed
      chrome.tabs.query({ url: 'https://github.com/*' }, (tabs) => {
        tabs.forEach((tab) => {
          chrome.tabs.sendMessage(tab.id, {
            type: 'auth-changed',
            user: message.user,
          }).catch(() => {});
        });
      });
    });
  }
});
