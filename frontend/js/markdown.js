/**
 * markdown.js — Markdown rendering with syntax highlighting.
 * Uses marked.js + highlight.js (loaded via CDN in index.html).
 */

const MarkdownRenderer = (() => {
  let _ready = false;

  function init() {
    if (typeof marked === 'undefined') return;

    marked.setOptions({
      highlight(code, lang) {
        if (typeof hljs !== 'undefined') {
          try {
            if (lang && hljs.getLanguage(lang)) {
              return hljs.highlight(code, { language: lang }).value;
            }
            return hljs.highlightAuto(code).value;
          } catch (_) {}
        }
        return code;
      },
      langPrefix: 'hljs language-',
      breaks: true,
      gfm: true,
    });

    _ready = true;
  }

  function render(text) {
    if (!_ready) init();
    if (typeof marked === 'undefined') {
      // Fallback: basic escaping
      return text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
    }
    try {
      return marked.parse(text);
    } catch (_) {
      return text;
    }
  }

  // Apply hljs to a DOM element's code blocks after rendering
  function highlight(container) {
    if (typeof hljs === 'undefined') return;
    container.querySelectorAll('pre code').forEach(block => {
      hljs.highlightElement(block);
    });
  }

  return { init, render, highlight };
})();
