// Shared front-end utilities for MockFlow-AI.
// Exposes a small set of helpers on `window` so templates and other static
// scripts can reuse them instead of redefining local copies.
(function () {
    'use strict';

    /**
     * Escape a value for safe insertion into HTML. Uses a detached element so
     * the browser handles entity encoding consistently. Null/undefined become ''.
     */
    function escapeHtml(value) {
        if (value === null || typeof value === 'undefined') return '';
        var div = document.createElement('div');
        div.textContent = value;
        return div.innerHTML;
    }

    /**
     * Format an ISO date string as e.g. "Dec 6, 2024 · 3:42 PM" (date + time so
     * same-day sessions stay distinguishable). Falsy input returns 'Unknown';
     * unparseable input is returned unchanged.
     */
    function formatDate(isoDate) {
        if (!isoDate) return 'Unknown';
        try {
            var date = new Date(isoDate);
            if (isNaN(date.getTime())) return isoDate;
            var datePart = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
            var timePart = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
            return datePart + ' · ' + timePart;
        } catch (e) {
            return isoDate;
        }
    }

    /**
     * Map an interview stage key to a short human label.
     */
    function formatStage(stage) {
        var map = {
            'welcome': 'Welcome',
            'self_intro': 'Intro',
            'past_experience': 'Experience',
            'company_fit': 'Fit',
            'closing': 'Closing'
        };
        return map[stage] || stage || '';
    }

    var TOAST_TYPES = { info: 'info', success: 'success', error: 'error' };

    /**
     * Lazily create (or fetch) the toast container. Marked as a live region so
     * assistive tech announces toasts as they appear.
     */
    function getToastStack() {
        var stack = document.querySelector('.app-toast-stack');
        if (!stack) {
            stack = document.createElement('div');
            stack.className = 'app-toast-stack';
            stack.setAttribute('role', 'status');
            stack.setAttribute('aria-live', 'polite');
            document.body.appendChild(stack);
        }
        return stack;
    }

    /**
     * Show a small dismissible toast. `type` is one of 'info' | 'success' |
     * 'error' (default 'info'). Auto-dismisses after ~3.5s; clicking dismisses
     * immediately.
     */
    function showToast(message, type) {
        var variant = TOAST_TYPES[type] || 'info';
        var stack = getToastStack();

        var toast = document.createElement('div');
        toast.className = 'app-toast app-toast--' + variant;

        var text = document.createElement('span');
        text.className = 'app-toast-text';
        text.textContent = message;
        toast.appendChild(text);

        var dismissed = false;
        function dismiss() {
            if (dismissed) return;
            dismissed = true;
            toast.classList.add('app-toast--leaving');
            window.setTimeout(function () {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 250);
        }

        toast.addEventListener('click', dismiss);
        stack.appendChild(toast);

        // Trigger enter transition on the next frame.
        window.requestAnimationFrame(function () {
            toast.classList.add('app-toast--visible');
        });

        window.setTimeout(dismiss, 3500);
        return toast;
    }

    window.escapeHtml = escapeHtml;
    window.formatDate = formatDate;
    window.formatStage = formatStage;
    window.showToast = showToast;
})();
