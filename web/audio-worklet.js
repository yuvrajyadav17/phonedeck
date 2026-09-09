/* Playback for the PC audio stream, on the audio render thread.

   This exists because the obvious approach does not work. A
   ScriptProcessorNode runs its callback on the main thread, so it competes
   with the dashboard's own rendering; on this phone the main thread stalls
   for up to 54 ms at a time, and every stall longer than the callback period
   is an audible dropout. An AudioWorkletProcessor runs on the dedicated audio
   thread instead and is unaffected by anything the page does.

   (Chromium 71 does have AudioWorklet -- it shipped in Chrome 66. The earlier
   assumption that it did not was what cost the stream its continuity.)

   Two other things have to be right for sound to stay unbroken for hours:

   * **A cushion the device chooses.** Audio arrives in 43 ms frames, and the
     phone's main thread -- which is where a WebSocket message is delivered,
     whatever thread ends up playing it -- stalls for tens of milliseconds at
     a time. Too small a buffer and every stall is a hole; too large and the
     sound lags the screen. So the buffer is not a fixed number: it grows
     whenever it runs dry and shrinks slowly while it does not, settling
     wherever this particular phone needs it. A faster phone ends up with
     less delay without anyone having to choose a number for it.
   * **Correcting for clock drift.** The PC samples at "48000" and the phone
     plays at "48000", but the two crystals differ by tens of parts per
     million -- seconds of accumulated error per hour. Left alone the buffer
     creeps to full or empty and eventually breaks. Playback speed is nudged
     by at most 0.5% -- eight cents, well below what anyone can hear -- to
     hold the buffer where it should be.
*/

var FLOOR_MS = 120;    // never aim for less cushion than this
var START_MS = 200;    // where a fresh stream begins
var CAP_MS = 700;      // never aim for more; past here it is only lag
var BUMP_MS = 60;      // added to the target each time we run dry
var DECAY_MS = 4;      // given back per quiet second
var DRIFT_GAIN = 0.05; // proportional term for the buffer controller
var MAX_DRIFT = 0.005; // never bend the clock by more than this

class DeckPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ready = false;
    this.port.onmessage = (event) => {
      var msg = event.data;
      if (msg && msg.config) this.configure(msg.config);
      else if (msg && msg.byteLength !== undefined) this.push(new Int16Array(msg));
    };
  }

  configure(cfg) {
    this.channels = cfg.channels || 2;
    this.srcRate = cfg.rate || 48000;
    this.capFrames = Math.ceil(this.srcRate * 3);          // three seconds
    this.ring = new Float32Array(this.capFrames * this.channels);

    var perMs = this.srcRate / 1000;
    this.floor = FLOOR_MS * perMs;
    this.roof = CAP_MS * perMs;
    this.bump = BUMP_MS * perMs;
    this.decay = DECAY_MS * perMs;
    this.target = START_MS * perMs;

    // Frames are counted from the start of the stream rather than tracked as
    // wrapping indices; the difference is the fill level, with no wraparound
    // bookkeeping to get wrong. A double counts frames exactly for millennia.
    this.written = 0;
    this.read = 0;
    this.armed = false;
    this.base = this.srcRate / sampleRate;
    this.underruns = 0;
    this.hadUnderrun = false;
    this.peak = 0;
    this.quanta = 0;
    this.ready = true;
  }

  push(pcm) {
    if (!this.ready) return;
    var ch = this.channels;
    var cap = this.capFrames;
    var frames = (pcm.length / ch) | 0;

    // No room: drop the oldest by moving the read pointer forward. Only
    // happens if the page was backgrounded or the cable stalled, and a seam
    // beats half a second of permanent lag.
    if (frames > cap - (this.written - this.read) - 1) {
      this.read = this.written + frames - cap + 1;
      this.armed = false;
    }

    var w = this.written % cap;
    for (var i = 0; i < frames; i++) {
      var dst = ((w + i) % cap) * ch;
      var src = i * ch;
      for (var c = 0; c < ch; c++) this.ring[dst + c] = pcm[src + c] / 32768;
    }
    this.written += frames;
  }

  process(inputs, outputs) {
    var out = outputs[0];
    var n = out[0].length;
    var c;
    if (!this.ready) {
      for (c = 0; c < out.length; c++) out[c].fill(0);
      return true;
    }

    // Give a little cushion back for every quiet second, so one bad moment
    // does not leave the stream lagging for the rest of the session.
    this.quanta++;
    if (this.quanta % Math.round(sampleRate / n) === 0) {
      if (!this.hadUnderrun && this.target > this.floor) {
        this.target = Math.max(this.floor, this.target - this.decay);
      }
      this.hadUnderrun = false;
      this.port.postMessage({ stats: {
        fillMs: Math.round((this.written - this.read) / this.srcRate * 1000),
        targetMs: Math.round(this.target / this.srcRate * 1000),
        underruns: this.underruns,
        // Loudest sample of the last second: the difference between "the
        // buffer is healthy" and "sound is actually coming out".
        peak: Math.round(this.peak * 100) / 100,
        seconds: Math.round(this.quanta * n / sampleRate),
      } });
      this.peak = 0;
    }

    var fill = this.written - this.read;
    if (!this.armed) {
      // Wait for the whole cushion before starting again. Resuming from a
      // nearly empty buffer only guarantees the next dropout.
      if (fill < this.target) {
        for (c = 0; c < out.length; c++) out[c].fill(0);
        return true;
      }
      this.armed = true;
    }
    if (fill > this.target + this.roof) {
      this.read = this.written - this.target;
      fill = this.target;
    }

    // Hold the cushion at its target by playing imperceptibly fast or slow.
    var error = (fill - this.target) / this.target;
    var rate = this.base * (1 + Math.max(-MAX_DRIFT,
                              Math.min(MAX_DRIFT, error * DRIFT_GAIN)));

    var cap = this.capFrames;
    var ch = this.channels;
    var mono = out.length === 1 && ch === 2;
    for (var i = 0; i < n; i++) {
      if (this.written - this.read < 2) {
        // Ran dry. Go quiet for the rest of this block rather than stuttering
        // sample by sample, and ask for more cushion next time round.
        this.armed = false;
        this.underruns++;
        this.hadUnderrun = true;
        this.target = Math.min(this.roof, this.target + this.bump);
        for (c = 0; c < out.length; c++) out[c].fill(0, i);
        return true;
      }
      var i0 = Math.floor(this.read);
      var frac = this.read - i0;
      var a = (i0 % cap) * ch;
      var b = ((i0 + 1) % cap) * ch;
      if (mono) {
        // A mono output: mix the pair rather than dropping the right channel.
        var l = this.ring[a] * (1 - frac) + this.ring[b] * frac;
        var r = this.ring[a + 1] * (1 - frac) + this.ring[b + 1] * frac;
        out[0][i] = (l + r) * 0.5;
      } else {
        for (c = 0; c < out.length; c++) {
          var s = c < ch ? c : ch - 1;    // mono source into a stereo output
          out[c][i] = this.ring[a + s] * (1 - frac) + this.ring[b + s] * frac;
        }
      }
      var v = out[0][i];
      if (v > this.peak) this.peak = v;
      this.read += rate;
    }
    return true;
  }
}

registerProcessor("deck-player", DeckPlayer);
