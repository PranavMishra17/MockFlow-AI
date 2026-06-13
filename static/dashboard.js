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
    { key: 'technical_coding', label: 'Technical (Coding)' }
];

const TRACK_PERSONA = {
    intro: 'a warm-up specialist',
    behavioral: 'a behavioral candidate',
    technical_voice: 'a technical communicator',
    technical_coding: 'a coding interviewer\'s favorite'
};

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
        return {
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[ch];
    });
}

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

function strongestTrack(tracks) {
    if (!tracks) return null;
    let best = null;
    let bestCount = 0;
    TRACK_META.forEach(function (t) {
        const count = Number(tracks[t.key]) || 0;
        if (count > bestCount) {
            bestCount = count;
            best = t.key;
        }
    });
    return best && bestCount > 0 ? best : null;
}

function buildPersonalitySummary(stats) {
    const parts = [];
    const total = Number(stats.total_interviews) || 0;

    if (total === 1) {
        parts.push('1 interview in');
    } else {
        parts.push(total + ' interviews in');
    }

    const best = strongestTrack(stats.tracks);
    if (best && TRACK_PERSONA[best]) {
        parts.push('strongest as ' + TRACK_PERSONA[best]);
    }

    if (stats.avg_overall_score != null) {
        parts.push('averaging ' + Number(stats.avg_overall_score).toFixed(1) + ' / 5');
    }

    const remaining = Number(stats.free_calls_remaining);
    if (Number.isFinite(remaining) && remaining > 0) {
        parts.push(remaining === 1 ? '1 free interview left' : remaining + ' free interviews left');
    }

    return parts.join(' · ');
}

function renderStatsContent(stats) {
    const total = Number(stats.total_interviews) || 0;
    const avg = stats.avg_overall_score;

    // Average score card
    let avgCard;
    if (avg == null) {
        avgCard =
            '<div class="stat-card">' +
                '<span class="stat-label">Average Score</span>' +
                '<span class="stat-value muted">&mdash;</span>' +
                '<span class="stat-hint">Take your first interview</span>' +
            '</div>';
    } else {
        avgCard =
            '<div class="stat-card accent-green">' +
                '<span class="stat-label">Average Score</span>' +
                '<span class="stat-value">' + Number(avg).toFixed(1) +
                    ' <span class="stat-unit">/ 5</span></span>' +
                '<span class="stat-hint">across all your interviews</span>' +
            '</div>';
    }

    // Recency card
    const recency = formatRelativeDate(stats.last_interview_date);
    const recencyCard =
        '<div class="stat-card">' +
            '<span class="stat-label">Last Active</span>' +
            '<span class="stat-value">' + (recency ? escapeHtml(recency) : '&mdash;') + '</span>' +
            '<span class="stat-hint">' + (recency ? 'keep the streak going' : 'no sessions yet') + '</span>' +
        '</div>';

    // Total card
    const totalCard =
        '<div class="stat-card">' +
            '<span class="stat-label">Total Interviews</span>' +
            '<span class="stat-value">' + total + '</span>' +
            '<span class="stat-hint">' + (total === 1 ? 'session completed' : 'sessions completed') + '</span>' +
        '</div>';

    // Track breakdown card
    const tracks = stats.tracks || {};
    const maxTrack = TRACK_META.reduce(function (m, t) {
        return Math.max(m, Number(tracks[t.key]) || 0);
    }, 0);
    const trackRows = TRACK_META.map(function (t) {
        const count = Number(tracks[t.key]) || 0;
        const pct = maxTrack > 0 ? Math.round((count / maxTrack) * 100) : 0;
        return '<div class="track-row">' +
            '<span class="track-name">' + escapeHtml(t.label) + '</span>' +
            '<span class="track-bar"><span class="track-bar-fill" style="width:' + pct + '%"></span></span>' +
            '<span class="track-count">' + count + '</span>' +
        '</div>';
    }).join('');
    const trackCard =
        '<div class="stat-card" style="grid-column: span 2; min-width: 0;">' +
            '<span class="stat-label">By Track</span>' +
            '<div class="track-breakdown">' + trackRows + '</div>' +
        '</div>';

    return '<div class="stat-grid">' + totalCard + avgCard + recencyCard + trackCard + '</div>';
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
        const response = await fetch('/api/user/stats');
        if (!response.ok) {
            throw new Error('Stats request failed: ' + response.status);
        }
        const stats = await response.json();

        setHidden(skeleton, true);

        const remaining = Number(stats.free_calls_remaining);
        if (badgeSlot) badgeSlot.innerHTML = freeBadgeMarkup(remaining);

        const total = Number(stats.total_interviews) || 0;

        if (total <= 0) {
            // Empty state — surface the free badge to pull them in.
            if (emptyBadgeSlot) emptyBadgeSlot.innerHTML = freeBadgeMarkup(remaining);
            setHidden(content, true);
            setHidden(summary, true);
            setHidden(empty, false);
            return;
        }

        // Has data — render cards + personality line.
        content.innerHTML = renderStatsContent(stats);
        setHidden(content, false);
        setHidden(empty, true);

        const line = buildPersonalitySummary(stats);
        if (line && summaryText) {
            summaryText.textContent = line;
            setHidden(summary, false);
        } else {
            setHidden(summary, true);
        }
    } catch (error) {
        console.error('[DASHBOARD] Failed to load user stats:', error);
        // Fail gracefully: hide skeleton, show a small non-blocking notice.
        // Account info + API keys remain fully functional.
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
