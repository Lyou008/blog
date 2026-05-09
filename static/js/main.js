/* ── Main JavaScript ──────────────────────────────────────────── */
(function() {
    'use strict';

    // ── Theme Toggle ──────────────────────────────────────────
    const themeToggle = document.getElementById('themeToggle');
    const html = document.documentElement;

    // Load saved theme
    const savedTheme = localStorage.getItem('blog-theme') || 'light';
    html.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);

    function updateThemeIcon(theme) {
        if (themeToggle) {
            const icon = themeToggle.querySelector('i');
            if (icon) {
                icon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
            }
        }
    }

    function toggleTheme() {
        const current = html.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        localStorage.setItem('blog-theme', next);
        updateThemeIcon(next);
    }

    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }

    // ── Search Toggle ──────────────────────────────────────────
    const searchToggle = document.getElementById('searchToggle');
    const searchBar = document.getElementById('searchBar');

    if (searchToggle && searchBar) {
        searchToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            searchBar.classList.toggle('hidden');
            if (!searchBar.classList.contains('hidden')) {
                const input = searchBar.querySelector('input');
                if (input) setTimeout(() => input.focus(), 100);
            }
        });

        // Close search bar on click outside
        document.addEventListener('click', function(e) {
            if (!searchBar.classList.contains('hidden') &&
                !searchBar.contains(e.target) &&
                !searchToggle.contains(e.target)) {
                searchBar.classList.add('hidden');
            }
        });

        // Close on Escape
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && !searchBar.classList.contains('hidden')) {
                searchBar.classList.add('hidden');
            }
        });
    }

    // ── Mobile Menu Toggle ─────────────────────────────────────
    const menuToggle = document.getElementById('menuToggle');
    const navLinks = document.querySelector('.nav-links');

    if (menuToggle && navLinks) {
        menuToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            navLinks.classList.toggle('open');
        });

        // Close menu on click outside
        document.addEventListener('click', function(e) {
            if (navLinks.classList.contains('open') &&
                !navLinks.contains(e.target) &&
                !menuToggle.contains(e.target)) {
                navLinks.classList.remove('open');
            }
        });

        // Close on link click
        navLinks.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                navLinks.classList.remove('open');
            });
        });
    }

    // ── Flash Messages Auto-dismiss ────────────────────────────
    document.querySelectorAll('.flash-message').forEach(function(msg) {
        setTimeout(function() {
            msg.style.opacity = '0';
            msg.style.transition = 'opacity 0.3s ease';
            setTimeout(function() {
                if (msg.parentElement) msg.remove();
            }, 300);
        }, 5000);
    });

    // ── Smooth Scroll ──────────────────────────────────────────
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: 'smooth' });
            }
        });
    });

    // ── Image Lazy Loading ──────────────────────────────────────
    if ('loading' in HTMLImageElement.prototype) {
        document.querySelectorAll('img[loading="lazy"]').forEach(img => {
            img.src = img.src; // Trigger lazy loading
        });
    }

    // ── Delete Confirmation Enhancement ────────────────────────
    document.querySelectorAll('form[onsubmit]').forEach(form => {
        const originalSubmit = form.onsubmit;
        form.onsubmit = null;
        form.addEventListener('submit', function(e) {
            // The inline onsubmit already handles the confirm dialog
        });
    });

    // System preference detection for first visit
    if (!localStorage.getItem('blog-theme')) {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            html.setAttribute('data-theme', 'dark');
            updateThemeIcon('dark');
        }
    }

})();
