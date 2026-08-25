// ==========================================================================
// Tab strip
// Chrome-style tabs living between the hamburger menu and the Export button.
// Tab 1 is the existing app (subjects/sessions/recordings/pinboard) and is
// never removed. New tabs open as blank pages that can be switched between
// without losing the state of Tab 1 (its DOM is simply shown/hidden, not
// rebuilt).
// ==========================================================================

(function () {
    const tabStrip = document.getElementById('tab-strip');
    const newTabBtn = document.getElementById('new-tab-btn');
    const tabPages = document.getElementById('tab-pages');

    if (!tabStrip || !newTabBtn || !tabPages) return;

    // Tab 1 already exists in the markup (id="tab-page-1").
    const tabs = [{ id: 1, title: 'Tab 1' }];
    let nextTabId = 2;
    let activeTabId = 1;

    function closeIconSvg() {
        return '<svg width="9" height="9" viewBox="0 0 10 10" fill="none">'
            + '<path d="M1 1L9 9M9 1L1 9" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />'
            + '</svg>';
    }

    function render() {
        tabStrip.innerHTML = '';

        tabs.forEach(function (tab) {
            const isActive = tab.id === activeTabId;

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'tab-item' + (isActive ? ' active' : '');
            btn.setAttribute('role', 'tab');
            btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
            btn.dataset.tabId = String(tab.id);
            btn.title = tab.title;

            const label = document.createElement('span');
            label.className = 'tab-item-label';
            label.textContent = tab.title;
            btn.appendChild(label);

            // Keep at least one tab open at all times.
            if (tabs.length > 1) {
                const close = document.createElement('span');
                close.className = 'tab-item-close';
                close.title = 'Close tab';
                close.innerHTML = closeIconSvg();
                close.addEventListener('click', function (e) {
                    e.stopPropagation();
                    closeTab(tab.id);
                });
                btn.appendChild(close);
            }

            btn.addEventListener('click', function () {
                setActiveTab(tab.id);
            });

            tabStrip.appendChild(btn);
        });

        tabPages.querySelectorAll('.tab-page').forEach(function (page) {
            page.classList.toggle('active', Number(page.dataset.tabId) === activeTabId);
        });
    }

    function setActiveTab(id) {
        activeTabId = id;
        render();
    }

    function createBlankPage(id) {
        const page = document.createElement('div');
        page.className = 'tab-page tab-page-blank';
        page.dataset.tabId = String(id);
        page.innerHTML = '<div class="tab-page-blank-inner">New Tab</div>';
        tabPages.appendChild(page);
        return page;
    }

    function addTab(title) {
        const id = nextTabId;
        nextTabId += 1;
        tabs.push({ id: id, title: title || 'New Tab' });
        createBlankPage(id);
        setActiveTab(id);
        return id;
    }

    // Exposed so other scripts (e.g. the Developer menu's "Custom Script"
    // item) can open a new tab in this strip instead of a browser tab.
    window.arcAddTab = addTab;

    function closeTab(id) {
        const idx = tabs.findIndex(function (t) { return t.id === id; });
        if (idx === -1 || tabs.length === 1) return;

        tabs.splice(idx, 1);

        const page = tabPages.querySelector('.tab-page[data-tab-id="' + id + '"]');
        // Only blank pages get removed from the DOM; Tab 1's real content
        // is preserved even though it's never closeable.
        if (page && page.classList.contains('tab-page-blank')) {
            page.remove();
        }

        if (activeTabId === id) {
            const fallback = tabs[idx] || tabs[idx - 1];
            activeTabId = fallback.id;
        }

        render();
    }

    newTabBtn.addEventListener('click', function () {
        addTab();
    });

    render();
})();
