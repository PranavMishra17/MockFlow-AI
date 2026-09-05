/*
 * MockFlow — "John Doe" live example data + renderers.
 *
 * Brand-new users (0 sessions / nothing to compare) should SEE the moat before
 * they've done anything. This module ships believable sample data and a few
 * compact renderers, each clearly badged "EXAMPLE — this is what yours will
 * look like". It is FRONT-END ONLY: no backend, no API, no data-contract change.
 *
 * Shapes mirror the real contracts so the examples are honest:
 *   - verdict  -> the /api/feedback/verdict shape (overall/context/signals/...)
 *   - insights -> the /api/user/insights shape (radar/latest/best_lines/...)
 *   - compare  -> the /api/user/compare shape (sessions/competencies/...)
 *
 * Depends on radar.js (window.MockFlowRadar) and utils.js (escapeHtml) when its
 * renderers are used; both are loaded before this on every page that needs it.
 */
(function (global) {
    'use strict';

    function esc(s) {
        if (global.escapeHtml) return global.escapeHtml(s);
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function sigil(n) { return (global.MockFlowRadar && global.MockFlowRadar.sigil) ? global.MockFlowRadar.sigil(n || 14) : ''; }

    var RECO_LABEL = {strong_no_hire:'Strong No-Hire', no_hire:'No-Hire', lean_no_hire:'Leaning No-Hire',
        on_fence:'On the Fence', lean_hire:'Leaning Hire', hire:'Hire', strong_hire:'Strong Hire'};
    var RECO_TONE = {strong_no_hire:'neg', no_hire:'neg', lean_no_hire:'neg',
        on_fence:'mid', lean_hire:'pos', hire:'pos', strong_hire:'pos'};
    var LEVEL_LABEL = {below_intern:'developing', intern:'intern', new_grad:'new-grad', mid:'mid-level', above_mid:'above mid-level'};
    var BAND_LABEL = {outstanding:'Outstanding', solid:'Solid', borderline:'Borderline', poor:'Poor', cannot_determine:'Not shown'};

    // ── the sample candidate: "John Doe", a backend SWE at a new-grad bar ──
    var VERDICT = {
        overall: { recommendation: 'lean_hire', confidence: 'medium', level_read: 'new_grad',
            headline: 'Sharp problem framing and a real point of view on trade-offs — ownership is the one thing holding the call back.' },
        context: { track: 'behavioral', role: 'swe', seniority: 'new_grad', archetype: 'big_tech' },
        signals: [
            { name: 'Problem-solving', band: 'outstanding',
              reasoning: 'Broke the ambiguous prompt into parts before committing and compared two designs out loud.',
              evidence: ["I'd scope it first — clarify the read/write ratio, then weigh a cache against a read replica"], to_raise: '' },
            { name: 'Communication & structure', band: 'solid',
              reasoning: 'Signposted the answer and kept each part tight.',
              evidence: ["Let me give you the headline, then the three reasons behind it"], to_raise: 'Lead with the result, then the journey.' },
            { name: 'Ownership', band: 'borderline',
              reasoning: "Defaulted to 'we'; the personal decision stayed fuzzy under follow-up.",
              evidence: ['We shipped it and the numbers looked good afterwards'],
              to_raise: "Say 'I decided / I measured', and name the metric you personally moved." },
            { name: 'Impact & metrics', band: 'solid',
              reasoning: 'Quantified one outcome credibly.',
              evidence: ['That dropped our p99 from 800ms to about 540ms'], to_raise: 'Tie every story to a number and the call it changed.' }
        ],
        differentiators: ['A genuine opinion on the trade-off, not just the textbook answer.'],
        delivery: { pace_available: true, wpm: 162, wpm_band: 'brisk', wpm_target: '130-160',
            filler_total: 11, filler_per_100w: 4.2, filler_per_min: 6.1,
            filler_band: 'moderate', filler_target: '<=3.3/100 words',
            word_count: 1040, sentence_count: 74, filler_breakdown: { like: 7, basically: 4 },
            top_crutch_word: { word: 'like', count: 7 }, talk_ratio: 0.61, longest_monologue_s: 44.0 },
        gap_to_next: { signal: 'Ownership', from_band: 'borderline', to_band: 'solid',
            move: "Say 'I decided / I measured', and name the metric you personally moved." },
        great_answers: 1
    };

    // ── the personality blob (2 sessions in) ──
    var INSIGHTS = {
        total_sessions: 2,
        lifetime: { sessions: 2, words: 1940, sentences: 138, great_answers: 2, fillers: 27,
            top_crutch_word: { word: 'like', count: 16 } },
        radar: { level: 'new_grad', axes: [
            { key: 'communication', label: 'Communication', you_score: 3, target_score: 3 },
            { key: 'problem_solving', label: 'Problem-solving', you_score: 4, target_score: 3 },
            { key: 'technical_depth', label: 'Technical depth', you_score: 3, target_score: 3 },
            { key: 'ownership_impact', label: 'Ownership & impact', you_score: 2, target_score: 3 },
            { key: 'domain_rigor', label: 'Role & domain rigor', you_score: 3, target_score: 3 } ] },
        latest: { recommendation: 'lean_hire', level_read: 'new_grad', track: 'behavioral',
            headline: VERDICT.overall.headline, date: '2026-06-11T15:00:00' },
        strongest: { key: 'problem_solving', label: 'Problem-solving' },
        weakest: { key: 'ownership_impact', label: 'Ownership & impact' },
        best_lines: [
            { quote: "I'd scope it first — clarify the read/write ratio, then weigh a cache against a read replica",
              band: 'outstanding', competency_label: 'Problem-solving', track: 'behavioral' },
            { quote: 'That dropped our p99 from 800ms to about 540ms', band: 'solid', competency_label: 'Impact & metrics', track: 'behavioral' }
        ],
        recurring_to_raise: [{ signal: 'Ownership', competency_label: 'Ownership & impact', count: 2,
            move: "Say 'I decided / I measured', and name the metric you personally moved." }]
    };

    // ── two sessions to compare (older "warm-up" vs newer, improved) ──
    var COMPARE = {
        sessions: [
            { recommendation: 'on_fence', level_read: 'new_grad', track: 'behavioral', date: '2026-06-03T10:00:00' },
            { recommendation: 'lean_hire', level_read: 'new_grad', track: 'behavioral', date: '2026-06-11T15:00:00' }
        ],
        competencies: [
            { key: 'problem_solving', label: 'Problem-solving', bands: ['solid', 'outstanding'], scores: [3, 4], delta: 1 },
            { key: 'communication', label: 'Communication', bands: ['borderline', 'solid'], scores: [2, 3], delta: 1 },
            { key: 'technical_depth', label: 'Technical depth', bands: ['solid', 'solid'], scores: [3, 3], delta: 0 },
            { key: 'ownership_impact', label: 'Ownership & impact', bands: ['poor', 'borderline'], scores: [1, 2], delta: 1 }
        ],
        improved: ['Problem-solving climbed Solid → Outstanding', 'Communication moved Borderline → Solid', 'Ownership lifted off the floor'],
        lagged: ['Ownership & impact is still only Borderline — name what YOU decided']
    };

    // ── a reusable example ribbon ──
    function ribbon(sub) {
        return '<div class="ex-ribbon">' + sigil(13) +
            '<span class="ex-ribbon-tag">Example</span>' +
            '<span class="ex-ribbon-sub">' + esc(sub || 'this is what yours will look like') + '</span></div>';
    }

    // ── (b) a compact sample hiring-verdict dossier (mini) ──
    function renderMiniDossier() {
        var v = VERDICT, o = v.overall, tone = RECO_TONE[o.recommendation];
        var html = '<div class="ex-dossier ex-card">';
        html += ribbon('a real hiring verdict — yours after one interview');
        html += '<div class="ex-d-hero tone-' + tone + '">';
        html += '<div class="ex-d-stamp" aria-hidden="true">' + sigil(34) + '</div>';
        html += '<div class="ex-d-call"><span class="ex-d-kicker">Where John would land today</span>' +
            '<span class="ex-d-reco">' + esc(RECO_LABEL[o.recommendation]) + '</span>' +
            '<span class="ex-d-sub">reads at <strong>' + esc(LEVEL_LABEL[o.level_read]) + '</strong> · ' + esc(o.confidence) + ' confidence</span></div>';
        html += '</div>';
        html += '<p class="ex-d-headline">' + esc(o.headline) + '</p>';
        // two evidence rows
        html += '<div class="ex-d-evlist">';
        v.signals.slice(0, 2).forEach(function (s) {
            html += '<div class="ex-d-ev"><div class="ex-d-ev-top"><span class="ex-d-ev-name">' + esc(s.name) + '</span>' +
                '<span class="bandpill bandpill-' + s.band + '">' + esc(BAND_LABEL[s.band] || s.band) + '</span></div>';
            if (s.evidence && s.evidence[0]) html += '<blockquote class="ex-d-quote">“' + esc(s.evidence[0]) + '”</blockquote>';
            html += '</div>';
        });
        html += '</div>';
        html += '<div class="ex-cta-row"><a class="ex-cta" href="/start">Get my real verdict →</a></div>';
        html += '</div>';
        return html;
    }

    // ── (a) a full sample personality card (dashboard empty state) ──
    function renderSamplePersonality() {
        var d = INSIGHTS, latest = d.latest, tone = RECO_TONE[latest.recommendation];
        var radar = global.MockFlowRadar ? global.MockFlowRadar.build({ axes: d.radar.axes, size: 300 }) : '';
        var html = '<div class="ex-persona ex-card">';
        html += ribbon('a 2-session personality — yours starts after interview one');
        // a slim player card
        html += '<div class="ex-pc tone-' + tone + '"><div class="ex-pc-sigil">' + sigil(34) + '</div>' +
            '<div class="ex-pc-id"><span class="ex-pc-eyebrow">Candidate card · John Doe</span>' +
            '<span class="ex-pc-name">' + esc(RECO_LABEL[latest.recommendation]) + '</span>' +
            '<span class="ex-pc-sub">reads at <strong>' + esc(LEVEL_LABEL[latest.level_read]) + '</strong> level</span></div>' +
            '<div class="ex-pc-badge"><span>Signature</span><strong>' + esc(d.strongest.label) + '</strong></div></div>';
        // mini stat strip
        html += '<div class="ex-pc-stats">' +
            exStat('Sessions', d.lifetime.sessions) +
            exStat('Words', Number(d.lifetime.words).toLocaleString()) +
            exStat('Great answers', '★ ' + d.lifetime.great_answers) +
            exStat('Top crutch', '“' + esc(d.lifetime.top_crutch_word.word) + '” ×' + d.lifetime.top_crutch_word.count) +
            '</div>';
        // the radar
        if (radar) html += '<div class="ex-pc-radar">' + radar +
            '<p class="radar-hint">Hover a point to see the band &amp; the gap to the bar</p>' +
            '<div class="radar-legend"><span class="rl rl-you">John</span><span class="rl rl-target">new-grad bar</span></div></div>';
        // best line
        var bl = d.best_lines[0];
        html += '<div class="ex-pc-best"><span class="ex-pc-best-tag">★ Best line</span>' +
            '<span class="ex-pc-best-q">“' + esc(bl.quote) + '”</span></div>';
        html += '<div class="ex-cta-row"><a class="ex-cta" href="/start">Build my real card →</a></div>';
        html += '</div>';
        return html;
    }
    function exStat(label, val) {
        return '<div class="ex-stat"><span class="ex-stat-l">' + esc(label) + '</span><span class="ex-stat-v">' + val + '</span></div>';
    }

    // ── (c) a sample two-session compare card ──
    function renderSampleCompare() {
        var c = COMPARE, A = c.sessions[0], B = c.sessions[1];
        var axes = c.competencies.map(function (x) { return { key: x.key, label: x.label, you_score: x.scores[1] }; });
        var prev = {}; c.competencies.forEach(function (x) { prev[x.key] = x.scores[0]; });
        var radar = (global.MockFlowRadar && c.competencies.length >= 3)
            ? global.MockFlowRadar.build({ axes: axes, previous: prev, showTarget: false, size: 300 }) : '';
        function fdate(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); }
        var html = '<div class="ex-compare ex-card">';
        html += ribbon('two of John\'s sessions — compare yours once you have two');
        html += '<div class="ex-cmp-heads">' +
            exCmpChip(A, fdate(A.date)) + '<span class="ex-cmp-arrow">→</span>' + exCmpChip(B, fdate(B.date)) + '</div>';
        if (radar) html += '<div class="ex-cmp-radar">' + radar +
            '<div class="radar-legend"><span class="rl rl-you">' + esc(fdate(B.date)) + '</span><span class="rl rl-prev">' + esc(fdate(A.date)) + '</span></div></div>';
        html += '<div class="ex-cmp-rows">';
        c.competencies.forEach(function (x) {
            var dir = x.delta > 0 ? 'up' : (x.delta < 0 ? 'down' : 'flat');
            var arr = x.delta > 0 ? '↑' : (x.delta < 0 ? '↓' : '→');
            html += '<div class="ex-cmp-row"><span class="ex-cmp-name">' + esc(x.label) + '</span>' +
                '<span class="bandpill bandpill-' + x.bands[0] + '">' + esc(BAND_LABEL[x.bands[0]]) + '</span>' +
                '<span class="ex-cmp-delta ' + dir + '">' + arr + '</span>' +
                '<span class="bandpill bandpill-' + x.bands[1] + '">' + esc(BAND_LABEL[x.bands[1]]) + '</span></div>';
        });
        html += '</div>';
        html += '<div class="ex-cta-row"><a class="ex-cta" href="/start">Run my sessions →</a></div>';
        html += '</div>';
        return html;
    }
    function exCmpChip(s, date) {
        var tone = RECO_TONE[s.recommendation];
        return '<div class="ex-cmp-chip tone-' + tone + '"><span class="ex-cmp-chip-d">' + esc(date) + '</span>' +
            '<span class="ex-cmp-chip-r">' + esc(RECO_LABEL[s.recommendation]) + '</span></div>';
    }

    global.MockFlowExamples = {
        verdict: VERDICT, insights: INSIGHTS, compare: COMPARE,
        renderMiniDossier: renderMiniDossier,
        renderSamplePersonality: renderSamplePersonality,
        renderSampleCompare: renderSampleCompare
    };
})(window);
