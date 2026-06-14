// Dashboard functionality

async function initDashboard() {
    try {
        const authData = await checkAuthStatus();

        if (!authData.authenticated || !authData.user) {
            window.location.href = '/auth/login';
            return;
        }

        const user = authData.user;

        // Populate user info
        document.getElementById('userName').textContent = user.name || user.email;
        document.getElementById('userEmail').textContent = user.email;

        // Set avatar placeholder with first letter
        const firstLetter = (user.name || user.email)[0].toUpperCase();
        document.getElementById('userAvatarPlaceholder').textContent = firstLetter;

        // Load API keys status and interview stats in parallel.
        // Each is independently fault-tolerant so one failing never blocks the other.
        await Promise.allSettled([
            loadApiKeysStatus(),
            loadUserStats()
        ]);
    } catch (error) {
        console.error('Dashboard initialization failed:', error);
    }
}

// ==================== INTERVIEW PERSONALITY / STATS ====================

const TRACK_META = [
    { key: 'intro', label: 'Intro' },
    { key: 'behavioral', label: 'Behavioral' },
    { key: 'technical_voice', label: 'Technical (Voice)' },
    { key: 'coding', label: 'Coding' }
];

// Wing D verdict vocabulary (mirrors feedback.html).
const RECO_LABEL = {strong_no_hire:'Strong No-Hire', no_hire:'No-Hire', lean_no_hire:'Leaning No-Hire',
    on_fence:'On the Fence', lean_hire:'Leaning Hire', hire:'Hire', strong_hire:'Strong Hire'};
const RECO_TONE = {strong_no_hire:'neg', no_hire:'neg', lean_no_hire:'neg',
    on_fence:'mid', lean_hire:'pos', hire:'pos', strong_hire:'pos'};
const LEVEL_LABEL = {below_intern:'developing', intern:'intern', new_grad:'new-grad',
    mid:'mid-level', above_mid:'above mid-level'};
const BAND_LABEL = {outstanding:'Outstanding', solid:'Solid', borderline:'Borderline',
    poor:'Poor', cannot_determine:'Not shown'};
const TREND_META = {
    improving: {icon: '↑', cls: 'up', label: 'improving'},
    regressing: {icon: '↓', cls: 'down', label: 'slipping'},
    flat: {icon: '→', cls: 'flat', label: 'steady'}
};

// escapeHtml is provided globally by static/utils.js (loaded before this script).

function setHidden(el, hidden) {
    if (!el) return;
    el.classList.toggle('is-hidden', hidden);
}

function formatRelativeDate(iso) {
    if (!iso) return null;
    const then = new Date(iso);
    if (isNaN(then.getTime())) return null;
    const now = new Date();
    const diffMs = now - then;
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffDays <= 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return diffDays + ' days ago';
    if (diffDays < 14) return 'Last week';
    if (diffDays < 30) return Math.floor(diffDays / 7) + ' weeks ago';
    if (diffDays < 60) return 'Last month';
    if (diffDays < 365) return Math.floor(diffDays / 30) + ' months ago';
    return Math.floor(diffDays / 365) + ' year' + (diffDays >= 730 ? 's' : '') + ' ago';
}

function freeBadgeMarkup(remaining) {
    const n = Number.isFinite(remaining) ? remaining : 0;
    if (n > 0) {
        const label = n === 1 ? '1 free interview left' : n + ' free interviews left';
        return '<span class="free-badge" role="status" aria-label="' + escapeHtml(label) + '">' +
            '<span class="free-badge-emoji" aria-hidden="true">🎁</span>' +
            '<span>' + escapeHtml(label) + '</span></span>';
    }
    return '<span class="free-badge byok" role="status">' +
        '<span>Bring your own keys for unlimited</span></span>';
}

function buildPersonalitySummary(data) {
    const parts = [];
    const n = Number(data.total_sessions) || 0;
    parts.push(n === 1 ? '1 session in' : n + ' sessions in');
    if (data.strongest && data.strongest.label) {
        parts.push('strongest at ' + data.strongest.label.toLowerCase());
    }
    if (data.recommendation_trend === 'improving') parts.push('trending up ↑');
    else if (data.recommendation_trend === 'regressing') parts.push('dipped recently');
    const remaining = Number(data.free_calls_remaining);
    if (Number.isFinite(remaining) && remaining > 0) {
        parts.push(remaining === 1 ? '1 free interview left' : remaining + ' free interviews left');
    }
    return parts.join(' · ');
}

function renderInsightsContent(data) {
    const latest = data.latest || {};
    const tone = RECO_TONE[latest.recommendation] || 'mid';

    // The headline verdict card.
    let verdict = '<div class="insight-verdict tone-' + tone + '">';
    verdict += '<span class="iv-eyebrow">Latest verdict' +
        (latest.track ? ' · ' + escapeHtml(latest.track) : '') + '</span>';
    verdict += '<span class="iv-reco">' + escapeHtml(RECO_LABEL[latest.recommendation] || '—') + '</span>';
    if (LEVEL_LABEL[latest.level_read]) {
        verdict += '<span class="iv-level">performing at <strong>' +
            LEVEL_LABEL[latest.level_read] + '</strong> level</span>';
    }
    if (latest.headline) verdict += '<p class="iv-headline">' + escapeHtml(latest.headline) + '</p>';
    verdict += '</div>';

    // Per-competency bands + trend across sessions.
    let comps = '';
    if (data.competencies && data.competencies.length) {
        const rows = data.competencies.map(function (c) {
            const t = TREND_META[c.trend] || TREND_META.flat;
            const pct = Math.round((Number(c.latest_score) / 4) * 100);
            return '<div class="comp-row">' +
                '<span class="comp-name">' + escapeHtml(c.label) + '</span>' +
                '<span class="comp-bar"><span class="comp-fill band-' + c.latest_band + '" style="width:' + pct + '%"></span></span>' +
                '<span class="comp-band band-chip-' + c.latest_band + '">' + (BAND_LABEL[c.latest_band] || c.latest_band) + '</span>' +
                '<span class="comp-trend trend-' + t.cls + '" title="' + t.label + ' (' + c.sessions + ' sessions)">' + t.icon + '</span>' +
            '</div>';
        }).join('');
        comps = '<div class="insight-comps"><div class="ic-title">Competencies — latest band &amp; trend</div>' + rows + '</div>';
    }

    // Compact stat row: sessions, recency, by-track.
    const total = Number(data.total_sessions) || 0;
    const recency = formatRelativeDate(latest.date);
    const totalCard = '<div class="stat-card"><span class="stat-label">Sessions</span>' +
        '<span class="stat-value">' + total + '</span>' +
        '<span class="stat-hint">' + (total === 1 ? 'completed' : 'completed') + '</span></div>';
    const recencyCard = '<div class="stat-card"><span class="stat-label">Last Active</span>' +
        '<span class="stat-value">' + (recency ? escapeHtml(recency) : '&mdash;') + '</span>' +
        '<span class="stat-hint">keep the streak going</span></div>';

    const tracks = data.by_track || {};
    const maxTrack = TRACK_META.reduce(function (m, t) { return Math.max(m, Number(tracks[t.key]) || 0); }, 0);
    const trackRows = TRACK_META.map(function (t) {
        const count = Number(tracks[t.key]) || 0;
        const pct = maxTrack > 0 ? Math.round((count / maxTrack) * 100) : 0;
        return '<div class="track-row"><span class="track-name">' + escapeHtml(t.label) + '</span>' +
            '<span class="track-bar"><span class="track-bar-fill" style="width:' + pct + '%"></span></span>' +
            '<span class="track-count">' + count + '</span></div>';
    }).join('');
    const trackCard = '<div class="stat-card" style="grid-column: span 2; min-width: 0;">' +
        '<span class="stat-label">By Track</span><div class="track-breakdown">' + trackRows + '</div></div>';

    return verdict + comps + '<div class="stat-grid">' + totalCard + recencyCard + trackCard + '</div>';
}

async function loadUserStats() {
    const skeleton = document.getElementById('statsSkeleton');
    const content = document.getElementById('statsContent');
    const empty = document.getElementById('statsEmpty');
    const errorBox = document.getElementById('statsError');
    const summary = document.getElementById('personalitySummary');
    const summaryText = document.getElementById('personalitySummaryText');
    const badgeSlot = document.getElementById('freeBadgeSlot');
    const emptyBadgeSlot = document.getElementById('emptyFreeBadgeSlot');

    try {
        const response = await fetch('/api/user/insights');
        if (!response.ok) {
            throw new Error('Insights request failed: ' + response.status);
        }
        const data = await response.json();

        setHidden(skeleton, true);

        const remaining = Number(data.free_calls_remaining);
        if (badgeSlot) badgeSlot.innerHTML = freeBadgeMarkup(remaining);

        const total = Number(data.total_sessions) || 0;

        if (total <= 0) {
            if (emptyBadgeSlot) emptyBadgeSlot.innerHTML = freeBadgeMarkup(remaining);
            setHidden(content, true);
            setHidden(summary, true);
            setHidden(empty, false);
            return;
        }

        content.innerHTML = renderInsightsContent(data);
        setHidden(content, false);
        setHidden(empty, true);

        const line = buildPersonalitySummary(data);
        if (line && summaryText) {
            summaryText.textContent = line;
            setHidden(summary, false);
        } else {
            setHidden(summary, true);
        }
    } catch (error) {
        console.error('[DASHBOARD] Failed to load user insights:', error);
        setHidden(skeleton, true);
        setHidden(content, true);
        setHidden(empty, true);
        setHidden(errorBox, false);
    }
}

async function loadApiKeysStatus() {
    const statusDiv = document.getElementById('apiKeysStatus');

    try {
        const response = await fetch('/api/user/keys/status');
        const data = await response.json();

        if (data.has_keys) {
            statusDiv.innerHTML = `
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                        <polyline points="22 4 12 14.01 9 11.01"/>
                    </svg>
                    <div>
                        <p style="font-weight: 500; margin-bottom: 0.25rem;">API Keys Configured</p>
                        <p style="color: var(--text-muted); font-size: 0.8125rem;">All required keys are set</p>
                    </div>
                </div>
            `;
        } else {
            statusDiv.innerHTML = `
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <line x1="12" y1="8" x2="12" y2="12"/>
                        <line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    <div>
                        <p style="font-weight: 500; margin-bottom: 0.25rem;">API Keys Not Set</p>
                        <p style="color: var(--text-muted); font-size: 0.8125rem;">Configure your keys to start interviewing</p>
                    </div>
                </div>
            `;
        }
    } catch (error) {
        console.error('[DASHBOARD] Failed to load API keys status:', error);
        statusDiv.innerHTML = `
            <p style="color: var(--error); font-size: 0.875rem;">Failed to load API keys status</p>
        `;
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initDashboard);
