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
     mountToggle(orbEl, opts)     wire a click GREET <-> ORB toggle on a composite

   Modes: voice, wave, pulse, comet, and the ADDITIVE combos voice+pulse /
   voice+comet (per-ray target = voice target SUM the other mode's, clamped) —
   these read visibly taller because the two contributions stack.

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
        speed: 1.2, // global tempo multiplier applied to every mode (~1.2x faster)
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
       Per-mode RAW target. Given (mode, i, n, phase, lobes) returns the
       un-clamped 0..~1 contribution for ray i this frame. Kept un-clamped so
       additive combos can SUM two contributions before a single final clamp.
       ------------------------------------------------------------------------- */
    function rawTarget(mode, i, n, phase, lobes) {
        var t = i / n;
        switch (mode) {
            case 'wave':
                // Clean travelling wave — the voice formula with the noise removed.
                return Math.sin(t * Math.PI * lobes + phase) * 0.3 + 0.25;

            case 'pulse':
                // All rays breathe together off one shared value (no i term).
                return Math.sin(phase) * 0.4 + 0.5;

            case 'comet':
                // A single sharp crest sweeping around the ring.
                return Math.pow(Math.max(0, Math.sin(t * Math.PI * 2 + phase)), 6);

            case 'voice':
            default:
                // The real interviewer: travelling 4-lobe sine + per-frame noise.
                return Math.sin(t * Math.PI * lobes + phase) * 0.3 + 0.25 +
                    Math.random() * 0.15;
        }
    }

    /* ---------------------------------------------------------------------------
       targetFor(mode, ...) returns the FINAL clamped 0..1 loudness for ray i.
       For the additive combos 'voice+pulse' / 'voice+comet' the bar length is
       the SUM of the voice target plus the partner mode's, then clamped to 1.0
       so stacks read taller without blowing out. Smoothing + px mapping happen
       in the loop, not here.
       ------------------------------------------------------------------------- */
    function targetFor(mode, i, n, phase, lobes) {
        if (mode === 'voice+pulse' || mode === 'voice+comet') {
            var other = mode === 'voice+pulse' ? 'pulse' : 'comet';
            return clamp01(
                rawTarget('voice', i, n, phase, lobes) +
                rawTarget(other, i, n, phase, lobes)
            );
        }
        return clamp01(rawTarget(mode, i, n, phase, lobes));
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
        var lobes = opts.lobes != null ? opts.lobes : DEFAULTS.lobes;
        var smooth = opts.smooth != null ? opts.smooth : DEFAULTS.smooth;
        // ~1.2x faster overall: base phase step × a global speed multiplier.
        var speed = opts.speed != null ? opts.speed : DEFAULTS.speed;
        var baseStep = opts.phaseStep != null ? opts.phaseStep : DEFAULTS.phaseStep;
        var phaseStep = baseStep * speed;

        var isCombo = (mode === 'voice+pulse' || mode === 'voice+comet');

        var spans = build(ringEl, count);
        var n = spans.length;
        var hr = resolveHeights(ringEl, opts);
        var min = hr.min, max = hr.max;
        // Combos stack two contributions — give the px ceiling ~10% more room so
        // a full stack reads taller than any single mode.
        if (isCombo) max = min + (max - min) * 1.1;
        var span = max - min;

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

    /* ---------------------------------------------------------------------------
       mountToggle(orbEl, opts)
       Wire a symmetric GREET <-> ORB click toggle on a .mf-orb2 composite:
         .mf-orb2__rings  — 3 concentric brand-green rings (resting state)
         .mf-rays         — the ray ring (this module fills + drives it)
         .mf-eyes         — two <i> eyes
       Starts in the CIRCLES state (rings at natural size; rays + eyes hidden).

       ENTRY (circles -> orb) on click:
         1) rings EXPAND (scale 1 -> 1.5)
         2) rings CONTRACT to centre and VANISH (scale -> 0, fade out)
         3) eyes POP out (scale 0 -> 1.2 -> 1)
         4) ~0.5s later rays BLOOM in and animate(mode) starts
       EXIT (orb -> circles) on the next click — the symmetric reverse:
         1) rays fade/scale out and the animator stops
         2) eyes SHUT (scaleY -> 0) and vanish
         3) rings GROW from centre (scale 0 -> 1.5 overshoot) then settle (-> 1),
            fading in
       Clicks mid-transition are ignored until the current one finishes.
       Reduced motion: no choreography — instantly swap circles <-> rays+eyes.
       Returns a handle { stop(), toggle(), open() } — open() reports the state.
       ------------------------------------------------------------------------- */
    function mountToggle(orbEl, opts) {
        opts = opts || {};
        var mode = opts.mode || orbEl.getAttribute('data-mode') || DEFAULTS.mode;
        var count = opts.count || DEFAULTS.count;

        var ringsEl = orbEl.querySelector('.mf-orb2__rings');
        var raysEl = orbEl.querySelector('.mf-rays');
        var eyesEl = orbEl.querySelector('.mf-eyes');

        // Entry/exit timings (ms). Each direction lands ~2.0–2.4s total.
        var T = {
            ringExpand: 600,   // 1) rings grow outward
            ringVanish: 600,   // 2) rings contract to centre + fade
            // 3) eyes pop (0.48s, CSS-driven) overlaps the rays delay below
            raysDelay: 500,    // 4) gap before rays bloom (after eyes pop starts)
            raysBloom: 520,    // rays scale/opacity in
            raysOut: 460,      // exit: rays fade/scale out
            eyesShut: 380,     // exit: eyes scaleY -> 0
            ringsReturn: 760   // exit: rings grow from centre + overshoot to rest
        };

        var animHandle = { stop: function () {} };
        var timers = [];
        var busy = false;       // true while a transition is mid-flight
        var isOpen = false;     // false = circles, true = orb (rays + eyes)

        function later(fn, ms) { timers.push(window.setTimeout(fn, ms)); }
        function clearTimers() { timers.forEach(clearTimeout); timers = []; }

        function resetClasses() {
            if (ringsEl) ringsEl.classList.remove(
                'is-expand', 'is-vanish', 'is-return', 'is-hidden');
            if (eyesEl) eyesEl.classList.remove('is-pop', 'is-shut');
            if (raysEl) raysEl.classList.remove('is-bloom', 'is-out');
        }

        function stopRays() {
            if (animHandle && animHandle.stop) animHandle.stop();
            animHandle = { stop: function () {} };
        }

        // --- Reduced motion: instant swap, no choreography. -------------------
        function swapInstant(open) {
            clearTimers();
            resetClasses();
            stopRays();
            if (open) {
                if (ringsEl) ringsEl.classList.add('is-hidden');
                if (eyesEl) eyesEl.classList.add('is-pop');   // CSS shows settled
                if (raysEl) {
                    raysEl.classList.add('is-bloom');          // CSS shows settled
                    animHandle = animate(raysEl, { mode: mode, count: count, min: opts.min, max: opts.max });
                }
            }
            isOpen = open;
            busy = false;
        }

        // --- ENTRY: circles -> orb -------------------------------------------
        function enter() {
            busy = true;
            resetClasses();
            stopRays();

            // 1) rings expand outward
            if (ringsEl) ringsEl.classList.add('is-expand');

            // 2) rings contract to centre + vanish
            later(function () {
                if (ringsEl) {
                    ringsEl.classList.remove('is-expand');
                    ringsEl.classList.add('is-vanish');
                }
            }, T.ringExpand);

            // 3) eyes pop (after the rings have collapsed)
            var eyesAt = T.ringExpand + T.ringVanish;
            later(function () {
                if (ringsEl) {
                    ringsEl.classList.remove('is-vanish');
                    ringsEl.classList.add('is-hidden'); // park hidden at centre
                }
                if (eyesEl) eyesEl.classList.add('is-pop');
            }, eyesAt);

            // 4) ~0.5s after eyes, rays bloom + the loop starts
            var raysAt = eyesAt + T.raysDelay;
            later(function () {
                if (raysEl) {
                    raysEl.classList.add('is-bloom');
                    animHandle = animate(raysEl, { mode: mode, count: count, min: opts.min, max: opts.max });
                }
            }, raysAt);

            later(function () { busy = false; isOpen = true; }, raysAt + T.raysBloom);
        }

        // --- EXIT: orb -> circles (symmetric reverse) ------------------------
        function exit() {
            busy = true;

            // 1) rays fade/scale out, animator stops
            if (raysEl) {
                raysEl.classList.remove('is-bloom');
                raysEl.classList.add('is-out');
            }
            later(stopRays, T.raysOut);

            // 2) eyes shut (scaleY -> 0) and vanish
            later(function () {
                if (eyesEl) {
                    eyesEl.classList.remove('is-pop');
                    eyesEl.classList.add('is-shut');
                }
            }, T.raysOut);

            // 3) rings grow from centre (overshoot to 1.5) then settle to rest
            var ringsAt = T.raysOut + T.eyesShut;
            later(function () {
                if (eyesEl) eyesEl.classList.remove('is-shut');
                if (raysEl) raysEl.classList.remove('is-out');
                if (ringsEl) {
                    ringsEl.classList.remove('is-hidden');
                    ringsEl.classList.add('is-return');
                }
            }, ringsAt);

            // settle: drop the return class so rings rest at their natural size
            later(function () {
                if (ringsEl) ringsEl.classList.remove('is-return');
                busy = false;
                isOpen = false;
            }, ringsAt + T.ringsReturn);
        }

        function toggle() {
            if (prefersReducedMotion()) { swapInstant(!isOpen); return; }
            if (busy) return;            // guard: ignore clicks mid-animation
            if (isOpen) exit(); else enter();
        }

        // Start cleanly in the circles state.
        clearTimers();
        resetClasses();
        if (prefersReducedMotion() && ringsEl) {
            // ensure resting circles are visible (CSS default already does this)
        }

        orbEl.addEventListener('click', toggle);
        orbEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
        });

        return {
            toggle: toggle,
            open: function () { return isOpen; },
            stop: function () { clearTimers(); stopRays(); }
        };
    }

    window.MFRays = { build: build, animate: animate, intro: intro, mountToggle: mountToggle };
})();
