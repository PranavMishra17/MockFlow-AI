/*
 * MockFlowRadar — a hand-rolled SVG competency "sonar" radar (no chart library).
 * Shared by the dashboard personality, the compare view, the feedback session
 * card, and the landing teaser.
 *
 * build(opts) -> SVG string. opts:
 *   axes:      [{ key, label, you_score, target_score }]  (scores 1..4, null = no data)
 *   previous:  { competencyKey: score }   optional 3rd polygon (e.g. a 2nd session)
 *   size:      px (square viewBox); default 320
 *   compact:   true -> no axis labels, tighter (for the landing mini-radar)
 *   showTarget: default true -> draw the dashed target polygon + deficit wedges
 *   interactive: default true (false in compact) -> hover/focus axis hotspots
 *                that reveal a tooltip (band + gap to the target) and a sonar
 *                center-out draw-in on first reveal.
 *
 * Interactivity is 100% declarative (CSS :hover/:focus on hotspots drives the
 * tooltip + spoke highlight), so it survives being injected via innerHTML by any
 * caller — no JS wiring needed. Reduced-motion is respected in radar.css.
 */
(function (global) {
    'use strict';

    var BAND_WORD = { 1: 'Poor', 2: 'Borderline', 3: 'Solid', 4: 'Outstanding' };

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    // A tiny concentric-ring "orb" sigil — echoes the brand interviewer. Inline
    // SVG string so it can be dropped into any eyebrow/kicker.
    function sigil(size) {
        size = size || 16;
        var c = size / 2;
        return '<svg class="ring-sigil" width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size +
            '" aria-hidden="true" focusable="false">' +
            '<circle cx="' + c + '" cy="' + c + '" r="' + (c - 1) + '" class="rs-ring rs-ring-3"/>' +
            '<circle cx="' + c + '" cy="' + c + '" r="' + (c * 0.62) + '" class="rs-ring rs-ring-2"/>' +
            '<circle cx="' + c + '" cy="' + c + '" r="' + (c * 0.26) + '" class="rs-core"/>' +
            '</svg>';
    }

    function build(opts) {
        opts = opts || {};
        var axes = opts.axes || [];
        var n = axes.length || 5;
        var size = opts.size || 320;
        var compact = !!opts.compact;
        var showTarget = opts.showTarget !== false;
        var interactive = opts.interactive !== false && !compact;
        var cx = size / 2, cy = size / 2;
        var R = size / 2 - (compact ? 14 : 54);

        function point(score, i) {
            var ang = (-90 + i * (360 / n)) * Math.PI / 180;
            var r = (Math.max(0, Math.min(4, score || 0)) / 4) * R;
            return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
        }
        function poly(scores) {
            return scores.map(function (s, i) {
                var p = point(s, i);
                return p[0].toFixed(1) + ',' + p[1].toFixed(1);
            }).join(' ');
        }

        var cls = 'radar-svg' + (interactive ? ' radar-interactive' : '');
        var svg = '<svg class="' + cls + '" viewBox="0 0 ' + size + ' ' + size +
            '" role="img" aria-label="Competency radar" style="--radar-r:' + R.toFixed(1) + 'px">';

        // soft radial "sonar" field behind the grid (atmosphere, not a flat fill)
        svg += '<circle class="radar-field" cx="' + cx + '" cy="' + cy + '" r="' + R.toFixed(1) + '"/>';

        // grid: 4 concentric polygon rings (band gridlines 1..4) + spokes
        for (var ring = 1; ring <= 4; ring++) {
            var rp = [];
            for (var i = 0; i < n; i++) rp.push(point(ring, i));
            svg += '<polygon class="radar-ring" points="' + rp.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') + '"/>';
        }
        for (var s = 0; s < n; s++) {
            var tipP = point(4, s);
            svg += '<line class="radar-spoke" data-spoke="' + s + '" x1="' + cx + '" y1="' + cy + '" x2="' + tipP[0].toFixed(1) + '" y2="' + tipP[1].toFixed(1) + '"/>';
        }

        // deficit wedges + target polygon (you-below-bar reads instantly)
        if (showTarget) {
            for (var d = 0; d < n; d++) {
                var a = axes[d];
                if (a && a.you_score != null && a.target_score != null && a.you_score < a.target_score) {
                    var py = point(a.you_score, d), pt = point(a.target_score, d);
                    svg += '<line class="radar-deficit" x1="' + py[0].toFixed(1) + '" y1="' + py[1].toFixed(1) +
                           '" x2="' + pt[0].toFixed(1) + '" y2="' + pt[1].toFixed(1) + '"/>';
                }
            }
            svg += '<polygon class="radar-target" points="' + poly(axes.map(function (a) { return a ? a.target_score : 0; })) + '"/>';
        }

        // optional previous-session polygon
        if (opts.previous) {
            var prevScores = axes.map(function (a) { var v = opts.previous[a.key]; return v == null ? 0 : v; });
            if (axes.some(function (a) { return opts.previous[a.key] != null; })) {
                svg += '<polygon class="radar-prev" points="' + poly(prevScores) + '"/>';
            }
        }

        // your polygon (only if any axis has data)
        var hasYou = axes.some(function (a) { return a && a.you_score != null; });
        if (hasYou) {
            svg += '<polygon class="radar-you" points="' + poly(axes.map(function (a) { return a ? a.you_score : 0; })) + '"/>';
        }

        // vertex dots on your polygon (visual anchor + hover lift target)
        if (hasYou) {
            for (var v2 = 0; v2 < n; v2++) {
                var ax2 = axes[v2];
                if (!ax2 || ax2.you_score == null) continue;
                var vp = point(ax2.you_score, v2);
                svg += '<circle class="radar-vertex" data-vx="' + v2 + '" cx="' + vp[0].toFixed(1) + '" cy="' + vp[1].toFixed(1) + '" r="3.4"/>';
            }
        }

        // axis labels (skipped in compact mode)
        if (!compact) {
            for (var L = 0; L < n; L++) {
                var ax = axes[L];
                if (!ax) continue;
                var ang = (-90 + L * (360 / n)) * Math.PI / 180;
                var lx = cx + (R + 16) * Math.cos(ang), ly = cy + (R + 16) * Math.sin(ang);
                var anchor = Math.abs(Math.cos(ang)) < 0.3 ? 'middle' : (Math.cos(ang) > 0 ? 'start' : 'end');
                var dim = ax.you_score == null ? ' radar-axis-dim' : '';
                svg += '<text class="radar-axis-label' + dim + '" data-lbl="' + L + '" x="' + lx.toFixed(1) + '" y="' + ly.toFixed(1) +
                       '" text-anchor="' + anchor + '">' + esc(ax.label) + '</text>';
            }
        }

        // interactive hotspots: one focusable wedge per axis. Pure-CSS :hover/
        // :focus on the <g> drives the spoke highlight + tooltip (declarative so
        // it works through innerHTML). Drawn last so it sits on top.
        if (interactive) {
            for (var h = 0; h < n; h++) {
                var ax3 = axes[h];
                if (!ax3) continue;
                var tip = tooltipFor(ax3);
                var tipP2 = point(4.35, h);
                // a generous invisible hit-wedge (triangle from center to two ring edges)
                var aMid = (-90 + h * (360 / n)) * Math.PI / 180;
                var aLo = aMid - Math.PI / n, aHi = aMid + Math.PI / n;
                var hr = R + (compact ? 8 : 22);
                var p1 = [cx + hr * Math.cos(aLo), cy + hr * Math.sin(aLo)];
                var p2 = [cx + hr * Math.cos(aHi), cy + hr * Math.sin(aHi)];
                svg += '<g class="radar-hotspot" data-axis="' + h + '" tabindex="0" role="button" ' +
                       'aria-label="' + esc(ax3.label + ': ' + tip.plain) + '">';
                svg += '<polygon class="radar-hit" points="' + cx + ',' + cy + ' ' +
                       p1[0].toFixed(1) + ',' + p1[1].toFixed(1) + ' ' + p2[0].toFixed(1) + ',' + p2[1].toFixed(1) + '"/>';
                // tooltip bubble, anchored just past the vertex, hidden until hover/focus
                var tp = point(4.05, h);
                var tx = Math.max(58, Math.min(size - 58, tp[0]));
                var ty = tp[1];
                var below = Math.sin(aMid) > 0.2;
                svg += '<g class="radar-tip" transform="translate(' + tx.toFixed(1) + ',' + ty.toFixed(1) + ')">';
                svg += '<rect class="radar-tip-bg" x="-56" y="' + (below ? 8 : -46) + '" width="112" height="38" rx="8"/>';
                svg += '<text class="radar-tip-name" x="0" y="' + (below ? 23 : -31) + '" text-anchor="middle">' + esc(tip.name) + '</text>';
                svg += '<text class="radar-tip-sub" x="0" y="' + (below ? 36 : -18) + '" text-anchor="middle">' + esc(tip.sub) + '</text>';
                svg += '</g></g>';
            }
        }

        svg += '</svg>';
        return svg;
    }

    // Build the tooltip strings for one axis: band + gap-to-target read.
    function tooltipFor(ax) {
        var name = ax.label || ax.key || '';
        if (ax.you_score == null) {
            return { name: name, sub: 'Not shown yet', plain: 'not shown yet' };
        }
        var band = BAND_WORD[Math.round(ax.you_score)] || '';
        var sub = band;
        if (ax.target_score != null) {
            var gap = ax.target_score - ax.you_score;
            if (gap > 0) sub = band + ' · ' + gap + ' below the bar';
            else if (gap < 0) sub = band + ' · ' + (-gap) + ' above the bar';
            else sub = band + ' · at the bar';
        }
        return { name: name, sub: sub, plain: sub };
    }

    global.MockFlowRadar = { build: build, sigil: sigil };
})(window);
