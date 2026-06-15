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

function trackLabel(tr) {
    const m = { intro: 'Intro', behavioral: 'Behavioral', technical_voice: 'Technical', coding: 'Coding', technical_coding: 'Coding' };
    return m[tr] || tr;
}

// ── [A] the epic stat band — countable, personal, each tied to a signal/action ──
function statTile(label, value, hint, opts) {
    opts = opts || {};
    const cls = 'pp-stat' + (opts.accent ? ' pp-stat-accent' : '') + (opts.onclick ? ' pp-stat-link' : '');
    const attrs = opts.onclick ? ' role="button" tabindex="0" onclick="' + opts.onclick +
        '" onkeydown="if(event.key===\'Enter\'){this.click();}"' : '';
    return '<div class="' + cls + '"' + attrs + '>' +
        '<span class="pp-stat-label">' + label + '</span>' +
        '<span class="pp-stat-value">' + value + '</span>' +
        (hint ? '<span class="pp-stat-hint">' + hint + '</span>' : '') + '</div>';
}

// The stat band is framed as a "player card": a banner (ring sigil + the
// latest hiring verdict as the headline) over a grid of countable stat tiles.
function ringSigil(size) {
    return (window.MockFlowRadar && window.MockFlowRadar.sigil) ? window.MockFlowRadar.sigil(size || 16) : '';
}

function renderStatBand(data) {
    const lt = data.lifetime || {};
    const latest = data.latest || {};
    const best = (data.best_lines && data.best_lines[0]) || null;
    const scrollBest = "var el=document.getElementById('ppBestLines'); if(el){el.scrollIntoView({behavior:'smooth'});}";
    const tone = RECO_TONE[latest.recommendation] || 'mid';

    let t = '';
    t += statTile('Sessions', (lt.sessions || data.total_sessions || 0), 'completed');
    if (lt.words) t += statTile('Words spoken', Number(lt.words).toLocaleString(), 'across every answer');
    if (lt.sentences) t += statTile('Sentences', Number(lt.sentences).toLocaleString(), 'thoughts delivered');
    t += statTile('Great answers', '<span class="pp-star">★</span> ' + (lt.great_answers || 0),
        'outstanding signals', { accent: true, onclick: best ? scrollBest : null });
    if (lt.fillers) {
        const crutch = lt.top_crutch_word ? ('“' + escapeHtml(lt.top_crutch_word.word) + '” ×' + lt.top_crutch_word.count) : 'well controlled';
        t += statTile('Filler words', Number(lt.fillers).toLocaleString(), 'top crutch: ' + crutch);
    }
    const recency = formatRelativeDate(data.latest && data.latest.date);
    if (recency) t += statTile('Last active', escapeHtml(recency), 'keep the streak');
    if (best) {
        const teaser = '<span class="pp-bestline-teaser">“' + escapeHtml(best.quote.slice(0, 52)) + (best.quote.length > 52 ? '…' : '') + '”</span>';
        t += statTile('Your best line', teaser, best.competency_label || '', { onclick: scrollBest });
    }

    // the banner: a player-card header. Latest verdict reads as the "name".
    let banner = '<div class="pp-card-banner tone-' + tone + '">';
    banner += '<div class="pp-card-sigil" aria-hidden="true">' + ringSigil(40) + '</div>';
    banner += '<div class="pp-card-id">';
    banner += '<span class="pp-card-eyebrow">Candidate card' + (latest.track ? ' · ' + escapeHtml(trackLabel(latest.track)) : '') + '</span>';
    banner += '<span class="pp-card-name">' + escapeHtml(RECO_LABEL[latest.recommendation] || 'In progress') + '</span>';
    if (LEVEL_LABEL[latest.level_read]) banner += '<span class="pp-card-sub">reads at <strong>' + LEVEL_LABEL[latest.level_read] + '</strong> level today</span>';
    banner += '</div>';
    if (data.strongest && data.strongest.label) {
        banner += '<div class="pp-card-badge"><span class="pp-card-badge-label">Signature</span>' +
            '<span class="pp-card-badge-val">' + escapeHtml(data.strongest.label) + '</span></div>';
    }
    banner += '</div>';

    return '<div class="pp-playercard tone-' + tone + '">' + banner +
        '<div class="pp-statband">' + t + '</div></div>';
}

// ── [B] the competency radar vs the target-level bar ──
function radarCaption(radar) {
    if (!radar || !radar.axes) return '';
    const meas = radar.axes.filter(a => a.you_score != null);
    if (!meas.length) return '<p class="radar-caption">Take an interview to map your competencies against the bar.</p>';
    const below = meas.filter(a => a.target_score != null && a.you_score < a.target_score);
    const lvl = LEVEL_LABEL[radar.level] || radar.level || 'target';
    const at = meas.length - below.length;
    let msg = 'At or above the ' + escapeHtml(lvl) + ' bar on <strong>' + at + ' of ' + meas.length + '</strong>';
    msg += below.length ? ' — push ' + below.map(a => escapeHtml(a.label)).join(' &amp; ') + ' to clear it everywhere.'
                        : ' — you clear the bar across the board.';
    return '<p class="radar-caption">' + msg + '</p>';
}

function renderRadarSection(data) {
    if (!data.radar || !window.MockFlowRadar) return '';
    const lvl = LEVEL_LABEL[data.radar.level] || data.radar.level || 'target';
    const svg = window.MockFlowRadar.build({ axes: data.radar.axes, size: 340 });
    return '<div class="pp-block pp-radar">' +
        '<div class="pp-sub-title">Where you stand vs the ' + escapeHtml(lvl) + ' bar</div>' +
        svg + radarCaption(data.radar) +
        '<div class="radar-legend"><span class="rl rl-you">You</span><span class="rl rl-target">' + escapeHtml(lvl) + ' bar</span></div>' +
        '</div>';
}

// ── [C] trajectory: latest verdict + recommendation sparkline + competency rows ──
function renderRecoSpark(series) {
    const pts = (series || []).filter(r => r.index != null);
    if (pts.length < 2) return '';
    const W = 240, H = 46, pad = 5, n = pts.length;
    const coords = pts.map((r, i) => [pad + (i / (n - 1)) * (W - 2 * pad), H - pad - (r.index / 6) * (H - 2 * pad)]);
    const last = pts[pts.length - 1], tone = RECO_TONE[last.recommendation] || 'mid', lc = coords[coords.length - 1];
    return '<svg class="reco-spark" viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true">' +
        '<polyline points="' + coords.map(c => c[0].toFixed(1) + ',' + c[1].toFixed(1)).join(' ') + '" fill="none"/>' +
        '<circle class="spark-dot dot-' + tone + '" cx="' + lc[0].toFixed(1) + '" cy="' + lc[1].toFixed(1) + '" r="3.5"/></svg>';
}

function renderTrajectorySection(data) {
    const latest = data.latest || {};
    const tone = RECO_TONE[latest.recommendation] || 'mid';
    let html = '<div class="insight-verdict tone-' + tone + '">';
    html += '<span class="iv-eyebrow">Latest verdict' + (latest.track ? ' · ' + escapeHtml(trackLabel(latest.track)) : '') + '</span>';
    html += '<span class="iv-reco">' + escapeHtml(RECO_LABEL[latest.recommendation] || '—') + '</span>';
    if (LEVEL_LABEL[latest.level_read]) html += '<span class="iv-level">performing at <strong>' + LEVEL_LABEL[latest.level_read] + '</strong> level</span>';
    if (latest.headline) html += '<p class="iv-headline">' + escapeHtml(latest.headline) + '</p>';
    const spark = renderRecoSpark(data.reco_series);
    if (spark) {
        const n = (data.reco_series || []).filter(r => r.index != null).length;
        html += '<div class="iv-spark">' + spark + '<span class="iv-spark-cap">your last ' + n + ' sessions</span></div>';
    }
    html += '</div>';

    if (data.competencies && data.competencies.length) {
        const rows = data.competencies.map(function (c) {
            const t = TREND_META[c.trend] || TREND_META.flat;
            const pct = Math.round((Number(c.latest_score) / 4) * 100);
            return '<div class="comp-row"><span class="comp-name">' + escapeHtml(c.label) + '</span>' +
                '<span class="comp-bar"><span class="comp-fill band-' + c.latest_band + '" style="width:' + pct + '%"></span></span>' +
                '<span class="comp-band band-chip-' + c.latest_band + '">' + (BAND_LABEL[c.latest_band] || c.latest_band) + '</span>' +
                '<span class="comp-trend trend-' + t.cls + '" title="' + t.label + ' (' + c.sessions + ' sessions)">' + t.icon + '</span></div>';
        }).join('');
        html += '<div class="insight-comps"><div class="ic-title">Competencies — latest band &amp; trend</div>' + rows + '</div>';
    }

    const tracks = data.by_track || {};
    const chips = TRACK_META.filter(tk => Number(tracks[tk.key])).map(tk =>
        '<span class="tt-chip">' + escapeHtml(tk.label) + ' <strong>' + Number(tracks[tk.key]) + '</strong></span>').join('');
    if (chips) html += '<div class="tt-strip">' + chips + '</div>';

    return '<div class="pp-block">' + html + '</div>';
}

// ── [D] cross-track trait stability ──
function stabilityCallout(cbt, comps, tracks) {
    const bandScore = { poor: 1, borderline: 2, solid: 3, outstanding: 4 };
    let best = null;
    comps.forEach(c => {
        const byT = cbt[c.key] || {};
        const vals = tracks.filter(tr => byT[tr]).map(tr => ({ tr, b: byT[tr], s: bandScore[byT[tr]] || 0 }));
        if (vals.length >= 2) {
            vals.sort((a, b) => b.s - a.s);
            const d = vals[0].s - vals[vals.length - 1].s;
            if (d > 0 && (!best || d > best.d)) best = { d, c, hi: vals[0], lo: vals[vals.length - 1] };
        }
    });
    if (!best) return '';
    return 'Your <strong>' + escapeHtml(best.c.label.toLowerCase()) + '</strong> is ' +
        (BAND_LABEL[best.hi.b] || best.hi.b).toLowerCase() + ' in ' + escapeHtml(trackLabel(best.hi.tr).toLowerCase()) +
        ' but ' + (BAND_LABEL[best.lo.b] || best.lo.b).toLowerCase() + ' in ' + escapeHtml(trackLabel(best.lo.tr).toLowerCase()) +
        ' — context changes how you show up.';
}

function renderStability(data) {
    const cbt = data.competency_by_track || {};
    const comps = (data.competencies || []).filter(c => cbt[c.key]);
    const trackSet = {};
    Object.keys(cbt).forEach(k => Object.keys(cbt[k]).forEach(tr => { trackSet[tr] = true; }));
    const tracks = Object.keys(trackSet);
    if (tracks.length < 2 || !comps.length) return '';
    let cells = '<span class="stab-cell stab-corner"></span>';
    tracks.forEach(tr => { cells += '<span class="stab-cell stab-th">' + escapeHtml(trackLabel(tr)) + '</span>'; });
    comps.forEach(c => {
        cells += '<span class="stab-cell stab-name">' + escapeHtml(c.label) + '</span>';
        tracks.forEach(tr => {
            const band = (cbt[c.key] || {})[tr];
            cells += band ? '<span class="stab-cell"><span class="bandpill bandpill-' + band + '">' + (BAND_LABEL[band] || band) + '</span></span>'
                          : '<span class="stab-cell stab-empty">—</span>';
        });
    });
    const grid = '<div class="stab-grid" style="grid-template-columns: minmax(6.5rem,1.2fr) repeat(' + tracks.length + ', minmax(0,1fr));">' + cells + '</div>';
    const callout = stabilityCallout(cbt, comps, tracks);
    return '<div class="pp-block pp-stability"><div class="pp-sub-title">How your traits hold up across tracks</div>' +
        grid + (callout ? '<p class="stab-callout">' + callout + '</p>' : '') + '</div>';
}

// ── [E] your best lines — the highlight reel ──
function renderBestLines(data) {
    const lines = data.best_lines || [];
    let html = '<div class="pp-block pp-bestlines" id="ppBestLines"><div class="pp-sub-title">Your best lines ' +
        '<span class="pp-sub-note">moments a hiring manager would remember</span></div>';
    if (!lines.length) {
        return html + '<div class="bl-empty">Your standout answers will be collected here. Land an outstanding signal to start the reel.</div></div>';
    }
    html += '<div class="bl-rail">';
    lines.forEach(l => {
        html += '<div class="bl-card"><div class="bl-quote">“' + escapeHtml(l.quote) + '”</div>' +
            '<div class="bl-meta"><span class="bandpill bandpill-' + l.band + '">' + (BAND_LABEL[l.band] || l.band) + '</span> ' +
            escapeHtml(l.competency_label || '') + (l.track ? ' · ' + escapeHtml(trackLabel(l.track)) : '') + '</div></div>';
    });
    return html + '</div></div>';
}

// ── [F] work on this next — one prioritized action ──
function renderNext(data) {
    const rtr = (data.recurring_to_raise && data.recurring_to_raise[0]) || null;
    const weakest = data.weakest || null;
    if (!rtr && !weakest) return '';
    let body = '<strong>' + escapeHtml((rtr && (rtr.competency_label || rtr.signal)) || weakest.label) + '</strong>';
    if (rtr && rtr.count > 1) body += ' — your recurring gap across ' + rtr.count + ' sessions.';
    else if (weakest) body += ' — your lowest signal right now.';
    if (rtr && rtr.move) body += ' ' + escapeHtml(rtr.move);
    const items = (data.recurring_to_raise || []).slice(0, 3).map(r =>
        '<li>' + escapeHtml(r.competency_label || r.signal) + (r.move ? ': ' + escapeHtml(r.move) : '') + '</li>').join('');
    let html = '<div class="pp-next"><div class="pp-next-label">Work on this next</div><p class="pp-next-body">' + body + '</p>';
    if (items) html += '<ul class="pp-next-list">' + items + '</ul>';
    return html + '<a class="pp-next-cta" href="/start">Practice this →</a></div>';
}

function renderInsightsContent(data) {
    return renderStatBand(data) +
        renderRadarSection(data) +
        renderTrajectorySection(data) +
        renderStability(data) +
        renderBestLines(data) +
        renderNext(data);
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
