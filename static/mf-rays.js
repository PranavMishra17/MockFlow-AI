/* =============================================================================
   MockFlow-AI · mf-rays.js
   A tiny, dependency-free JS driver for the kit's `.mf-rays` ray ring (see
   animations.css). The CSS gives every ray its geometry — point outward from
   centre, anchored at the rim, growing in HEIGHT. This module owns the per-frame
   HEIGHT so the ring can move like a real voice instead of a fixed CSS loop.

   It mirrors the live interview agent (templates/interview.html), whose demo
   loop drives 64 bars with:
       wave  = sin((i/N) * PI * 4 + phase) * 0.3 + 0.25;   // 4 lobes round the ring
       noise = random() * 0.15;                              // sporadic, voice-like
       target = wave + noise;                                // 0..~0.7
       h[i]   = h[i] * 0.4 + target * 0.6;                   // smoothed, no jitter
       phase += 0.06;                                        // per frame
   and each ray's pixel height = min + h[i] * (max - min).

   Public API — window.MFRays:
     build(ringEl, count)         fill a ring with <span style="--i:N"> children
     animate(ringEl, opts)        run a rAF loop driving every span's height
     intro(orbEl, opts)           choreograph rings -> eyes -> rays, then animate

   Vanilla. Light-only. Reduced-motion safe. Only height/transform/opacity move.
   ============================================================================= */
(function () {
    'use strict';

    var DEFAULTS = {
        count: 56,
        mode: 'voice',
        min: 4,    // resting ray height in px (scaled to ring size when possible)
        max: 38,   // peak ray height in px
        phaseStep: 0.06,
        lobes: 4,  // number of travelling sine lobes around the ring
        smooth: 0.4 // weight of the previous frame; (1 - smooth) is the new target
    };

    function prefersReducedMotion() {
        return typeof window.matchMedia === 'function' &&
            window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    function clamp01(v) {
        return v < 0 ? 0 : (v > 1 ? 1 : v);
    }

    /* If the ring exposes a pixel size (via --mf-rays-size or its own box), scale
       the default min/max so the motion reads right at any card size. Explicit
       opts.min / opts.max always win. */
    function resolveHeights(ringEl, opts) {
        var min = opts.min;
        var max = opts.max;
        if (opts.min == null || opts.max == null) {
            var size = 0;
            try {
                var cs = getComputedStyle(ringEl);
                var token = cs.getPropertyValue('--mf-rays-size').trim();
                if (token) size = parseFloat(token);
                if (!size) size = ringEl.getBoundingClientRect().width;
            } catch (e) { /* non-DOM / detached — fall through to defaults */ }
            if (size && size > 0) {
                if (opts.min == null) min = Math.max(2, size * 0.025);
                if (opts.max == null) max = size * 0.24;
            }
        }
        if (min == null) min = DEFAULTS.min;
        if (max == null) max = DEFAULTS.max;
        if (max <= min) max = min + 1; // guard against a flat ring
        return { min: min, max: max };
    }

    /* ---------------------------------------------------------------------------
       build(ringEl, count)
       Fill ringEl with `count` ray spans, set --mf-ray-count, and disable each
       span's CSS animation so THIS module owns the height (not the keyframe).
       Re-builds only when the child count differs, so re-calling is cheap.
       Returns the array of span elements.
       ------------------------------------------------------------------------- */
    function build(ringEl, count) {
        if (!ringEl) return [];
        var n = count || DEFAULTS.count;
        var spans = ringEl.children;

        if (spans.length !== n) {
            // Build off-DOM, then swap in one shot (one reflow, not n).
            var frag = document.createDocumentFragment();
            for (var i = 0; i < n; i++) {
                var span = document.createElement('span');
                span.style.setProperty('--i', i);
                span.style.animation = 'none'; // JS drives height from here on
                frag.appendChild(span);
            }
            ringEl.textContent = '';
            ringEl.appendChild(frag);
        } else {
            // Reuse existing spans — just make sure JS owns them.
            for (var j = 0; j < spans.length; j++) {
                spans[j].style.setProperty('--i', j);
                spans[j].style.animation = 'none';
            }
        }

        ringEl.style.setProperty('--mf-ray-count', n);
        return Array.prototype.slice.call(ringEl.children);
    }

    /* ---------------------------------------------------------------------------
       Per-mode target generator. Given (i, n, phase, lobes) returns a 0..1
       "loudness" for ray i this frame. Smoothing + height mapping happen in the
       loop, not here.
       ------------------------------------------------------------------------- */
    function targetFor(mode, i, n, phase, lobes) {
        var t = i / n;
        switch (mode) {
            case 'wave':
                // Clean travelling wave — the voice formula with the noise removed.
                return clamp01(Math.sin(t * Math.PI * lobes + phase) * 0.3 + 0.25);

            case 'pulse':
                // All rays breathe together off one shared value (no i term).
                return clamp01(Math.sin(phase) * 0.4 + 0.5);

            case 'comet':
                // A single sharp crest sweeping around the ring.
                return clamp01(Math.pow(Math.max(0, Math.sin(t * Math.PI * 2 + phase)), 6));

            case 'voice':
            default:
                // The real interviewer: travelling 4-lobe sine + per-frame noise.
                var wave = Math.sin(t * Math.PI * lobes + phase) * 0.3 + 0.25;
                var noise = Math.random() * 0.15;
                return clamp01(wave + noise);
        }
    }

    /* ---------------------------------------------------------------------------
       animate(ringEl, opts)
       Build if empty, then run a rAF loop setting each span's height every frame.
       opts: { mode, count, min, max, phaseStep, lobes, smooth }
       Returns a handle { stop() }. Honors reduced-motion by painting a single
       pleasant static mid-height instead of looping.
       ------------------------------------------------------------------------- */
    function animate(ringEl, opts) {
        opts = opts || {};
        var mode = opts.mode || DEFAULTS.mode;
        var count = opts.count || DEFAULTS.count;
        var phaseStep = opts.phaseStep != null ? opts.phaseStep : DEFAULTS.phaseStep;
        var lobes = opts.lobes != null ? opts.lobes : DEFAULTS.lobes;
        var smooth = opts.smooth != null ? opts.smooth : DEFAULTS.smooth;

        var spans = build(ringEl, count);
        var n = spans.length;
        var hr = resolveHeights(ringEl, opts);
        var min = hr.min, max = hr.max, span = max - min;

        if (!n) return { stop: function () {} };

        // Reduced motion: skip the loop, settle to a calm even mid-height.
        if (prefersReducedMotion()) {
            var rest = min + span * 0.5;
            for (var k = 0; k < n; k++) spans[k].style.height = rest + 'px';
            return { stop: function () {} };
        }

        // Per-ring smoothing buffer, primed at the resting level.
        var h = new Array(n);
        for (var p = 0; p < n; p++) h[p] = 0;

        var phase = 0;
        var rafId = null;
        var running = true;
        var newWeight = 1 - smooth;

        function frame() {
            if (!running) return;
            for (var i = 0; i < n; i++) {
                var target = targetFor(mode, i, n, phase, lobes);
                // h[i] = h[i]*smooth + target*(1-smooth)  — matches the live 0.4/0.6.
                h[i] = h[i] * smooth + target * newWeight;
                spans[i].style.height = (min + h[i] * span) + 'px';
            }
            phase += phaseStep;
            rafId = window.requestAnimationFrame(frame);
        }
        rafId = window.requestAnimationFrame(frame);

        return {
            stop: function () {
                running = false;
                if (rafId != null) window.cancelAnimationFrame(rafId);
                rafId = null;
            }
        };
    }

    /* ---------------------------------------------------------------------------
       intro(orbEl, opts)
       Choreograph the combined motif (~2.2s), then settle into animate(mode).
       orbEl must contain:
         .mf-orb2__rings  — 3 concentric circle spans (provided CSS in the page)
         .mf-rays         — the ray ring (this module fills + drives it)
         .mf-eyes         — two <i> eyes (kit class)
       Sequence (driven by CSS classes the page defines + JS timing):
         1) rings EXPAND then SNAP-COMPACT to tiny           ~0.9s
         2) eyes POP out                                     ~0.4s
         3) rays BLOOM in + animate() starts                 ~0.5s
         4) rings fade out
       Reduced motion: skip choreography — show rays (static) + eyes immediately.
       Returns a handle { stop() } that also halts the underlying animate loop.
       ------------------------------------------------------------------------- */
    function intro(orbEl, opts) {
        opts = opts || {};
        var mode = opts.mode || DEFAULTS.mode;
        var count = opts.count || DEFAULTS.count;

        var ringsEl = orbEl.querySelector('.mf-orb2__rings');
        var raysEl = orbEl.querySelector('.mf-rays');
        var eyesEl = orbEl.querySelector('.mf-eyes');

        // Reset any prior run's classes/state so Replay starts clean.
        if (ringsEl) ringsEl.classList.remove('is-expand', 'is-compact', 'is-fade');
        if (eyesEl) eyesEl.classList.remove('is-pop');
        if (raysEl) raysEl.classList.remove('is-bloom');

        var handle = { stop: function () {} };
        var timers = [];
        function later(fn, ms) { timers.push(window.setTimeout(fn, ms)); }

        function startRays() {
            if (!raysEl) return;
            raysEl.classList.add('is-bloom');
            handle = animate(raysEl, { mode: mode, count: count, min: opts.min, max: opts.max });
        }

        // Reduced motion: no choreography — just present the settled state.
        if (prefersReducedMotion()) {
            if (eyesEl) eyesEl.classList.add('is-pop');
            if (ringsEl) ringsEl.classList.add('is-fade');
            startRays(); // animate() itself paints a static mid-height under RM
            return {
                stop: function () {
                    timers.forEach(clearTimeout);
                    handle.stop();
                }
            };
        }

        // 1) Rings expand, then snap compact.
        if (ringsEl) {
            ringsEl.classList.add('is-expand');
            later(function () {
                ringsEl.classList.remove('is-expand');
                ringsEl.classList.add('is-compact');
            }, 550);
        }

        // 2) Eyes pop after the rings have snapped in.
        later(function () { if (eyesEl) eyesEl.classList.add('is-pop'); }, 900);

        // 3) Rays bloom in and the loop starts.
        later(startRays, 1300);

        // 4) Concentric rings fade out under the blooming rays.
        later(function () { if (ringsEl) ringsEl.classList.add('is-fade'); }, 1700);

        return {
            stop: function () {
                timers.forEach(clearTimeout);
                handle.stop();
            }
        };
    }

    window.MFRays = { build: build, animate: animate, intro: intro };
})();
