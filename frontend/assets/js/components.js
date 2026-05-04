/**
 * components.js
 * --------------
 * Injects the shared site header and footer into every page so the markup
 * stays in one place. Each HTML page only needs:
 *
 *   <body data-nav="about">
 *     <div id="site-header"></div>
 *     <main> ... </main>
 *     <div id="site-footer"></div>
 *     <script src="/path/to/components.js"></script>
 *   </body>
 *
 * The script computes the site root from its own URL, so the injected links
 * work no matter how deep the current page is in the folder structure.
 */
(function () {
  // Locate this script so we can derive the site root from its URL.
  const thisScript =
    document.currentScript ||
    Array.from(document.scripts).find((s) => s.src.includes("components.js"));

  if (!thisScript) return;

  // components.js lives at <root>/assets/js/components.js
  // → site root is two directories up.
  const siteRoot = new URL("../../", thisScript.src).href;

  const headerHTML = `
    <a class="skip-link" href="#main">Skip to content</a>
    <header class="site-header" role="banner">
      <div class="container">
        <a class="site-title" href="${siteRoot}index.html">The World</a>
        <p class="site-tagline">News, data, and trends</p>
        <nav class="site-nav" aria-label="Primary navigation">
          <ul>
            <li><a href="${siteRoot}index.html" data-nav="about">About</a></li>
            <li><a href="${siteRoot}news/index.html" data-nav="news">News</a></li>
          </ul>
        </nav>
      </div>
    </header>
  `;

  const year = new Date().getFullYear();
  const footerHTML = `
    <footer class="site-footer" role="contentinfo">
      <div class="container">
        <p>&copy; ${year} The World. Placeholder content for layout purposes.</p>
      </div>
    </footer>
  `;

  const headerSlot = document.getElementById("site-header");
  const footerSlot = document.getElementById("site-footer");

  if (headerSlot) headerSlot.outerHTML = headerHTML;
  if (footerSlot) footerSlot.outerHTML = footerHTML;

  // Highlight the active nav link based on the body's data-nav attribute.
  const activeNav = document.body.dataset.nav;
  if (activeNav) {
    const link = document.querySelector(`.site-nav a[data-nav="${activeNav}"]`);
    if (link) {
      link.classList.add("is-active");
      link.setAttribute("aria-current", "page");
    }
  }
})();
