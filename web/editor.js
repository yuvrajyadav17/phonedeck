/* PhoneDeck shortcut editor.
 *
 * Edits the same shortcuts.json the dashboard reads. The model is held in
 * memory, mutated as you type, and written back wholesale on Save.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  // Number of top-bar slots. Must match SLOT_COUNT in app.js.
  var SLOT_COUNT = 4;

  // --------------------------------------------------------------- auth --
  var token = new URLSearchParams(location.search).get("t");
  if (token) {
    try { localStorage.setItem("pd_token", token); } catch (e) {}
    history.replaceState(null, "", location.pathname);
  } else {
    try { token = localStorage.getItem("pd_token") || ""; } catch (e) { token = ""; }
  }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign(
      { "X-PhoneDeck-Token": token, "Content-Type": "application/json" },
      options.headers || {}
    );
    return fetch(path, options).then(function (res) {
      return res.json().catch(function () { return { ok: false, error: "bad response" }; });
    });
  }

  var toastTimer;
  function toast(msg, kind) {
    var el = $("toast");
    el.textContent = msg;
    el.className = "toast " + (kind || "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 3500);
  }

  function markDirty() {
    var el = $("savedState");
    el.textContent = "unsaved changes";
    el.className = "saved dirty";
  }

  // -------------------------------------------------------------- state --
  var model = { version: 1, groups: [] };
  var mode = "button";  // "button" (drawer tile) or "slot" (top-bar launcher)
  var gi = 0;           // selected group index
  var bi = -1;          // selected button index
  var si = -1;          // selected top-bar slot index

  function group() { return model.groups[gi] || null; }
  function button() {
    var g = group();
    return g && g.buttons ? g.buttons[bi] || null : null;
  }
  function slot() {
    return (model.topbar || [])[si] || null;
  }
  /* Whichever thing the form is currently editing. Both carry an `action`,
     so the whole action half of the form is shared between them. */
  function current() { return mode === "slot" ? slot() : button(); }

  function slugify(text, fallback) {
    var s = String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-")
             .replace(/^-+|-+$/g, "");
    return s || fallback;
  }

  function uniqueId(base) {
    var taken = {};
    model.groups.forEach(function (g) {
      (g.buttons || []).forEach(function (b) { taken[b.id] = true; });
    });
    if (!taken[base]) return base;
    var n = 2;
    while (taken[base + "-" + n]) n++;
    return base + "-" + n;
  }

  // ------------------------------------------------------------ sidebar --
  function renderSlots() {
    // Pad rather than replace: a config written before the count grew still
    // keeps its existing slots and simply gains empty ones.
    if (!model.topbar) model.topbar = [];
    while (model.topbar.length < SLOT_COUNT) {
      model.topbar.push({
        id: "slot" + (model.topbar.length + 1), label: "", action: null
      });
    }
    var ul = $("slotList");
    ul.innerHTML = "";
    model.topbar.forEach(function (s, i) {
      var li = document.createElement("li");
      li.className = (mode === "slot" && i === si) ? "active" : "";
      var assigned = !!(s && s.action);
      li.innerHTML = '<span class="ico"></span><span class="txt"></span>';
      li.querySelector(".ico").textContent = assigned ? (i + 1) : "+";
      li.querySelector(".txt").textContent = assigned
        ? (s.label || s.id)
        : "empty";
      if (!assigned) li.querySelector(".txt").style.color = "#5f7188";
      li.onclick = function () {
        mode = "slot"; si = i; bi = -1;
        renderSlots(); renderGroups(); renderButtons(); showForm();
      };
      ul.appendChild(li);
    });
  }

  function renderGroups() {
    var ul = $("groupList");
    ul.innerHTML = "";
    if (!model.groups.length) {
      ul.innerHTML = '<li class="empty">No groups yet</li>';
      return;
    }
    model.groups.forEach(function (g, i) {
      var li = document.createElement("li");
      li.className = i === gi ? "active" : "";
      li.innerHTML = '<span class="ico"></span><span class="txt"></span>';
      li.querySelector(".ico").textContent = g.icon || "●";
      li.querySelector(".txt").textContent = g.name || g.id;

      ["↑", "↓"].forEach(function (arrow, k) {
        var mv = document.createElement("button");
        mv.className = "move";
        mv.textContent = arrow;
        mv.title = k === 0 ? "Move up" : "Move down";
        mv.onclick = function (e) {
          e.stopPropagation();
          moveItem(model.groups, i, k === 0 ? -1 : 1);
          gi = Math.max(0, Math.min(model.groups.length - 1, i + (k === 0 ? -1 : 1)));
          markDirty(); renderGroups(); renderButtons();
        };
        li.appendChild(mv);
      });

      li.onclick = function () {
        mode = "button"; gi = i; bi = -1; si = -1;
        renderSlots(); renderGroups(); renderButtons(); showForm();
      };
      ul.appendChild(li);
    });
  }

  function renderButtons() {
    var ul = $("buttonList");
    ul.innerHTML = "";
    var g = group();
    if (!g) { ul.innerHTML = '<li class="empty">No group selected</li>'; return; }
    var buttons = g.buttons || [];
    if (!buttons.length) { ul.innerHTML = '<li class="empty">No buttons yet</li>'; return; }

    buttons.forEach(function (b, i) {
      var li = document.createElement("li");
      li.className = i === bi ? "active" : "";
      li.innerHTML = '<span class="ico"></span><span class="txt"></span>';
      li.querySelector(".ico").textContent = b.icon || "●";
      li.querySelector(".txt").textContent = b.label || b.id;

      ["↑", "↓"].forEach(function (arrow, k) {
        var mv = document.createElement("button");
        mv.className = "move";
        mv.textContent = arrow;
        mv.onclick = function (e) {
          e.stopPropagation();
          moveItem(buttons, i, k === 0 ? -1 : 1);
          bi = Math.max(0, Math.min(buttons.length - 1, i + (k === 0 ? -1 : 1)));
          markDirty(); renderButtons();
        };
        li.appendChild(mv);
      });

      li.onclick = function () {
        mode = "button"; bi = i; si = -1;
        renderSlots(); renderButtons(); showForm();
      };
      ul.appendChild(li);
    });
  }

  function moveItem(list, index, delta) {
    var target = index + delta;
    if (target < 0 || target >= list.length) return;
    var tmp = list[index];
    list[index] = list[target];
    list[target] = tmp;
  }

  // ---------------------------------------------------------------- form --
  var BODIES = {
    app: "bodyApp", aumid: "bodyApp", macro: "bodyMacro",
    urls: "bodyUrls", hotkey: "bodyHotkey", text: "bodyText",
    command: "bodyCommand", powershell: "bodyCommand", chain: "bodyChain"
  };

  function showBody(type) {
    var wanted = BODIES[type] || "bodyApp";
    Object.keys(BODIES).forEach(function (k) { $(BODIES[k]).hidden = true; });
    $(wanted).hidden = false;
  }

  function updateIconPreview(s) {
    var img = $("sPreview");
    if (!s || !s.action) { img.style.display = "none"; return; }
    img.style.display = "block";
    // Cache-bust so a changed icon source shows immediately.
    img.src = "/api/icon/" + encodeURIComponent(s.id)
            + "?t=" + encodeURIComponent(token) + "&_=" + Date.now();
    img.onerror = function () { img.style.display = "none"; };
  }

  function showForm() {
    var target = current();
    var g = group();
    var isSlot = mode === "slot";

    $("placeholder").hidden = !!target;
    $("form").hidden = !target;

    // The action half of the form is shared; only the identity half differs.
    $("fsSlot").hidden = !isSlot;
    $("fsGroup").hidden = isSlot;
    $("fsButton").hidden = isSlot;
    $("delButton").hidden = isSlot;

    if (!isSlot && g) {
      $("gName").value = g.name || "";
      $("gIcon").value = g.icon || "";
    }
    if (!target) return;

    if (isSlot) {
      $("sLabel").value = target.label || "";
      $("sIcon").value = target.icon_source || "";
      updateIconPreview(target);
    } else {
      $("bLabel").value = target.label || "";
      $("bIcon").value = target.icon || "";
      $("bColor").value = target.color || "#4c8dff";
      $("bId").value = target.id || "";
      $("bConfirm").checked = !!target.confirm;
    }

    // Deliberately not written back to the model: merely selecting an empty
    // slot must not turn it into an assigned-but-broken one.
    var action = target.action || { type: "app", target: "" };
    var type = action.type === "cmd" ? "command" : (action.type === "ps" ? "powershell" : action.type);
    if (type === "url") type = "urls";
    $("aType").value = BODIES[type] ? type : "app";
    showBody($("aType").value);

    $("aTarget").value = action.target || "";
    $("aArgs").value = joinArgs(action.args);
    $("aUrls").value = (action.targets || (action.target ? [action.target] : [])).join("\n");
    $("aNewWindow").checked = action.new_window !== false;
    $("aBrowser").value = action.browser || "";
    $("aProfile").value = action.profile || "";
    $("aSpeed").value = action.speed || 1;
    showMacroCount((action.events || []).length);
    $("aKeys").value = action.keys || "";
    $("aRepeat").value = action.repeat || 1;
    $("aText").value = action.text || "";
    $("aCommand").value = action.target || "";
    renderSteps();
    syncRaw();
  }

  /* Read every field back into the model. Called on any input event. */
  function readForm() {
    var target = current();
    if (!target) return;
    var isSlot = mode === "slot";

    if (isSlot) {
      target.label = $("sLabel").value;
      var iconSrc = $("sIcon").value.trim();
      if (iconSrc) {
        target.icon_source = iconSrc;
      } else {
        delete target.icon_source;   // fall back to the launched executable
      }
    } else {
      var g = group();
      if (!g) return;
      g.name = $("gName").value;
      g.icon = $("gIcon").value;

      target.label = $("bLabel").value;
      target.icon = $("bIcon").value;
      target.color = $("bColor").value;
      var newId = $("bId").value.trim();
      if (newId) target.id = newId;

      if ($("bConfirm").checked) {
        // Keep a custom prompt string if one was set by hand; otherwise the
        // phone falls back to asking with the button's own label.
        if (!target.confirm) target.confirm = true;
      } else {
        delete target.confirm;
      }
    }

    var type = $("aType").value;
    var action = { type: type };

    if (type === "app") {
      action.target = $("aTarget").value;
      var args = splitArgs($("aArgs").value);
      if (args.length) action.args = args;
    } else if (type === "aumid") {
      action.target = $("aTarget").value.trim();
    } else if (type === "urls") {
      action.targets = $("aUrls").value.split("\n")
        .map(function (s) { return s.trim(); })
        .filter(Boolean);
      // Only written when it differs from the default, to keep the JSON clean.
      if (!$("aNewWindow").checked) action.new_window = false;
      var browserPath = $("aBrowser").value.trim();
      if (browserPath) action.browser = browserPath;
      var profileDir = $("aProfile").value.trim();
      if (profileDir) action.profile = profileDir;
    } else if (type === "hotkey") {
      action.keys = $("aKeys").value.trim();
      var rep = parseInt($("aRepeat").value, 10);
      if (rep > 1) action.repeat = rep;
    } else if (type === "text") {
      action.text = $("aText").value;
    } else if (type === "command" || type === "powershell") {
      action.target = $("aCommand").value;
    } else if (type === "macro") {
      // Carried over deliberately: the events live only in the model,
      // there is no form field holding them.
      action.events = (target.action && target.action.events) || [];
      var speed = parseFloat($("aSpeed").value);
      if (speed && speed !== 1) action.speed = speed;
    } else if (type === "chain") {
      action.steps = readSteps();
    }

    target.action = action;
    markDirty();
    if (isSlot) { renderSlots(); } else { renderButtons(); }
    syncRaw();
  }

  /* Arguments are split on whitespace but honour double quotes, because real
     ones contain spaces -- Chromium's own --profile-directory="Profile 3"
     being exactly the case this dashboard needs. */
  function splitArgs(text) {
    var out = [], re = /"([^"]*)"|(\S+)/g, m;
    while ((m = re.exec(text)) !== null) {
      out.push(m[1] !== undefined ? m[1] : m[2]);
    }
    return out;
  }

  function joinArgs(list) {
    return (list || []).map(function (a) {
      return /\s/.test(a) ? '"' + a + '"' : a;
    }).join(" ");
  }

  // --------------------------------------------------------- chain steps --
  var STEP_TYPES = ["app", "urls", "hotkey", "text", "command", "powershell",
                    "delay", "notify"];

  function stepRow(step) {
    var row = document.createElement("div");
    row.className = "step";

    var sel = document.createElement("select");
    STEP_TYPES.forEach(function (t) {
      var o = document.createElement("option");
      o.value = t; o.textContent = t;
      sel.appendChild(o);
    });
    sel.value = STEP_TYPES.indexOf(step.type) >= 0 ? step.type : "command";

    var val = document.createElement("input");
    val.type = "text";
    val.placeholder = "value";
    val.value = step.type === "delay" ? (step.ms || 200)
              : step.type === "hotkey" ? (step.keys || "")
              : step.type === "text" ? (step.text || "")
              : step.type === "urls" ? (step.targets || []).join(" ")
              : (step.target || "");

    var up = document.createElement("button");
    up.type = "button"; up.className = "move"; up.textContent = "↑";
    var rm = document.createElement("button");
    rm.type = "button"; rm.className = "move"; rm.textContent = "×";

    row.appendChild(sel); row.appendChild(val); row.appendChild(up); row.appendChild(rm);

    sel.onchange = function () { val.placeholder = sel.value === "delay" ? "milliseconds" : "value"; readForm(); };
    val.oninput = readForm;
    up.onclick = function () {
      var box = $("steps"), idx = Array.prototype.indexOf.call(box.children, row);
      if (idx > 0) { box.insertBefore(row, box.children[idx - 1]); readForm(); }
    };
    rm.onclick = function () { row.remove(); readForm(); };
    return row;
  }

  function renderSteps() {
    var box = $("steps");
    box.innerHTML = "";
    var action = (button() || {}).action || {};
    (action.steps || []).forEach(function (s) { box.appendChild(stepRow(s)); });
  }

  function readSteps() {
    return Array.prototype.map.call($("steps").children, function (row) {
      var type = row.children[0].value;
      var raw = row.children[1].value;
      if (type === "delay") return { type: "delay", ms: parseInt(raw, 10) || 200 };
      if (type === "hotkey") return { type: "hotkey", keys: raw };
      if (type === "text") return { type: "text", text: raw };
      if (type === "urls") return { type: "urls", targets: raw.split(/\s+/).filter(Boolean) };
      return { type: type, target: raw };
    });
  }

  // ------------------------------------------------------------ raw json --
  function syncRaw() {
    var t = current();
    if (t) $("rawJson").value = JSON.stringify(t.action || {}, null, 2);
  }

  $("applyRaw").onclick = function () {
    var t = current();
    if (!t) return;
    try {
      var parsed = JSON.parse($("rawJson").value);
      if (!parsed || typeof parsed !== "object") throw new Error("not an object");
      t.action = parsed;
      markDirty();
      showForm();
      toast("JSON applied", "ok");
    } catch (err) {
      toast("Invalid JSON: " + err.message, "bad");
    }
  };

  // ------------------------------------------------------------- actions --
  $("addGroup").onclick = function () {
    var name = prompt("Group name:", "New group");
    if (!name) return;
    model.groups.push({ id: slugify(name, "group"), name: name, icon: "⭐", buttons: [] });
    mode = "button"; si = -1;
    gi = model.groups.length - 1;
    bi = -1;
    markDirty(); renderSlots(); renderGroups(); renderButtons(); showForm();
  };

  $("delGroup").onclick = function () {
    var g = group();
    if (!g || !confirm("Delete group \"" + (g.name || g.id) + "\" and all its buttons?")) return;
    model.groups.splice(gi, 1);
    gi = Math.max(0, gi - 1); bi = -1;
    markDirty(); renderGroups(); renderButtons(); showForm();
  };

  $("addButton").onclick = function () {
    var g = group();
    if (!g) { toast("Add a group first", "bad"); return; }
    g.buttons = g.buttons || [];
    g.buttons.push({
      id: uniqueId("button"), label: "New button", icon: "⭐",
      color: "#4c8dff", action: { type: "app", target: "" }
    });
    mode = "button"; si = -1;
    bi = g.buttons.length - 1;
    markDirty(); renderSlots(); renderButtons(); showForm();
  };

  $("clearSlot").onclick = function () {
    var s = slot();
    if (!s || !confirm("Clear slot " + (si + 1) + "?")) return;
    s.label = "";
    s.action = null;
    delete s.icon_source;
    markDirty();
    renderSlots();
    showForm();
  };

  $("delButton").onclick = function () {
    var g = group(), b = button();
    if (!g || !b || !confirm("Delete \"" + (b.label || b.id) + "\"?")) return;
    g.buttons.splice(bi, 1);
    bi = -1;
    markDirty(); renderButtons(); showForm();
  };

  $("testBtn").onclick = function () {
    var t = current();
    if (!t) return;
    readForm();
    api("/api/run-inline", { method: "POST", body: JSON.stringify(t.action) })
      .then(function (r) {
        toast(r.ok ? (r.message || "ok") : ("Failed: " + (r.error || "unknown")),
              r.ok ? "ok" : "bad");
      })
      .catch(function (e) { toast(e.message, "bad"); });
  };

  $("saveBtn").onclick = function () {
    readForm();
    api("/api/shortcuts", { method: "PUT", body: JSON.stringify(model) })
      .then(function (r) {
        if (r.ok) {
          var el = $("savedState");
          el.textContent = "saved";
          el.className = "saved ok";
          toast("Saved to shortcuts.json", "ok");
        } else {
          toast("Save failed: " + (r.error || "unknown"), "bad");
        }
      })
      .catch(function (e) { toast(e.message, "bad"); });
  };

  // ------------------------------------------------------ macro recording --
  var macroPoll = null;

  function showMacroCount(count) {
    $("macroStatus").textContent = count
      ? count + " event" + (count === 1 ? "" : "s") + " recorded"
      : "nothing recorded yet";
  }

  function setRecording(on) {
    $("macroRecord").disabled = on;
    $("macroStop").disabled = !on;
  }

  $("macroRecord").onclick = function () {
    api("/api/macro/record/start", { method: "POST" }).then(function (r) {
      if (!r.ok) { toast(r.error || "could not start recording", "bad"); return; }
      setRecording(true);
      toast("Recording — do the actions, then press Stop", "ok");
      macroPoll = setInterval(function () {
        api("/api/macro/status").then(function (s) {
          if (s.recording) {
            $("macroStatus").textContent =
              "recording… " + s.events + " events, " + s.seconds + "s";
          }
        });
      }, 1000);
    });
  };

  $("macroStop").onclick = function () {
    clearInterval(macroPoll);
    // trim=1: this very click happened on the PC and is not part of the macro.
    api("/api/macro/record/stop?trim=1", { method: "POST" }).then(function (r) {
      setRecording(false);
      if (!r.ok) { toast(r.error || "not recording", "bad"); return; }
      var t = current();
      if (!t) return;
      t.action = t.action || {};
      t.action.type = "macro";
      t.action.events = r.events || [];
      markDirty();
      showMacroCount(t.action.events.length);
      syncRaw();
      toast(r.message + " — press Save to keep it", "ok");
    });
  };

  $("aType").onchange = function () { showBody($("aType").value); readForm(); };
  $("addStep").onclick = function () {
    $("steps").appendChild(stepRow({ type: "command", target: "" }));
    readForm();
  };

  // Any edit anywhere in the form writes straight through to the model.
  $("form").addEventListener("input", function (e) {
    if (e.target.closest("#rawJson")) return;   // raw JSON applies explicitly
    if (e.target.closest("#steps")) return;     // step rows have own handlers
    readForm();
  });

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); $("saveBtn").click(); }
  });

  /* Inside the desktop shell there is no browser to open a tab in, so the
     dashboard link is handed to the host instead. pywebview injects its API
     asynchronously, hence the event as well as the immediate check. */
  function wireDashboardLink() {
    var link = document.querySelector('a.ghost[href="/"]');
    if (!link || !window.pywebview || !window.pywebview.api) return;
    link.onclick = function (e) {
      e.preventDefault();
      window.pywebview.api.open_dashboard();
    };
  }
  window.addEventListener("pywebviewready", wireDashboardLink);
  wireDashboardLink();

  // ---------------------------------------------------------------- load --
  api("/api/shortcuts").then(function (r) {
    if (!r.ok) { toast("Could not load: " + (r.error || "unauthorised"), "bad"); return; }
    model = r.shortcuts || { version: 1, groups: [] };
    if (!model.groups) model.groups = [];
    renderSlots();
    renderGroups();
    renderButtons();
    showForm();
  });
})();
