// ==UserScript==
// @name         Yummy Imgur Proxy
// @namespace    https://imgur-uk.vercel.app
// @author       YY7MII
// @version      0.1.3
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

  const MAIN_IMGUR = 'imgur.com';
  const IMGUR_IMGS = 'i.imgur.com';
  const TO = 'imgur-uk.vercel.app';

  function replaceUrl(str) {
    return str.replaceAll(IMGUR_IMGS, TO);
  }

  // --- 1. Fix <img> tags (src + srcset) ---
  function fixImages(root = document) {
    root.querySelectorAll('img').forEach(img => {
      // Replace src
      if (img.src && img.src.includes(IMGUR_IMGS)) {
        img.src = replaceUrl(img.src);
      }
      if (img.src && img.src.includes(MAIN_IMGUR)) {
        img.src = replaceUrl(img.src);
      }

      // Replace srcset
      if (img.srcset && img.srcset.includes(IMGUR_IMGS)) {
        img.srcset = replaceUrl(img.srcset);
      }
      if (img.srcset && img.srcset.includes(MAIN_IMGUR)) {
        img.srcset = replaceUrl(img.srcset);
      }
    });
  }

  function fixAlbumLinks(root = document) {
    root.querySelectorAll('a[href]').forEach(a => {
      const href = a.getAttribute('href');
      if (!href) return;

      if (
        href.includes('imgur.com/a/') ||
        href.includes('imgur.com/gallery/')
      ) {
        a.href = href.replace(MAIN_IMGUR, TO);
      }
    });
  }


  // --- 2. Inline <style> tags ---
  function fixInlineStyles() {
    document.querySelectorAll('style').forEach(style => {
      if (style.textContent.includes(IMGUR_IMGS)) {
        style.textContent = replaceUrl(style.textContent);
      }
    });
  }

  // --- 3. style="" attributes ---
  function fixStyleAttributes(root = document) {
    root.querySelectorAll('[style*="' + IMGUR_IMGS + '"]').forEach(el => {
      el.setAttribute('style', replaceUrl(el.getAttribute('style')));
    });
  }

  // --- 4. Linked CSS (also fetch remote CSS and patch it if needed) ---
  function fixLinkedCSS() {
    document.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
      const href = link.href;
      if (!href) return;

      if (href.includes(IMGUR_IMGS)) {
        link.href = replaceUrl(href);
      } else if (!href.startsWith(window.location.origin)) {
        fetch(href)
          .then(r => r.text())
          .then(css => {
            if (css.includes(IMGUR_IMGS)) {
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
    fixAlbumLinks();
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
          if (node.src && node.src.includes(IMGUR_IMGS)) node.src = replaceUrl(node.src);
          if (node.srcset && node.srcset.includes(IMGUR_IMGS)) node.srcset = replaceUrl(node.srcset);
        }

        // Handle new <style> tags
        if (node.tagName === 'STYLE' && node.textContent.includes(IMGUR_IMGS)) {
          node.textContent = replaceUrl(node.textContent);
        }

        // Handle inline styles
        if (node.hasAttribute && node.hasAttribute('style')) {
          const style = node.getAttribute('style');
          if (style && style.includes(IMGUR_IMGS)) node.setAttribute('style', replaceUrl(style));
        }

        // Recursively patch inside container nodes
        fixImages(node);
        fixStyleAttributes(node);
        fixAlbumLinks(node);
      }
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
})();
