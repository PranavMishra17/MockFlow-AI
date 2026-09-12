/**
 * Live caption state for LiveKit `lk.transcription` text streams.
 *
 * The agents SDK publishes transcriptions as text streams on the topic
 * `lk.transcription`, one stream per utterance segment, identified by the
 * `lk.segment_id` attribute. Two framings arrive on that topic:
 *
 *   - The agent's own speech is a DELTA stream: one stream stays open for the
 *     whole reply and each chunk is the next word(s), paced to the audio.
 *   - The candidate's STT is a REPLACE stream: every interim result opens a new
 *     stream carrying the FULL text so far, with the same segment id; the final
 *     result is one more such stream tagged `lk.transcription_final=true`.
 *
 * `CaptionTrack` reduces both to one rule: opening a stream resets that
 * segment's text, chunks append. A new segment id replaces the caption.
 *
 * No DOM here so it can be unit-tested under node (tests/test_captions_js.py).
 */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.CaptionTrack = factory();
    }
}(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    function CaptionTrack() {
        this.segmentId = null;
        this.text = '';
        this.final = false;
        // True once any stream text has landed for this speaker. From then on
        // the streams are authoritative and the agent's end-of-turn data
        // packets for this speaker should be ignored.
        this.live = false;
    }

    /** A stream opened for `segmentId`. Resets the text for that segment. */
    CaptionTrack.prototype.open = function (segmentId) {
        this.segmentId = segmentId;
        this.text = '';
        this.final = false;
    };

    /** A chunk arrived. Ignored if it belongs to a segment we've moved past. */
    CaptionTrack.prototype.append = function (segmentId, chunk) {
        if (segmentId !== this.segmentId) return false;
        this.text += chunk;
        this.live = true;
        return true;
    };

    /** The stream closed. `final` is the `lk.transcription_final` attribute. */
    CaptionTrack.prototype.close = function (segmentId, final) {
        if (segmentId !== this.segmentId) return;
        this.final = !!final;
    };

    /** Display text: collapsed whitespace, trimmed. */
    CaptionTrack.prototype.caption = function () {
        return this.text.replace(/\s+/g, ' ').trim();
    };

    return CaptionTrack;
}));
