/*
 * MockFlowRadar — a hand-rolled SVG competency radar (no chart library).
 * Shared by the dashboard personality, the compare view, and the landing teaser.
 *
 * build(opts) -> SVG string. opts:
 *   axes:      [{ key, label, you_score, target_score }]  (scores 1..4, null = no data)
 *   previous:  { competencyKey: score }   optional 3rd polygon (e.g. a 2nd session)
 *   size:      px (square viewBox); default 320
 *   compact:   true -> no axis labels, tighter (for the landing mini-radar)
 *   showTarget: default true -> draw the dashed target polygon + deficit wedges
 */
(function (global) {
    'use strict';

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    function build(opts) {
        opts = opts || {};
        var axes = opts.axes || [];
        var n = axes.length || 5;
        var size = opts.size || 320;
        var compact = !!opts.compact;
        var showTarget = opts.showTarget !== false;
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

        var svg = '<svg class="radar-svg" viewBox="0 0 ' + size + ' ' + size + '" role="img" aria-label="Competency radar">';

        // grid: 4 concentric pentagon rings (the band gridlines 1..4) + spokes
        for (var ring = 1; ring <= 4; ring++) {
            var rp = [];
            for (var i = 0; i < n; i++) rp.push(point(ring, i));
            svg += '<polygon class="radar-ring" points="' + rp.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') + '"/>';
        }
        for (var s = 0; s < n; s++) {
            var tipP = point(4, s);
            svg += '<line class="radar-spoke" x1="' + cx + '" y1="' + cy + '" x2="' + tipP[0].toFixed(1) + '" y2="' + tipP[1].toFixed(1) + '"/>';
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
        if (axes.some(function (a) { return a && a.you_score != null; })) {
            svg += '<polygon class="radar-you" points="' + poly(axes.map(function (a) { return a ? a.you_score : 0; })) + '"/>';
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
                svg += '<text class="radar-axis-label' + dim + '" x="' + lx.toFixed(1) + '" y="' + ly.toFixed(1) +
                       '" text-anchor="' + anchor + '">' + esc(ax.label) + '</text>';
            }
        }

        svg += '</svg>';
        return svg;
    }

    global.MockFlowRadar = { build: build };
})(window);
