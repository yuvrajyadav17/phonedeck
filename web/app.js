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
      if (e.touches.length !== 1) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      tracking = true;
    }, { passive: true });

    card.addEventListener("touchend", function (e) {
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
      var value = metric === "mem" ? esc(p.mem_h) : p.cpu.toFixed(1) + "%";
      html += '<div class="proc" data-pid="' + p.pid + '">'
            +   '<div class="name">' + esc(p.name) + "</div>"
            +   '<div class="val">' + value + "</div>"
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
      poll();
      loadShortcuts();
    });
})();
