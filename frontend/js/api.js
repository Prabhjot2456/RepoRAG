/**
 * api.js — API client for the GitHub RAG backend.
 */

const API_BASE = 'http://localhost:8000';

const API = {
  /**
   * Start repository ingestion.
   * @returns {Promise<{repository_id, status, message}>}
   */
  async analyzeRepository(url, forceReindex = false) {
    const res = await fetch(`${API_BASE}/api/repositories/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, force_reindex: forceReindex }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Failed to start analysis');
    }
    return res.json();
  },

  /**
   * Open an EventSource for SSE progress updates.
   * @returns {EventSource}
   */
  openProgressStream(repositoryId) {
    return new EventSource(`${API_BASE}/api/repositories/${repositoryId}/status`);
  },

  /**
   * Get repository metadata.
   */
  async getRepository(repositoryId) {
    const res = await fetch(`${API_BASE}/api/repositories/${repositoryId}`);
    if (!res.ok) throw new Error('Repository not found');
    return res.json();
  },

  /**
   * List all indexed repositories.
   */
  async listRepositories() {
    const res = await fetch(`${API_BASE}/api/repositories`);
    if (!res.ok) throw new Error('Failed to list repositories');
    return res.json();
  },

  /**
   * Delete a repository index.
   */
  async deleteRepository(repositoryId) {
    const res = await fetch(`${API_BASE}/api/repositories/${repositoryId}`, {
      method: 'DELETE',
    });
    if (!res.ok && res.status !== 204) throw new Error('Failed to delete repository');
  },

  /**
   * Get file tree.
   */
  async getFileTree(repositoryId) {
    const res = await fetch(`${API_BASE}/api/repositories/${repositoryId}/files`);
    if (!res.ok) throw new Error('Failed to load file tree');
    return res.json();
  },

  /**
   * Get file content.
   */
  async getFileContent(repositoryId, filePath) {
    const res = await fetch(
      `${API_BASE}/api/repositories/${repositoryId}/files/${encodeURIComponent(filePath)}`
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'File not found');
    }
    return res.json();
  },

  /**
   * Ask a question about the repository.
   */
  async chat(repositoryId, question, conversationHistory = [], conversationId = null) {
    const res = await fetch(`${API_BASE}/api/repositories/${repositoryId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        conversation_history: conversationHistory,
        conversation_id: conversationId,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Chat request failed');
    }
    return res.json();
  },

  /**
   * Generate a project overview.
   */
  async generateOverview(repositoryId) {
    const res = await fetch(`${API_BASE}/api/repositories/${repositoryId}/overview`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error('Overview generation failed');
    return res.json();
  },

  /**
   * Check backend health.
   */
  async health() {
    const res = await fetch(`${API_BASE}/api/health`);
    return res.ok;
  },

  /**
   * Check LLM health.
   */
  async llmHealth() {
    const res = await fetch(`${API_BASE}/api/health/llm`);
    if (!res.ok) return { reachable: false };
    return res.json();
  },
};
