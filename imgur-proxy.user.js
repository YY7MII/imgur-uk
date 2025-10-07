// ==UserScript==
// @name         Yummy Imgur Proxy
// @namespace    yy7mii's imgur proxy for userscripts :p
// @author       YY7MII
// @version      1.0.3
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

  // Replace all existing img src
  document.querySelectorAll('img').forEach(img => {
    if (img.src.includes(FROM)) {
      img.src = img.src.replace(FROM, TO);
    }
  });

  // Observe new img elements added later
  const observer = new MutationObserver(mutations => {
    mutations.forEach(m => {
      m.addedNodes.forEach(node => {
        if (node.tagName === 'IMG' && node.src.includes(FROM)) {
          node.src = node.src.replace(FROM, TO);
        }
        // Also handle imgs inside added containers
        if (node.querySelectorAll) {
          node.querySelectorAll('img').forEach(img => {
            if (img.src.includes(FROM)) {
              img.src = img.src.replace(FROM, TO);
            }
          });
        }
      });
    });
  });

  observer.observe(document.body, { childList: true, subtree: true });
})();
