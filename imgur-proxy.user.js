// ==UserScript==
// @name         Yummy Imgur Proxy
// @namespace    yy7mii's imgur proxy for userscripts :p
// @author       YY7MII
// @version      1.0.2
// @description  Replace i.imgur.com references safely
// @match        *://*/*
// @run-at       document-end
// @grant        none
// @updateURL    https://raw.githubusercontent.com/YY7MII/imgur-uk/main/imgur-proxy.user.js
// @downloadURL  https://raw.githubusercontent.com/YY7MII/imgur-uk/main/imgur-proxy.user.js
// @homepageURL  https://github.com/YY7MII/imgur-uk
// @noframes
// ==/UserScript==

(function () {
  'use strict';

  const FROM = 'i.imgur.com';
  const TO = 'imgur-uk.vercel.app';

  // Safe attribute/text replacement for elements
  function replaceElementUrls(el) {
    if (el.hasAttribute('src')) {
      el.src = el.src.replace(FROM, TO);
    }
    if (el.hasAttribute('href')) {
      el.href = el.href.replace(FROM, TO);
    }
    if (el.hasAttribute('srcset')) {
      el.srcset = el.srcset.replaceAll(FROM, TO);
    }
    if (el.hasAttribute('style')) {
      el.style.cssText = el.style.cssText.replaceAll(FROM, TO);
    }
  }

  // Replace text nodes (rarely used for URLs)
  function walk(node) {
    let child, next;
    switch (node.nodeType) {
      case 1:  // Element
        replaceElementUrls(node);
        for (child = node.firstChild; child; child = next) {
          next = child.nextSibling;
          walk(child);
        }
        break;
      case 3:  // Text node
        node.nodeValue = node.nodeValue.replaceAll(FROM, TO);
        break;
    }
  }

  walk(document.body);

  // Observe DOM changes for dynamic content
  const observer = new MutationObserver(mutations => {
    mutations.forEach(m => {
      if (m.type === 'childList') {
        m.addedNodes.forEach(n => walk(n));
      } else if (m.type === 'attributes') {
        walk(m.target);
      }
    });
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['src', 'href', 'srcset', 'style']
  });

})();
