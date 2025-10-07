// ==UserScript==
// @name         Yummy Imgur Proxy
// @namespace    yy7mii's imgur proxy for userscripts :p
// @author       YY7MII
// @version      1.0.1
// @description  Replace all i.imgur.com html references with imgur-uk.vercel.app
// @match        *://*/*
// @run-at       document-end
// @grant        none
// @updateURL    https://raw.githubusercontent.com/YY7MII/imgur-uk/main/imgur-proxy.user.js
// @downloadURL  https://raw.githubusercontent.com/YY7MII/imgur-uk/main/imgur-proxy.user.js
// @noframes
// ==/UserScript==

(function () {
  'use strict';
  // Replace all instances of i.imgur.com -> imgur-uk.vercel.app
  document.body.innerHTML = document.body.innerHTML.replaceAll('i.imgur.com', 'imgur-uk.vercel.app');
})();
