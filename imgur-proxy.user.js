// ==UserScript==
// @name         Yummy Imgur Proxy
// @namespace    https://imgur-uk.vercel.app
// @author       YY7MII
// @version      0.1.0
// @description  Proxy all i.imgur.com links (img + CSS) through imgur-uk.vercel.app
// @match        http://*/*
// @match        https://*/*
// @run-at       document-end
// @grant        none
// @updateURL    https://raw.githubusercontent.com/YY7MII/imgur-uk/main/imgur-proxy.user.js
// @downloadURL  https://raw.githubusercontent.com/YY7MII/imgur-uk/main/imgur-proxy.user.js
// @homepageURL  https://github.com/YY7MII/imgur-uk
// @noframes
// ==/UserScript==

(function() {
  'use strict';

  const FROM = 'i.imgur.com';
  const TO = 'imgur-uk.vercel.app';

  function replaceUrl(str) {
    return str.replaceAll(FROM, TO);
  }

  // --- 1. Rewrite <img> elements ---
  function fixImages(root = document) {
    root.querySelectorAll('img[src*="' + FROM + '"]').forEach(img => {
      img.src = replaceUrl(img.src);
    });
  }

  // --- 2. Rewrite inline <style> blocks ---
  function fixInlineStyles() {
    document.querySelectorAll('style').forEach(style => {
      if (style.textContent.includes(FROM)) {
        style.textContent = replaceUrl(style.textContent);
      }
    });
  }

  // --- 3. Rewrite style="" attributes ---
  function fixStyleAttributes(root = document) {
    root.querySelectorAll('[style*="' + FROM + '"]').forEach(el => {
      el.setAttribute('style', replaceUrl(el.getAttribute('style')));
    });
  }

  // --- 4. Rewrite external CSS files dynamically ---
  function fixLinkedCSS() {
    document.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
      const href = link.href;
      if (href && href.includes(FROM)) {
        link.href = replaceUrl(href);
      } else {
        // For cross-origin CSS that may contain Imgur URLs, fetch and replace them
        if (href && !href.startsWith(window.location.origin)) {
          fetch(href)
            .then(r => r.text())
            .then(css => {
              if (css.includes(FROM)) {
                const newStyle = document.createElement('style');
                newStyle.textContent = replaceUrl(css);
                document.head.appendChild(newStyle);
              }
            })
            .catch(() => {});
        }
      }
    });
  }

  // --- 5. Initial run ---
  fixImages();
  fixInlineStyles();
  fixStyleAttributes();
  fixLinkedCSS();

  // --- 6. Observe future changes ---
  const observer = new MutationObserver(mutations => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;

        if (node.tagName === 'IMG' && node.src.includes(FROM)) {
          node.src = replaceUrl(node.src);
        }
        if (node.tagName === 'STYLE' && node.textContent.includes(FROM)) {
          node.textContent = replaceUrl(node.textContent);
        }
        if (node.hasAttribute && node.hasAttribute('style') && node.getAttribute('style').includes(FROM)) {
          node.setAttribute('style', replaceUrl(node.getAttribute('style')));
        }

        // Recursively fix inside containers
        fixImages(node);
        fixStyleAttributes(node);
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
})();
