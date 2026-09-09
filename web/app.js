/* PhoneDeck dashboard.
 *
 * Three panes plus a shortcut drawer. The arrangement (three columns in
 * landscape, one stack in portrait) is entirely CSS -- this file never
 * measures the window or branches on orientation.
 *
 * Written in ES5 on purpose: the target device's WebView is Chromium 71.
 * No arrow functions, no template literals, no const/let.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  // How many quick-launch slots the top bar holds. Kept in step with the
  // editor's own count in editor.js.
  var SLOT_COUNT = 4;

  // ------------------------------------------------------------- token --
  // Arrives once as ?t=... (from the app shell or the desktop link) and is
  // remembered, so a reload never needs re-pairing.
  var token = new URLSearchParams(location.search).get("t");
  if (token) {
    try { localStorage.setItem("pd_token", token); } catch (e) { /* private mode */ }
    history.replaceState(null, "", location.pathname);
  } else {
    try { token = localStorage.getItem("pd_token") || ""; } catch (e) { token = ""; }
  }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign({ "X-PhoneDeck-Token": token },
                                    options.headers || {});
    return fetch(path, options).then(function (res) {
      return res.json()
        .catch(function () { return { ok: false, error: "bad response" }; })
        .then(function (body) {
          if (res.status === 401) {
            throw new Error("unauthorised - open once with ?t=TOKEN");
          }
          return body;
        });
    });
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var toastTimer = null;
  function toast(message, kind) {
    var el = $("toast");
    el.textContent = message;
    el.className = "toast " + (kind || "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 2600);
  }

  // ======================================================= dashboard =====
  var pollMs = 1000;
  var failures = 0;
  var metric = "cpu";      // which tab the process pane is showing
  var driveIndex = 0;      // which drive the centre column is paging on
  var lastStats = null;

  function setLink(state, text) {
    $("linkDot").className = "dot " + state;
    $("linkText").textContent = text;
  }

  // ------------------------------------------------------------- cores --
  function renderCores(list) {
    var box = $("cores");
    if (box.children.length !== list.length) {
      box.innerHTML = "";
      for (var n = 0; n < list.length; n++) {
        box.appendChild(document.createElement("i"));
      }
    }
    for (var i = 0; i < list.length; i++) {
      var pct = Math.max(2, Math.min(100, list[i]));
      box.children[i].style.height = pct + "%";
      box.children[i].style.opacity = 0.35 + (pct / 100) * 0.65;
    }
  }

  // ------------------------------------------------------------ drives --
  function renderDrive(disks, io) {
    if (!disks || !disks.length) {
      $("driveName").textContent = "no drives";
      return;
    }
    if (driveIndex >= disks.length) driveIndex = 0;
    if (driveIndex < 0) driveIndex = disks.length - 1;

    var d = disks[driveIndex];
    $("driveName").textContent = d.device;
    $("driveFree").textContent = d.free_h + " free";
    $("driveText").textContent = d.used_h + " / " + d.total_h;

    var bar = $("driveBar");
    bar.style.width = d.percent + "%";
    bar.className = d.percent >= 90 ? "bad" : d.percent >= 75 ? "warn" : "";

    // Page indicators, rebuilt only when the drive count changes.
    var dots = $("driveDots");
    if (dots.children.length !== disks.length) {
      dots.innerHTML = "";
      for (var i = 0; i < disks.length; i++) {
        var dot = document.createElement("i");
        (function (index) {
          dot.onclick = function () {
            driveIndex = index;
            if (lastStats) renderDrive(lastStats.disks, lastStats.disk_io);
          };
        })(i);
        dots.appendChild(dot);
      }
    }
    for (var k = 0; k < dots.children.length; k++) {
      dots.children[k].className = k === driveIndex ? "on" : "";
    }
  }

  /* Swipe the disk card left or right to page through C:, D:, E: ... */
  (function bindDriveSwipe() {
    var card = $("diskCard");
    var startX = 0, startY = 0, tracking = false;

    card.addEventListener("touchstart", function (e) {
      // Keep this gesture to the drives: without it a swipe here would also
      // flip the dashboard page underneath.
      e.stopPropagation();
      if (e.touches.length !== 1) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      tracking = true;
    }, { passive: true });

    card.addEventListener("touchend", function (e) {
      e.stopPropagation();
      if (!tracking) return;
      tracking = false;
      var touch = e.changedTouches[0];
      var dx = touch.clientX - startX;
      var dy = touch.clientY - startY;
      // Horizontal intent only; a vertical drag is a scroll, not a page turn.
      if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy)) return;
      driveIndex += (dx < 0 ? 1 : -1);
      if (lastStats) renderDrive(lastStats.disks, lastStats.disk_io);
    }, { passive: true });
  })();

  // --------------------------------------------------------- processes --
  function renderProcs(processes) {
    var list = (metric === "mem" ? processes.by_mem : processes.by_cpu) || [];
    var html = "";
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      // Both columns are shown; the one being sorted on is the bright one.
      var cpuCls = metric === "cpu" ? "val strong" : "val";
      var memCls = metric === "mem" ? "val strong" : "val";
      html += '<div class="proc" data-pid="' + p.pid + '">'
            +   '<div class="name">' + esc(p.name) + "</div>"
            +   '<div class="' + cpuCls + '">' + p.cpu.toFixed(1) + "%</div>"
            +   '<div class="' + memCls + '">' + esc(p.mem_h) + "</div>"
            + "</div>";
    }
    $("procs").innerHTML = html;
  }

  (function bindProcTabs() {
    var buttons = $("procTabs").getElementsByTagName("button");
    for (var i = 0; i < buttons.length; i++) {
      (function (btn) {
        btn.onclick = function () {
          metric = btn.getAttribute("data-metric");
          for (var k = 0; k < buttons.length; k++) {
            buttons[k].className = "seg-btn" +
              (buttons[k] === btn ? " active" : "");
          }
          $("procs").scrollTop = 0;
          if (lastStats && lastStats.processes) renderProcs(lastStats.processes);
        };
      })(buttons[i]);
    }
  })();

  /* Hold a row to end that process. */
  (function bindProcessHold() {
    var holdTimer = null;

    function begin(event) {
      var row = event.target.closest(".proc");
      if (!row) return;
      holdTimer = setTimeout(function () {
        var pid = row.getAttribute("data-pid");
        var name = row.querySelector(".name").textContent;
        if (!confirm("End " + name + " (pid " + pid + ")?")) return;
        row.classList.add("killing");
        api("/api/process/" + pid + "/kill", { method: "POST" })
          .then(function (body) {
            toast(body.ok ? body.message : body.error, body.ok ? "ok" : "bad");
          })
          .catch(function (e) { toast(e.message, "bad"); });
      }, 550);
    }
    function cancel() { clearTimeout(holdTimer); }

    var procs = $("procs");
    procs.addEventListener("touchstart", begin, { passive: true });
    procs.addEventListener("mousedown", begin);
    ["touchend", "touchmove", "touchcancel", "mouseup", "mouseleave"]
      .forEach(function (evt) { procs.addEventListener(evt, cancel, { passive: true }); });
  })();

  /* The Claude light. Which sessions exist comes from Claude's own registry;
   * what each is doing comes from its hooks. No label is drawn beside it --
   * the colour and the one-word state say everything. */
  function applyClaude(c) {
    if (!c) return;

    $("claudeDot").style.background = c.colour;
    $("claudeDot").style.boxShadow = c.state === "offline"
      ? "none" : "0 0 7px " + c.colour;
    $("claudeState").textContent = c.label;
    $("claudeState").style.color = c.colour;

    var led = $("claudeLed");
    led.className = "temp t-claude" + (c.state === "running" ? " busy" : "");
    led.title = c.detail
      ? (c.label + " - " + c.detail)
      : ("Claude: " + c.label
         + (c.sessions ? " (" + c.sessions + " session"
            + (c.sessions === 1 ? "" : "s") + ")" : ""));

  }


  // ========================================================== paging =====
  /* Three pages exist, but only the first two are in the swipe rotation.
     Downloads is reachable solely from the top-bar chip, which itself only
     appears while something is actually downloading. */
  var page = 0;
  var cameFrom = 0;
  var PAGE_DOWNLOADS = 2;

  function setPage(n) {
    page = Math.max(0, Math.min(2, n));
    $("board").setAttribute("data-page", String(page));
    // Landscape slides; portrait swaps by display (see the stylesheet).
    $("pager").style.transform = "translateX(" + (page * -33.3333) + "%)";
    var dots = $("pageDots").children;
    for (var i = 0; i < dots.length; i++) {
      dots[i].className = i === page ? "on" : "";
    }
  }

  function swipePage(direction) {
    if (page === PAGE_DOWNLOADS) {
      setPage(cameFrom);            // any swipe leaves downloads
      return;
    }
    var next = page + direction;
    if (next < 0 || next > 1) return;
    setPage(next);
  }

  function openDownloads() {
    if (page !== PAGE_DOWNLOADS) cameFrom = page;
    setPage(PAGE_DOWNLOADS);
  }

  (function bindPageSwipe() {
    var board = $("board");
    var startX = 0, startY = 0, tracking = false;

    board.addEventListener("touchstart", function (e) {
      if (e.touches.length !== 1) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      tracking = true;
    }, { passive: true });

    board.addEventListener("touchend", function (e) {
      if (!tracking) return;
      tracking = false;
      var touch = e.changedTouches[0];
      var dx = touch.clientX - startX;
      var dy = touch.clientY - startY;
      if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy)) return;
      swipePage(dx < 0 ? 1 : -1);
    }, { passive: true });
  })();

  $("dlChip").onclick = openDownloads;

  // ============================================================ sound =====
  /* A short tone, generated rather than loaded, so there are no audio files to
     ship. Browsers keep an AudioContext suspended until the user has touched
     the page at least once, so the first tap unlocks it. */
  var audioCtx = null;
  var audioReady = false;

  function unlockAudio() {
    try {
      if (!audioCtx) {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        audioCtx = new Ctx();
      }
      if (audioCtx.state === "suspended") audioCtx.resume();
      audioReady = true;
    } catch (e) { /* no audio on this device */ }
  }
  document.addEventListener("touchstart", unlockAudio, { passive: true });
  document.addEventListener("click", unlockAudio);

  function tone(freq, ms, delay) {
    if (!audioReady || !audioCtx) return;
    setTimeout(function () {
      try {
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        // A short fade stops the click you get from cutting a tone dead.
        gain.gain.setValueAtTime(0.0001, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.18, audioCtx.currentTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001,
          audioCtx.currentTime + ms / 1000);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + ms / 1000 + 0.02);
      } catch (e) { /* ignore */ }
    }, delay || 0);
  }

  function chime(kind) {
    if (kind === "done")    { tone(880, 130); tone(1320, 160, 150); }
    else if (kind === "ask") { tone(660, 180); }
    else if (kind === "bad") { tone(320, 260); }
  }



  // ==================================================== voice input =====
  /* The phone's microphone as a dictation device: capture here, recognise on
     the PC, and the recognised words are typed into whatever window has focus
     over there. Nothing is sent anywhere but down the USB cable.

     Audio is resampled to the 16 kHz the recogniser expects before sending,
     which also cuts the bandwidth to a third. */
  var VOICE_RATE = 16000;
  var micWs = null, micStream = null, micNode = null, micSource = null;
  var heardEl = null;

  function showHeard(text) {
    if (!heardEl) {
      heardEl = document.createElement("div");
      heardEl.className = "heard";
      document.body.appendChild(heardEl);
    }
    heardEl.textContent = text || "listening…";
  }

  function hideHeard() {
    if (heardEl && heardEl.parentNode) heardEl.parentNode.removeChild(heardEl);
    heardEl = null;
  }

  function micStop() {
    if (micWs) {
      try { micWs.send("stop"); micWs.close(); } catch (e) {}
      micWs = null;
    }
    if (micNode) { try { micNode.disconnect(); } catch (e) {} micNode.onaudioprocess = null; micNode = null; }
    if (micSource) { try { micSource.disconnect(); } catch (e) {} micSource = null; }
    if (micStream) {
      micStream.getTracks().forEach(function (t) { t.stop(); });
      micStream = null;
    }
    $("micBtn").className = "mic";
    hideHeard();
  }

  function micStart() {
    unlockAudio();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      toast("This device cannot capture audio", "bad");
      return;
    }
    $("micBtn").className = "mic on";
    showHeard("");

    navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
    }).then(function (stream) {
      micStream = stream;
      var scheme = location.protocol === "https:" ? "wss:" : "ws:";
      micWs = new WebSocket(scheme + "//" + location.host
                            + "/ws/voice?t=" + encodeURIComponent(token));
      micWs.binaryType = "arraybuffer";

      micWs.onmessage = function (e) {
        var msg;
        try { msg = JSON.parse(e.data); } catch (err) { return; }
        if (msg.error) { toast(msg.error, "bad"); micStop(); return; }
        if (msg.final) { showHeard(msg.final); }
        else if (msg.partial) { showHeard(msg.partial); }
      };
      micWs.onerror = function () { toast("Voice link failed", "bad"); micStop(); };
      micWs.onclose = function () { if (micWs) micStop(); };

      micWs.onopen = function () {
        micSource = audioCtx.createMediaStreamSource(stream);
        micNode = audioCtx.createScriptProcessor(4096, 1, 1);
        var ratio = audioCtx.sampleRate / VOICE_RATE;

        micNode.onaudioprocess = function (ev) {
          if (!micWs || micWs.readyState !== 1) return;
          var input = ev.inputBuffer.getChannelData(0);
          var outLen = Math.floor(input.length / ratio);
          var pcm = new Int16Array(outLen);
          for (var i = 0; i < outLen; i++) {
            var s = input[Math.floor(i * ratio)];
            pcm[i] = Math.max(-32768, Math.min(32767, s * 32767));
          }
          try { micWs.send(pcm.buffer); } catch (e) {}
        };

        micSource.connect(micNode);
        // ScriptProcessor only runs while connected to the graph; a zeroed
        // gain node keeps it alive without playing the mic back at you.
        var mute = audioCtx.createGain();
        mute.gain.value = 0;
        micNode.connect(mute);
        mute.connect(audioCtx.destination);
      };
    }).catch(function (err) {
      toast("Microphone denied: " + err.name, "bad");
      micStop();
    });
  }

  $("micBtn").onclick = function () {
    if (micWs || micStream) micStop(); else micStart();
  };

  // ==================================================== audio listen =====
  /* Interleaved 16-bit PCM arrives over a WebSocket and is played by an
     AudioWorklet (see audio-worklet.js, which holds the jitter buffer and the
     drift correction).

     The work this file does is deliberately tiny: hand the raw ArrayBuffer
     straight to the worklet, transferring rather than copying it. Everything
     that has to happen on time happens on the audio thread, because this
     thread is busy drawing the dashboard and stalls for tens of milliseconds
     at a stretch. */
  var audioWs = null, audioNode = null, audioPending = null;

  function setSpeakerUi(state) {
    var btn = $("spkBtn");
    btn.className = "spk-btn" + (state === "on" ? " on"
                    : state === "connecting" ? " connecting" : "");
    $("spkText").textContent = state === "on" ? "listening"
                             : state === "connecting" ? "…" : "listen";
  }

  function audioStop() {
    if (audioWs) { var w = audioWs; audioWs = null; try { w.close(); } catch (e) {} }
    if (audioNode) {
      try { audioNode.disconnect(); } catch (e) {}
      audioNode = null;
    }
    audioPending = null;
    setSpeakerUi("off");
  }

  /* The worklet module is fetched once and kept; addModule is a network round
     trip and re-registering the processor on every tap would be wasteful. */
  var workletReady = null;
  function loadWorklet() {
    if (workletReady) return workletReady;
    if (!audioCtx.audioWorklet) return null;
    workletReady = audioCtx.audioWorklet.addModule("/audio-worklet.js");
    return workletReady;
  }

  function audioStart() {
    unlockAudio();
    if (!audioCtx) { toast("This device has no Web Audio", "bad"); return; }
    if (audioWs) return;

    setSpeakerUi("connecting");
    var scheme = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(scheme + "//" + location.host
                           + "/ws/audio?t=" + encodeURIComponent(token));
    ws.binaryType = "arraybuffer";
    audioWs = ws;
    audioPending = [];

    ws.onopen = function () { setSpeakerUi("on"); };
    ws.onerror = function () { toast("Audio stream failed", "bad"); audioStop(); };
    ws.onclose = function () { if (audioWs === ws) audioStop(); };

    ws.onmessage = function (e) {
      if (audioWs !== ws) return;
      if (typeof e.data === "string") {           // the format announcement
        var cfg;
        try { cfg = JSON.parse(e.data); } catch (err) { return; }
        startPlayer(ws, cfg);
        return;
      }
      if (!e.data || e.data.byteLength < 4) return;   // keep-alive ping
      if (audioNode) {
        audioNode.port.postMessage(e.data, [e.data]);
      } else if (audioPending && audioPending.length < 24) {
        audioPending.push(e.data);
      }
    };
  }

  function startPlayer(ws, cfg) {
    var ready = loadWorklet();
    if (!ready) { startFallbackPlayer(ws, cfg); return; }

    ready.then(function () {
      if (audioWs !== ws) return;                 // stopped while loading
      var node;
      try {
        node = new AudioWorkletNode(audioCtx, "deck-player",
                                    { outputChannelCount: [cfg.channels] });
      } catch (e) {
        node = new AudioWorkletNode(audioCtx, "deck-player");
      }
      node.port.onmessage = function (m) {
        if (m.data && m.data.stats) window.__audioStats = m.data.stats;
      };
      node.port.postMessage({ config: cfg });
      node.connect(audioCtx.destination);
      audioNode = node;
      if (audioPending) {
        for (var i = 0; i < audioPending.length; i++) {
          node.port.postMessage(audioPending[i], [audioPending[i]]);
        }
        audioPending = null;
      }
    }, function () {
      startFallbackPlayer(ws, cfg);
    });
  }

  /* Only for a WebView older than Chrome 66, which has no AudioWorklet at all.
     A ScriptProcessorNode runs on this thread and will glitch whenever the
     dashboard renders -- but glitching is better than silence. */
  function startFallbackPlayer(ws, cfg) {
    if (audioWs !== ws) return;
    var ch = cfg.channels, ratio = cfg.rate / audioCtx.sampleRate;
    var q = audioPending || [];
    audioPending = null;
    var buf = [], have = 0, pos = 0, on = false;
    var prebuffer = Math.round(cfg.rate * 0.18);

    function take(data) {
      var pcm = new Int16Array(data);
      buf.push(pcm); have += pcm.length / ch;
      while (have > cfg.rate && buf.length > 1) {
        have -= buf[0].length / ch; buf.shift(); pos = 0;
      }
      if (!on && have >= prebuffer) on = true;
    }
    for (var i = 0; i < q.length; i++) take(q[i]);

    var node = audioCtx.createScriptProcessor(4096, 1, ch);
    node.onaudioprocess = function (ev) {
      var outs = [], c;
      for (c = 0; c < ev.outputBuffer.numberOfChannels; c++) {
        outs.push(ev.outputBuffer.getChannelData(c));
      }
      for (var i = 0; i < outs[0].length; i++) {
        while (buf.length && Math.floor(pos) >= buf[0].length / ch) {
          pos -= buf[0].length / ch; have -= buf[0].length / ch; buf.shift();
        }
        if (!on || !buf.length) {
          for (c = 0; c < outs.length; c++) outs[c][i] = 0;
          if (!buf.length) on = false;
          continue;
        }
        var base = Math.floor(pos) * ch;
        for (c = 0; c < outs.length; c++) {
          outs[c][i] = buf[0][base + (c < ch ? c : ch - 1)] / 32768;
        }
        pos += ratio;
      }
    };
    node.connect(audioCtx.destination);
    // Route incoming frames here instead of to a worklet port.
    audioNode = { port: { postMessage: function (d) { take(d); } },
                  disconnect: function () {
                    try { node.disconnect(); } catch (e) {}
                    node.onaudioprocess = null;
                  } };
  }

  $("spkBtn").onclick = function () {
    if (audioWs) audioStop(); else audioStart();
  };

  // ============================================================ notes =====
  function renderNotes(items) {
    var box = $("notesList");
    items = items || [];
    if (!items.length) {
      box.innerHTML = '<div class="notes-empty">Nothing to do.<br>'
                    + "Tap <b>edit</b> to add something.</div>";
      return;
    }
    box.innerHTML = "";
    items.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "note";
      row.innerHTML = '<span class="tick"></span><span class="text"></span>';
      row.querySelector(".text").textContent = item.text;
      row.querySelector(".tick").onclick = function () {
        if (row.className.indexOf("doing") >= 0) return;
        row.className = "note doing";
        api("/api/notes/" + encodeURIComponent(item.id) + "/done",
            { method: "POST" })
          .then(function (r) {
            if (r.ok) { row.parentNode.removeChild(row); }
            else { row.className = "note"; toast(r.error || "failed", "bad"); }
          })
          .catch(function (e) { row.className = "note"; toast(e.message, "bad"); });
      };
      box.appendChild(row);
    });
  }

  $("notesEdit").onclick = function () {
    api("/api/notes/edit", { method: "POST" })
      .then(function (r) {
        toast(r.ok ? "Notes open on the PC" : (r.error || "failed"),
              r.ok ? "ok" : "bad");
      })
      .catch(function (e) { toast(e.message, "bad"); });
  };

  // ======================================================== downloads =====
  var lastFinishedAt = 0;

  function renderDownloads(d) {
    if (!d) return;
    var chip = $("dlChip");

    // The chip exists only while something is in flight.
    chip.hidden = d.count === 0;
    $("dlCount").textContent = d.count;
    $("dlRate").textContent = d.total_rate > 0 ? d.total_rate_h : "";

    $("dlSummary").textContent = d.count
      ? d.count + (d.count === 1 ? " file" : " files") + " · " + d.total_rate_h
      : "";

    var html = "";
    (d.items || []).forEach(function (item) {
      html += '<div class="dl' + (item.growing ? "" : " stalled") + '">'
            +   '<div class="dl-name">' + esc(item.name) + "</div>"
            +   '<div class="dl-size">' + esc(item.size_h) + "</div>"
            +   '<div class="dl-rate">' + (item.growing ? esc(item.rate_h) : "paused")
            +   "</div></div>";
    });
    $("dlList").innerHTML = html
      || '<div class="dl-empty">Nothing downloading.</div>';

    // Chime once when a transfer ends, and step off the page if it is empty.
    if (lastFinishedAt && d.finished_at > lastFinishedAt) {
      chime("done");
      toast("Download finished", "ok");
      if (page === PAGE_DOWNLOADS && d.count === 0) setPage(cameFrom);
    }
    lastFinishedAt = d.finished_at;
  }

  // =========================================================== clock =====
  /* Ticks from the phone's own clock rather than the server: it updates every
     second without a round trip, and the two devices sit on the same desk. */
  function tickClock() {
    var now = new Date();
    var h = now.getHours(), m = now.getMinutes();
    $("clockTime").textContent =
      (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
    $("clockDate").textContent = now.toLocaleDateString(undefined, {
      weekday: "short", day: "numeric", month: "short"
    });
    // Land the next tick just after the minute turns.
    setTimeout(tickClock, (60 - now.getSeconds()) * 1000 + 200);
  }

  // ========================================================= weather =====
  function renderWeather(w) {
    if (!w) { $("wxTemp").textContent = "--°"; $("wxLabel").textContent = "…"; return; }
    $("wxSymbol").textContent = w.symbol || "•";
    $("wxTemp").textContent = Math.round(w.temp) + "°";
    $("wxLabel").textContent = w.label || "";
    $("wxFeels").textContent = w.feels != null
      ? "feels " + Math.round(w.feels) + "°" : "";
    $("wxRange").textContent = (w.low != null && w.high != null)
      ? Math.round(w.low) + "° / " + Math.round(w.high) + "°" : "";
    $("wxRain").textContent = w.rain_chance != null
      ? w.rain_chance + "% rain" : "";
    $("wxPlace").textContent = w.place || "";
    $("wxWind").textContent = w.wind != null ? Math.round(w.wind) + " km/h" : "";
  }

  // ===================================================== now playing =====
  function renderNowPlaying(np) {
    var card = $("npCard");
    if (!np) {
      card.className = "card np quiet";
      $("npTitle").textContent = "nothing playing";
      $("npArtist").textContent = "";
      $("npSource").textContent = "";
      return;
    }
    card.className = "card np" + (np.playing ? "" : " quiet");
    $("npTitle").textContent = np.title || "—";
    $("npArtist").textContent = np.artist || "";
    $("npSource").textContent = np.source || "";
  }

  // ------------------------------------------------------------- apply --
  function applyStats(s) {
    lastStats = s;

    $("uptime").textContent = s.uptime.clock;

    // Temperatures. CPU package needs LibreHardwareMonitor running; until it
    // is, the dash shows a dash rather than a fake number.
    $("cpuTemp").textContent = s.temps && s.temps.cpu_c != null
      ? Math.round(s.temps.cpu_c) : "--";
    $("gpuTemp").textContent = s.temps && s.temps.gpu_c != null
      ? Math.round(s.temps.gpu_c) : "--";

    var cpu = Math.round(s.cpu.percent);
    $("cpuPct").textContent = cpu + "%";
    $("cpuBar").style.width = cpu + "%";
    renderCores(s.cpu.per_core || []);
    $("cpuName").textContent = s.cpu.name || "";
    $("cpuCores").textContent = (s.cpu.cores_physical || "?") + "C / "
                              + (s.cpu.cores_logical || "?") + "T";
    $("cpuFreq").textContent = s.cpu.freq_mhz ? (s.cpu.freq_mhz + " MHz") : "";

    var mem = Math.round(s.memory.percent);
    $("memPct").textContent = mem + "%";
    $("memBar").style.width = mem + "%";
    $("memText").textContent = s.memory.used_h + " / " + s.memory.total_h;
    $("swapText").textContent = s.memory.swap_total_h !== "0 B"
      ? "swap " + s.memory.swap_percent + "%" : "";

    if (s.gpu) {
      var load = s.gpu.load_percent;
      $("gpuPct").textContent = load != null ? Math.round(load) + "%" : "--";
      $("gpuBar").style.width = (load != null ? load : 0) + "%";
      $("gpuName").textContent = s.gpu.name || "";
      $("gpuVram").textContent = s.gpu.mem_used_mb != null
        ? Math.round(s.gpu.mem_used_mb) + " / " + Math.round(s.gpu.mem_total_mb) + " MB"
        : "";
      $("gpuPower").textContent = s.gpu.power_w != null
        ? s.gpu.power_w.toFixed(1) + " W" : "";
    } else {
      $("gpuPct").textContent = "--";
      $("gpuName").textContent = "no NVIDIA GPU detected";
      $("gpuVram").textContent = "";
      $("gpuPower").textContent = "";
    }

    applyClaude(s.claude);

    $("netDown").textContent = s.network.down_per_s_h;
    $("netUp").textContent = s.network.up_per_s_h;
    $("ioRead").textContent = s.disk_io.read_per_s_h;
    $("ioWrite").textContent = s.disk_io.write_per_s_h;

    renderDrive(s.disks, s.disk_io);
    renderWeather(s.weather);
    renderNowPlaying(s.now_playing);
    renderNotes(s.notes);
    renderDownloads(s.downloads);
    if (s.processes) renderProcs(s.processes);
  }

  function poll() {
    api("/api/stats")
      .then(function (body) {
        if (!body.ok) throw new Error(body.error || "stats failed");
        failures = 0;
        setLink("ok", "live");
        applyStats(body.stats);
      })
      .catch(function (err) {
        failures++;
        setLink(failures > 3 ? "bad" : "warn", failures > 3 ? "offline" : "retrying");
        if (failures === 1) toast(err.message, "bad");
      })
      .then(function () { setTimeout(poll, pollMs); });
  }

  // ========================================================== drawer =====
  var shortcuts = { groups: [] };
  var activeGroup = 0;

  function loadShortcuts() {
    return api("/api/shortcuts").then(function (body) {
      if (body.ok) {
        shortcuts = body.shortcuts || { groups: [] };
        renderDrawer();
        renderLaunchers();
      }
    }).catch(function () { /* the dashboard still works without them */ });
  }

  /* The three logo-only launchers in the top bar. Icons are the applications'
   * own, served by /api/icon; an app with no readable icon falls back to its
   * initial rather than showing a broken image. */
  function renderLaunchers() {
    var slots = shortcuts.topbar || [];
    var box = $("launch");
    box.innerHTML = "";

    // Always draw the full set, so an unassigned slot still shows its
    // placeholder rather than silently disappearing.
    for (var i = 0; i < SLOT_COUNT; i++) {
      var slot = slots[i];
      var el = document.createElement("button");

      if (!slot || !slot.action) {
        el.className = "slot empty";
        el.textContent = "+";
        el.title = "Empty slot - assign one in the editor";
        el.onclick = function () {
          toast("Assign this slot in the editor", "");
        };
      } else {
        el.className = "slot";
        el.title = slot.label || slot.id;

        var img = document.createElement("img");
        // <img> cannot send the auth header, so the token rides the query
        // string; the endpoint accepts either.
        img.src = "/api/icon/" + encodeURIComponent(slot.id)
                + "?t=" + encodeURIComponent(token);
        img.alt = "";
        (function (button, entry) {
          img.onerror = function () {
            button.innerHTML = '<span class="fallback">'
              + esc(String(entry.label || "?").charAt(0).toUpperCase())
              + "</span>";
          };
          button.onclick = function () { runButton(entry, button); };
        })(el, slot);
        el.appendChild(img);
      }
      box.appendChild(el);
    }
  }

  function renderDrawer() {
    var groups = shortcuts.groups || [];
    var tabs = $("tabs");
    tabs.innerHTML = "";
    groups.forEach(function (g, i) {
      var b = document.createElement("button");
      b.className = "tab" + (i === activeGroup ? " active" : "");
      b.textContent = (g.icon ? g.icon + " " : "") + (g.name || g.id);
      b.onclick = function () { activeGroup = i; renderDrawer(); };
      tabs.appendChild(b);
    });

    var deck = $("deck");
    deck.innerHTML = "";
    var group = groups[activeGroup];
    if (!group || !(group.buttons || []).length) {
      deck.innerHTML = '<div class="deck-empty">No shortcuts yet.<br>'
                     + 'Add some in the <a href="/editor">editor</a>.</div>';
      return;
    }
    group.buttons.forEach(function (btn) {
      var el = document.createElement("button");
      el.className = "btn";
      el.style.setProperty("--accent", btn.color || "#4c8dff");
      el.innerHTML = '<span class="ico">' + esc(btn.icon || "●") + "</span>"
                   + '<span class="lbl">' + esc(btn.label || btn.id) + "</span>";
      el.onclick = function () { runButton(btn, el); };
      deck.appendChild(el);
    });
  }

  /* Shared by the drawer tiles and the top-bar launchers, so it toggles a
   * class rather than rewriting className -- the two have different bases. */
  function runButton(btn, el) {
    if (el.classList.contains("busy")) return;

    // Destructive buttons (shutdown, close everything) carry "confirm", so a
    // mis-tap on a phone lying on the desk cannot take the PC down.
    if (btn.confirm) {
      var question = typeof btn.confirm === "string"
        ? btn.confirm
        : (btn.label || btn.id) + "?";
      if (!window.confirm(question)) return;
    }

    el.classList.add("busy");
    if (navigator.vibrate) navigator.vibrate(12);

    api("/api/run/" + encodeURIComponent(btn.id), { method: "POST" })
      .then(function (body) {
        toast(body.ok ? (body.message || "done") : (body.error || "failed"),
              body.ok ? "ok" : "bad");
      })
      .catch(function (err) { toast(err.message, "bad"); })
      .then(function () { el.classList.remove("busy"); });
  }

  $("fab").onclick = function () {
    $("drawer").hidden = false;
    loadShortcuts();
  };
  $("drawerClose").onclick = function () { $("drawer").hidden = true; };
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") $("drawer").hidden = true;
  });

  // ========================================================= kickoff =====
  fetch("/api/health")
    .then(function (r) { return r.json(); })
    .then(function (h) { if (h.poll_ms) pollMs = h.poll_ms; })
    .catch(function () {})
    .then(function () {
      setPage(0);
      tickClock();
      poll();
      loadShortcuts();
    });
})();
