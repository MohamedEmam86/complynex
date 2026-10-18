/* ==========================================================================
   ComplyNex sidebar behaviour — three collapsible levels.

   No inline handlers: the app runs a CSP that strips onclick attributes, so
   everything binds here.
   ========================================================================== */
(function () {
  'use strict';

  var nav = document.getElementById('cnxNav');
  var sidebar = document.getElementById('cnxSidebar');
  if (!nav || !sidebar) return;

  var K_OPEN = 'cnx.nav.open';       /* which area is open */
  var K_OPEN_MOD = 'cnx.nav.openmod'; /* which module inside it */
  var K_COLLAPSED = 'cnx.nav.collapsed';

  function setOpen(item, open) {
    item.classList.toggle('is-open', open);
    var t = item.querySelector(':scope > .cnx-nav__toggle');
    if (t) t.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  /* ------------------------------------------------------------ active trail
     Opens the whole branch down to the current page and marks every ancestor,
     so after a page load you can see where you are without hunting. Matching is
     on resolved href with longest-prefix wins, because several endpoints share
     a path root. */
  function markActive() {
    var here = window.location.pathname.replace(/\/+$/, '') || '/';
    var best = null, bestLen = -1;

    nav.querySelectorAll('.cnx-nav__link').forEach(function (a) {
      var href = (a.getAttribute('href') || '').replace(/\/+$/, '') || '/';
      if (href === '/' && here !== '/') return;
      if (here === href || here.indexOf(href + '/') === 0) {
        if (href.length > bestLen) { best = a; bestLen = href.length; }
      }
    });
    if (!best) return;

    best.classList.add('is-active');
    var node = best.parentElement;
    while (node && node !== nav) {
      if (node.classList && node.classList.contains('cnx-nav__item')) {
        node.classList.add('has-active');
        setOpen(node, true);
      }
      node = node.parentElement;
    }
  }

  /* ------------------------------------------------------------ accordion
     Siblings only. Opening a module closes its sibling modules but leaves the
     parent area open — closing the parent when you open a child would make the
     tree unusable. */
  function bindToggles() {
    nav.querySelectorAll('.cnx-nav__toggle').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var item = btn.parentElement;
        var willOpen = !item.classList.contains('is-open');
        var siblings = item.parentElement.children;

        for (var i = 0; i < siblings.length; i++) {
          var s = siblings[i];
          if (s !== item && s.classList &&
              s.classList.contains('cnx-nav__item')) {
            setOpen(s, false);
          }
        }
        setOpen(item, willOpen);

        try {
          var isModule = item.classList.contains('cnx-nav__item--module');
          if (isModule) {
            if (willOpen) {
              localStorage.setItem(K_OPEN_MOD,
                (btn.querySelector('.cnx-nav__label') || {}).textContent || '');
            } else {
              localStorage.removeItem(K_OPEN_MOD);
            }
          } else {
            if (willOpen) localStorage.setItem(K_OPEN, item.dataset.area || '');
            else { localStorage.removeItem(K_OPEN); localStorage.removeItem(K_OPEN_MOD); }
          }
        } catch (err) { /* private mode — remembering is a nicety */ }
      });
    });
  }

  function restore() {
    if (nav.querySelector('.cnx-nav__item.has-active')) return; /* active wins */
    var area, mod;
    try {
      area = localStorage.getItem(K_OPEN);
      mod = localStorage.getItem(K_OPEN_MOD);
    } catch (e) { return; }
    if (!area) return;
    var item = nav.querySelector('.cnx-nav__item[data-area="' + area + '"]');
    if (!item) return;
    setOpen(item, true);
    if (!mod) return;
    item.querySelectorAll('.cnx-nav__item--module').forEach(function (m) {
      var lbl = m.querySelector('.cnx-nav__label');
      if (lbl && lbl.textContent.trim() === mod.trim()) setOpen(m, true);
    });
  }

  /* ------------------------------------------------------------ search
     Filters leaf pages and reveals the branches that contain a hit. With 107
     pages this is the fastest route to any of them. */
  function bindSearch() {
    var input = document.getElementById('cnxNavSearch');
    if (!input) return;

    var empty = document.createElement('li');
    empty.className = 'cnx-nav__noresult';
    empty.hidden = true;
    empty.textContent = 'No matching page';
    nav.appendChild(empty);

    function reset() {
      nav.classList.remove('is-searching');
      nav.querySelectorAll('.is-hidden').forEach(function (n) {
        n.classList.remove('is-hidden');
      });
      nav.querySelectorAll('.cnx-nav__item').forEach(function (i) {
        setOpen(i, i.classList.contains('has-active'));
      });
      empty.hidden = true;
    }

    function apply() {
      var q = input.value.trim().toLowerCase();
      if (!q) { reset(); return; }

      nav.classList.add('is-searching');
      var hits = 0;

      /* leaves first */
      nav.querySelectorAll('.cnx-nav__subitem').forEach(function (li) {
        var a = li.querySelector('.cnx-nav__link');
        if (!a) return;
        var match = a.textContent.trim().toLowerCase().indexOf(q) !== -1;
        li.classList.toggle('is-hidden', !match);
        if (match) hits++;
      });

      /* then any branch with no visible leaf disappears — deepest first, so a
         module hidden here also stops its area from counting it */
      nav.querySelectorAll('.cnx-nav__item--module').forEach(function (m) {
        var vis = m.querySelectorAll('.cnx-nav__subitem:not(.is-hidden)').length;
        m.classList.toggle('is-hidden', vis === 0);
        setOpen(m, vis > 0);
      });
      nav.querySelectorAll('.cnx-nav > .cnx-nav__item').forEach(function (a) {
        var vis = a.querySelectorAll('.cnx-nav__subitem:not(.is-hidden)').length;
        a.classList.toggle('is-hidden', vis === 0);
        setOpen(a, vis > 0);
      });

      empty.hidden = hits > 0;
    }

    input.addEventListener('input', apply);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { input.value = ''; reset(); input.blur(); }
      if (e.key === 'Enter') {
        var f = nav.querySelector('.cnx-nav__subitem:not(.is-hidden) .cnx-nav__link');
        if (f) f.click();
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
      var t = e.target.tagName;
      if (t === 'INPUT' || t === 'TEXTAREA' || e.target.isContentEditable) return;
      e.preventDefault(); input.focus(); input.select();
    });
  }

  /* ------------------------------------------------------------ expand/collapse all */
  function bindExpandCollapse() {
    function setAll(open) {
      nav.querySelectorAll('.cnx-nav__item').forEach(function (i) {
        if (i.querySelector(':scope > .cnx-nav__toggle')) setOpen(i, open);
      });
      if (!open) {
        try { localStorage.removeItem(K_OPEN); localStorage.removeItem(K_OPEN_MOD); }
        catch (e) {}
      }
    }
    var ex = document.getElementById('cnxExpandAll');
    var co = document.getElementById('cnxCollapseAll');
    if (ex) ex.addEventListener('click', function () { setAll(true); });
    if (co) co.addEventListener('click', function () { setAll(false); });
  }

  /* ------------------------------------------------------------ rail collapse */
  function bindCollapse() {
    var btn = document.getElementById('cnxCollapse');
    if (!btn) return;
    try {
      if (localStorage.getItem(K_COLLAPSED) === '1') sidebar.classList.add('is-collapsed');
    } catch (e) {}
    btn.addEventListener('click', function () {
      var c = sidebar.classList.toggle('is-collapsed');
      try { localStorage.setItem(K_COLLAPSED, c ? '1' : '0'); } catch (e) {}
    });
  }


  /* ------------------------------------------------------------ mobile
     Below 992px the CSS parks the sidebar off-screen and reveals it on
     .is-open — but nothing was adding that class, so on a phone the sidebar
     was simply unreachable.

     main.js binds #sidebarToggle to document.querySelector('.sidebar') and
     toggles '.show'. Neither matches this sidebar: the class is .cnx-sidebar
     and the state class is .is-open, so that handler silently bound to null.

     The CMS navbar has #sidebarToggle. The Employee Portal has no sidebar
     toggle at all — its hamburger drives its own top nav — so one is injected
     here rather than editing two templates. */
  function bindMobile() {
    var MOBILE = window.matchMedia('(max-width: 991.98px)');

    var backdrop = document.createElement('div');
    backdrop.className = 'cnx-backdrop';
    backdrop.hidden = true;
    document.body.appendChild(backdrop);

    function open(yes) {
      sidebar.classList.toggle('is-open', yes);
      backdrop.hidden = !yes;
      document.body.classList.toggle('cnx-noscroll', yes);
    }

    var btn = document.getElementById('sidebarToggle');
    if (!btn) {
      btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'cnxMobileToggle';
      btn.className = 'cnx-mobile-toggle';
      btn.setAttribute('aria-label', 'Open navigation');
      btn.innerHTML = '<i class="bi bi-list"></i>';
      document.body.appendChild(btn);
    }
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      open(!sidebar.classList.contains('is-open'));
    });

    backdrop.addEventListener('click', function () { open(false); });

    /* a tap on any page link should close the drawer, or you land on the new
       page with the menu still covering it */
    nav.addEventListener('click', function (e) {
      if (e.target.closest('.cnx-nav__link') && MOBILE.matches) open(false);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') open(false);
    });

    /* rotating to landscape past the breakpoint should not leave a stuck
       backdrop over a sidebar that is now docked */
    MOBILE.addEventListener('change', function (ev) {
      if (!ev.matches) open(false);
    });
  }

  markActive();
  bindToggles();
  restore();
  bindSearch();
  bindExpandCollapse();
  bindCollapse();
  bindMobile();
})();
