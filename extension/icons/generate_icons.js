/**
 * generate_icons.js — Generate proper PNG icons for the extension.
 * Run with: node generate_icons.js
 */
const fs = require('fs');
const { createCanvas } = (() => {
  // Fallback: generate simple SVG-based icons when canvas isn't available
  return {
    createCanvas: null
  };
})();

// SVG icon template
function createSvgIcon(size) {
  const s = size;
  const pad = Math.round(s * 0.1);
  const inner = s - pad * 2;
  
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#6366f1"/>
      <stop offset="100%" stop-color="#4f46e5"/>
    </linearGradient>
  </defs>
  <rect width="${s}" height="${s}" rx="${Math.round(s*0.18)}" fill="url(#bg)"/>
  <text x="${s/2}" y="${s*0.62}" text-anchor="middle" 
        font-family="monospace" font-weight="bold" font-size="${inner*0.5}px" fill="white" opacity="0.9">{ }</text>
  <circle cx="${s/2}" cy="${s*0.48}" r="${inner*0.16}" fill="none" stroke="white" stroke-width="${Math.max(1.5, s*0.04)}" opacity="0.95"/>
  <line x1="${s*0.55}" y1="${s*0.58}" x2="${s*0.68}" y2="${s*0.72}" 
        stroke="white" stroke-width="${Math.max(1.5, s*0.04)}" stroke-linecap="round" opacity="0.95"/>
</svg>`;
}

// Generate SVG files (Chrome accepts SVG via data URIs, but for icons we need PNG)
// Since we can't easily generate PNG without canvas, we'll create SVG files
const sizes = [16, 32, 48, 128];

sizes.forEach(size => {
  const svg = createSvgIcon(size);
  const path = __dirname + `/icon${size}.svg`;
  fs.writeFileSync(path, svg);
  console.log(`Generated icon${size}.svg`);
});

console.log('Done! Icons generated as SVG files.');
