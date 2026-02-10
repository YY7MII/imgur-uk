// ==UserScript==
// @name         Yummy Imgur Proxy
// @namespace    https://imgur-uk.vercel.app
// @author       YY7MII
// @version      0.1.2
// @description  Proxy all i.imgur.com links (img + CSS + srcset) through imgur-uk.vercel.app
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

  // --- 1. Fix <img> tags (src + srcset) ---
  function fixImages(root = document) {
    root.querySelectorAll('img').forEach(img => {
      // Replace src
      if (img.src && img.src.includes(FROM)) {
        img.src = replaceUrl(img.src);
      }

      // Replace srcset
      if (img.srcset && img.srcset.includes(FROM)) {
        img.srcset = replaceUrl(img.srcset);
      }
    });
  }

  // --- 2. Inline <style> tags ---
  function fixInlineStyles() {
    document.querySelectorAll('style').forEach(style => {
      if (style.textContent.includes(FROM)) {
        style.textContent = replaceUrl(style.textContent);
      }
    });
  }

  // --- 3. style="" attributes ---
  function fixStyleAttributes(root = document) {
    root.querySelectorAll('[style*="' + FROM + '"]').forEach(el => {
      el.setAttribute('style', replaceUrl(el.getAttribute('style')));
    });
  }

  // --- 4. Linked CSS (also fetch remote CSS and patch it if needed) ---
  function fixLinkedCSS() {
    document.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
      const href = link.href;
      if (!href) return;

      if (href.includes(FROM)) {
        link.href = replaceUrl(href);
      } else if (!href.startsWith(window.location.origin)) {
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
    });
  }

  // --- 5. Initial run ---
  function runAll() {
    fixImages();
    fixInlineStyles();
    fixStyleAttributes();
    fixLinkedCSS();
  }

  runAll();

  setInterval(runAll, 3500);
  // --- 6. Mutation observer for dynamically loaded content ---
  const observer = new MutationObserver(mutations => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;

        // Handle newly added <img>
        if (node.tagName === 'IMG') {
          if (node.src && node.src.includes(FROM)) node.src = replaceUrl(node.src);
          if (node.srcset && node.srcset.includes(FROM)) node.srcset = replaceUrl(node.srcset);
        }

        // Handle new <style> tags
        if (node.tagName === 'STYLE' && node.textContent.includes(FROM)) {
          node.textContent = replaceUrl(node.textContent);
        }

        // Handle inline styles
        if (node.hasAttribute && node.hasAttribute('style')) {
          const style = node.getAttribute('style');
          if (style && style.includes(FROM)) node.setAttribute('style', replaceUrl(style));
        }

        // Recursively patch inside container nodes
        fixImages(node);
        fixStyleAttributes(node);
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
})();
