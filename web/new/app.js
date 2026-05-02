/* MuzAIk — Liquid Glass wired logic
   ---------------------------------------------------------------
   Connects the Liquid Glass UI to the existing MuzAIk backend
   (control_server + segment_conductor + generate_dummy_stream).

   Endpoints:
      GET  /api/radio-status              (live-window + conductor status)
      GET  /api/llm-status                (existing)
     GET  /api/sysinfo                   (new — added in control_server.py)
     GET  /public/conductor-status.json
     GET  /public/live-control.json
     GET  /public/stream/state.json
     GET  /public/stream/role-bundles.json
     GET  /public/current-session.json
     GET  /public/archive/index.json
     GET  /public/personas.json
     GET  /api/vote-round
     GET  /api/fallback
     POST /api/live-control
     POST /api/personas
     POST /api/vote
     POST /api/suggestions
   --------------------------------------------------------------- */

(function () {
  "use strict";

  /* -------- paths (relative to /web/new/index.html) -------- */
  const PATHS = {
    apiLlmStatus:    "/api/llm-status",
    apiRadioStatus:  "/api/radio-status",
    apiSysinfo:      "/api/sysinfo",
    apiLiveControl:  "/api/live-control",
    apiPersonas:     "/api/personas",
    apiPresetModes:  "/api/preset-modes",
    apiVoteRound:    "/api/vote-round",
    apiVote:         "/api/vote",
    apiSuggestions:  "/api/suggestions",
    apiFallback:     "/api/fallback",
    apiAdminLogin:   "/api/admin/login",
    apiAdminSession: "/api/admin/session",
    apiAdminLogout:  "/api/admin/logout",
    apiAdminVoteRound: "/api/admin/vote-round",
    apiAdminSuggestions: "/api/admin/suggestions",
    apiAdminPromoteSuggestion: "/api/admin/suggestions/promote",
    apiAdminOverride: "/api/admin/override",
    apiAdminFallback: "/api/admin/fallback",
    apiCollapse:     "/api/admin/collapse",
    conductorStatus: "../../public/conductor-status.json",
    liveControl:     "../../public/live-control.json",
    presetModes:     "../../public/preset-modes.json",
    state:           "../../public/stream/state.json",
    roleBundles:     "../../public/stream/role-bundles.json",
    currentSession:  "../../public/current-session.json",
    archiveIndex:    "../../public/archive/index.json",
    personas:        "../../public/personas.json",
    streamHls:       "../../public/stream/index.m3u8",
    recordingFallback: "../../public/recordings/dummy-live-recording.mp3",
  };
  if (window.AIPS_CONFIG) {
    if (window.AIPS_CONFIG.backendBaseUrl) {
      Object.keys(PATHS).forEach(key => {
        if (key.indexOf("api") === 0) PATHS[key] = window.AIPS_CONFIG.backendBaseUrl.replace(/\/$/, "") + PATHS[key];
      });
    }
    if (window.AIPS_CONFIG.mediaBaseUrl) {
      ["conductorStatus", "liveControl", "presetModes", "state", "roleBundles", "currentSession", "archiveIndex", "personas", "streamHls", "recordingFallback"].forEach(key => {
        PATHS[key] = window.AIPS_CONFIG.mediaBaseUrl.replace(/\/$/, "") + "/" + PATHS[key].replace(/^\.\.\/\.\.\//, "");
      });
    }
  }
  const MEDIA_BASE_URL = window.AIPS_CONFIG && window.AIPS_CONFIG.mediaBaseUrl ? window.AIPS_CONFIG.mediaBaseUrl.replace(/\/$/, "") : "";

  /* -------- helpers -------- */
  function $(id) { return document.getElementById(id); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }
  function fmtClock(secs) {
    if (!isFinite(secs) || secs < 0) secs = 0;
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = Math.floor(secs % 60);
    return [h, m, s].map(n => String(n).padStart(2, "0")).join(":");
  }
  function fmtDb(volume01) {
    if (!volume01 || volume01 <= 0) return "-∞ dB";
    return (20 * Math.log10(volume01)).toFixed(1) + " dB";
  }
  function setStatus(node, msg, kind) {
    if (!node) return;
    node.textContent = msg || "";
    node.className = "save-status" + (kind ? " " + kind : "");
  }
  function mediaUrl(url) {
    if (!url) return "";
    if (/^https?:\/\//i.test(url)) return url;
    if (MEDIA_BASE_URL && url.charAt(0) === "/") return MEDIA_BASE_URL + url;
    return url;
  }
  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(r => r.json().then(j => {
      if (!r.ok || j.ok === false) throw new Error(j.error || "Request failed (" + r.status + ")");
      return j;
    }));
  }
  function getJson(url) {
    return fetch(url, { cache: "no-store", credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .catch(() => null);
  }
  function bindClick(id, handler) {
    const node = $(id);
    if (node) node.addEventListener("click", handler);
  }

  /* ------------------------------------------------------------------
   * STATE
   * ----------------------------------------------------------------*/
  const state = {
    masterVolume: 0.8,
    isLive: false,
    audioCtxStarted: false,
    hlsInstance: null,
    latestArchiveRecording: PATHS.recordingFallback,
    personas: {},
    presetModes: null,
    audioStartedAt: null,         // wall time when current source started playing
    sectionSeconds: 10,
    tapTimes: [],
    currentSection: null,
    conductor: null,
    stateJson: null,
    roleBundles: null,
    selectedVoteOption: null,
    selectedRoleVotes: {},
    radioStatus: null,
  };

  const IS_ADMIN_ROUTE = window.location.pathname.replace(/\/+$/, "") === "/admin";
  document.body.classList.toggle("admin-route", IS_ADMIN_ROUTE);
  document.body.classList.toggle("public-route", !IS_ADMIN_ROUTE);

  /* ------------------------------------------------------------------
   * SYSTEM TIME
   * ----------------------------------------------------------------*/
  (function clockTick() {
    function tick() {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, "0");
      const mm = String(now.getMinutes()).padStart(2, "0");
      const ss = String(now.getSeconds()).padStart(2, "0");
      $("sys-clock").textContent = hh + ":" + mm + ":" + ss;
      const months = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
      $("sys-date").textContent = months[now.getMonth()] + " " + String(now.getDate()).padStart(2, "0") + ", " + now.getFullYear();
    }
    tick();
    setInterval(tick, 1000);
  })();

  /* ------------------------------------------------------------------
   * SYSINFO (CPU / RAM / NET) — every 2s
   * ----------------------------------------------------------------*/
  function netHistory() {
    const max = 8;
    const buf = [];
    return {
      push(v) { buf.push(v); if (buf.length > max) buf.shift(); return buf; },
      values() { return buf.slice(); },
    };
  }
  const cpuHist = netHistory();
  const ramHist = netHistory();
  const netHist = netHistory();

  function paintBars(rootId, history, maxValue) {
    const root = $(rootId);
    if (!root) return;
    const bars = root.querySelectorAll("span");
    const values = history.values();
    const n = bars.length;
    for (let i = 0; i < n; i++) {
      const idx = values.length - n + i;
      const v = idx >= 0 ? values[idx] : 0;
      const pct = clamp(v / (maxValue || 1) * 100, 4, 100);
      bars[i].style.height = pct + "%";
    }
  }

  function refreshSysinfo() {
    return getJson(PATHS.apiSysinfo).then(info => {
      if (!info || info.ok === false) return;
      const cpu = Number(info.cpu_pct) || 0;
      const ram = Number(info.ram_pct) || 0;
      const net = Number(info.net_mbps) || 0;
      cpuHist.push(cpu); ramHist.push(ram); netHist.push(net);
      $("stat-cpu").textContent = cpu.toFixed(0) + "%";
      $("stat-ram").textContent = ram.toFixed(0) + "%";
      $("stat-net").textContent = net.toFixed(1);
      paintBars("bars-cpu", cpuHist, 100);
      paintBars("bars-ram", ramHist, 100);
      // For NET, scale to recent peak (min 1 MB/s) so the bars always show motion
      const peak = Math.max(1, ...netHist.values());
      paintBars("bars-net", netHist, peak);
    });
  }
  refreshSysinfo();
  setInterval(refreshSysinfo, 2000);

  /* ------------------------------------------------------------------
   * RADIO STATUS — scheduled 5AM-7PM America/New_York window
   * ----------------------------------------------------------------*/
  function fallbackRadioStatus() {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(new Date());
    const values = {};
    parts.forEach(part => { values[part.type] = part.value; });
    const hour = Number(values.hour) || 0;
    const minute = Number(values.minute) || 0;
    const easternMinutes = hour * 60 + minute;
    const shouldBeLive = easternMinutes >= 5 * 60 && easternMinutes < 19 * 60;
    return {
      ok: true,
      should_be_live: shouldBeLive,
      state: shouldBeLive ? "opening" : "offline",
      message: shouldBeLive ? "Live window is open; waiting for backend status." : "Radio is offline outside the 5:00 AM–7:00 PM EST window.",
      window_label: "5:00 AM–7:00 PM EST",
      next_transition_label: shouldBeLive ? "closes at" : "opens at",
      next_transition_at_eastern: shouldBeLive ? "7:00 PM EST" : "5:00 AM EST",
      conductor_running: false,
      live_ready: false,
    };
  }

  function radioAllowsLive() {
    return !state.radioStatus || state.radioStatus.should_be_live !== false;
  }

  function updateLiveActionState() {
    const btn = $("btn-apply");
    if (!btn) return;
    const offline = state.radioStatus && state.radioStatus.should_be_live === false;
    btn.disabled = !!offline;
    btn.title = offline ? "Radio is offline outside the 5:00 AM–7:00 PM EST broadcast window." : "Apply the prompt and start live audio";
  }

  function refreshRadioStatus() {
    const btn = $("btn-check-llm");
    if (btn) btn.disabled = true;
    $("llm-message").textContent = "Checking radio status…";
    $("llm-latency").textContent = "";
    return getJson(PATHS.apiRadioStatus)
      .then(result => renderRadioStatus(result || fallbackRadioStatus()))
      .finally(() => { if (btn) btn.disabled = false; });
  }

  function renderRadioStatus(result) {
    state.radioStatus = result;
    const orb = $("llm-orb");
    const verb = $("llm-verb");
    const shouldBeLive = !!result.should_be_live;
    const onAir = shouldBeLive && !!result.conductor_running && !!result.live_ready;
    orb.classList.toggle("connected", onAir);
    orb.classList.toggle("pending", shouldBeLive && !onAir);
    verb.textContent = onAir ? "Live" : (shouldBeLive ? "Opening" : "Offline");
    verb.className = "verb " + (onAir ? "ok" : (shouldBeLive ? "warn" : "bad"));
    $("llm-message").textContent = "— " + (result.message || "Radio status unavailable.");
    $("llm-latency").textContent = (result.next_transition_label || "next change") + " " + (result.next_transition_at_eastern || "—");
    $("meta-model").textContent = result.window_label || "5:00 AM–7:00 PM EST";
    updateLiveActionState();
  }
  bindClick("btn-check-llm", refreshRadioStatus);
  refreshRadioStatus();
  setInterval(refreshRadioStatus, 30000);

  /* ------------------------------------------------------------------
   * CONDUCTOR STATUS — every 2s, drives sync%, hint lines, system orb
   * ----------------------------------------------------------------*/
  function paintSync(syncPct) {
    const bars = $("sync-bars").querySelectorAll("i");
    const lit = Math.round(clamp(syncPct, 0, 100) / 12.5);
    bars.forEach((b, i) => {
      const h = (i + 1) * 12;
      b.style.height = (i < lit ? h : Math.max(2, h - 25)) + "%";
      b.style.opacity = i < lit ? 1 : 0.32;
    });
  }

  function refreshConductor() {
    return getJson(PATHS.conductorStatus).then(c => {
      state.conductor = c;
      const sysOrb = $("system-orb");
      const sysLabel = $("system-status-label");
      const hintConductor = $("hint-conductor");
      const bufDot = $("buffer-dot");
      const bufText = $("buffer-text");
      const livePill = $("live-pill");
      const scheduledLive = radioAllowsLive();

      if (!scheduledLive) {
        sysOrb.classList.add("offline");
        sysLabel.innerHTML = "Radio<br/>Offline";
        $("meta-session").textContent = "OFF AIR";
        $("meta-sync").textContent = "—";
        paintSync(0);
        hintConductor.textContent = (state.radioStatus && state.radioStatus.message) || "Radio is offline outside the daily broadcast window.";
        bufDot.classList.add("bad");
        bufText.textContent = "Radio offline until the next 5:00 AM EST opening window";
        livePill.textContent = "OFFLINE";
        livePill.classList.add("idle");
        state.isLive = false;
        return;
      }

      if (!c) {
        sysOrb.classList.add("offline");
        sysLabel.innerHTML = "System<br/>Offline";
        $("meta-session").textContent = "OFFLINE";
        $("meta-sync").textContent = "—";
        paintSync(0);
        hintConductor.textContent = "Conductor status: not running. Prompt changes apply to the next generated form.";
        bufDot.classList.add("bad");
        bufText.textContent = "Conductor not running";
        livePill.textContent = "IDLE";
        livePill.classList.add("idle");
        state.isLive = false;
        return;
      }

      sysOrb.classList.toggle("offline", !c.live_ready);
      sysLabel.innerHTML = c.live_ready ? "System<br/>Online" : "System<br/>Buffering";
      $("meta-session").textContent = (c.session_id || "—").toString().toUpperCase();
      state.sectionSeconds = c.section_seconds || state.sectionSeconds;

      // Sync %: when live, fall to 99-100% based on prompt-ETA backlog; while prebuffering, ramp from 0 to 100
      let sync;
      if (c.live_ready) {
        const eta = Number.isInteger(c.prompt_sections_until_heard) ? c.prompt_sections_until_heard : 0;
        sync = Math.max(40, 100 - eta * 1.5);
      } else {
        const buf = c.buffered_sections || 0;
        const target = Math.max(1, c.prebuffer_sections || 1);
        sync = clamp((buf / target) * 100, 0, 95);
      }
      $("meta-sync").textContent = sync.toFixed(1) + "%";
      paintSync(sync);

      bufDot.classList.toggle("bad", !c.live_ready);
      bufText.textContent = c.live_ready
        ? "Live buffer ready"
        : "Prebuffering · " + (c.buffered_sections || 0) + "/" + (c.prebuffer_sections || 0) + " sections";

      const isPlayingLive = state.isLive && !$("player").paused;
      livePill.textContent = isPlayingLive ? "LIVE" : (c.live_ready ? "READY" : "WAIT");
      livePill.classList.toggle("idle", !isPlayingLive);

      const promptEta = Number.isInteger(c.prompt_sections_until_heard)
        ? "audible in ~" + c.prompt_sections_until_heard + " buffered section(s)"
        : "next generated section";
      hintConductor.textContent =
        "Conductor: " + (c.status || "—") + " · section " + (c.section_index ?? "—") +
        " · buffer " + (c.buffered_sections || 0) + "/" + (c.prebuffer_sections || 0) +
        " · next boundary " + (c.next_section_eta_seconds ?? "?") + "s · " + promptEta;
    });
  }
  refreshConductor();
  setInterval(refreshConductor, 2000);

  /* ------------------------------------------------------------------
   * LIVE CONTROL — initial load
   * ----------------------------------------------------------------*/
  function renderLiveControl(c) {
    if (!c) return;
    const level = Math.round((c.psychosis_level || 0) * 100);
    $("prompt-box").value = c.prompt || "";
    $("drift").value = String(level);
    $("drift-readout").textContent = level + " %";
    renderItunesPlayer(c);
  }

  function renderItunesPlayer(c) {
    var activeMode = activePreset(state.presetModes);
    var activePresetId = state.presetModes && state.presetModes.active_profile;
    var isCustom = !activeMode || activePresetId === "none";
    var modeLabel = isCustom ? "Custom" : (activeMode.label || presetLabelFromId(activePresetId));
    var desc = isCustom
      ? "Freeform prompt mode. Write anything and the ensemble will interpret it."
      : (activeMode.description || "");
    var bpm = (c && c.tempo_bpm) || (activeMode && activeMode.tempo_bpm) || "—";
    var key = (c && c.key) || (activeMode && activeMode.key) || "—";
    var drift = c ? Math.round((c.psychosis_level || 0) * 100) : 25;
    var prompt = (c && c.prompt) || "";

    $("itunes-mode-name").textContent = modeLabel;
    $("itunes-mode-desc").textContent = desc;
    $("itunes-bpm").textContent = bpm + " BPM";
    $("itunes-key").textContent = String(key).toUpperCase();
    $("itunes-drift").textContent = "DRIFT " + drift + "%";
    $("itunes-marquee").innerHTML = "&#9835; " + escapeHtml(prompt || "No prompt set.") + " &#9835;";
  }
  getJson(PATHS.liveControl).then(renderLiveControl);

  /* ------------------------------------------------------------------
   * VOTING + SUGGESTIONS
   * ----------------------------------------------------------------*/
  function renderVoteRound(payload) {
    const optionsRoot = $("vote-options");
    const roleRoot = $("role-vote-options");
    if (!optionsRoot || !payload || !payload.round) return;
    const round = payload.round;
    const tally = payload.tally || { counts: {}, total_votes: 0 };
    const options = Array.isArray(round.options) ? round.options : [];
    const eta = payload.audible_eta || {};
    const winnerLabel = tally.winner ? " · leading: " + tally.winner : "";
    const etaCopy = eta.message ? " · " + eta.message : "";
    $("vote-status").textContent = "Vote for the next generated section · " + (tally.total_votes || 0) + " vote(s) counted" + winnerLabel + etaCopy;
    optionsRoot.innerHTML = options.map(opt => {
      const count = (tally.counts && tally.counts[opt.id]) || 0;
      return '<button class="preset-btn" type="button" data-vote-option="' + escapeHtml(opt.id) + '" aria-pressed="' + String(state.selectedVoteOption === opt.id) + '">' + escapeHtml(opt.label || opt.id) + ' · ' + count + '</button>';
    }).join("");
    optionsRoot.querySelectorAll("[data-vote-option]").forEach(btn => {
      btn.addEventListener("click", () => {
        state.selectedVoteOption = btn.getAttribute("data-vote-option");
        renderVoteRound(payload);
      });
    });
    const roleOptions = round.role_options || {};
    roleRoot.innerHTML = Object.keys(ROLE_LABELS).map(role => {
      const selected = state.selectedRoleVotes[role] || "";
      const choices = Array.isArray(roleOptions[role]) && roleOptions[role].length ? roleOptions[role] : ["support", "foreground", "sparser"];
      return '<label class="preset-toggle">' + escapeHtml(ROLE_LABELS[role]) + ' <select data-role-vote="' + escapeHtml(role) + '"><option value="">auto</option>' + choices.map(choice => {
        const value = typeof choice === "object" ? choice.id : choice;
        const label = typeof choice === "object" ? (choice.label || choice.id) : choice;
        return '<option value="' + escapeHtml(value) + '" ' + (selected === value ? 'selected' : '') + '>' + escapeHtml(label) + '</option>';
      }).join("") + '</select></label>';
    }).join("");
    roleRoot.querySelectorAll("[data-role-vote]").forEach(select => {
      select.addEventListener("change", () => {
        const role = select.getAttribute("data-role-vote");
        if (select.value) state.selectedRoleVotes[role] = select.value;
        else delete state.selectedRoleVotes[role];
      });
    });
  }

  function refreshVoteRound() {
    return getJson(PATHS.apiVoteRound).then(renderVoteRound);
  }
  refreshVoteRound();
  setInterval(refreshVoteRound, 5000);

  bindClick("btn-submit-vote", () => {
    if (!state.selectedVoteOption) {
      setStatus($("vote-save-status"), "Pick a style first.", "error");
      return;
    }
    postJson(PATHS.apiVote, { option_id: state.selectedVoteOption, role_votes: state.selectedRoleVotes })
      .then(result => { renderVoteRound(result); setStatus($("vote-save-status"), "Vote recorded. It will apply at an upcoming boundary.", "ok"); })
      .catch(err => setStatus($("vote-save-status"), err.message, "error"));
  });

  bindClick("btn-submit-suggestion", () => {
    postJson(PATHS.apiSuggestions, { text: $("suggestion-box").value })
      .then(result => { $("suggestion-box").value = ""; setStatus($("suggestion-status"), "Suggestion " + result.suggestion.status + ": " + result.suggestion.reason, "ok"); })
      .catch(err => setStatus($("suggestion-status"), err.message, "error"));
  });

  if ($("drift")) $("drift").addEventListener("input", (e) => {
    $("drift-readout").textContent = e.target.value + " %";
  });

  /* ------------------------------------------------------------------
   * AUDIO — Web Audio API (spectrum + L/R analysers)
   * ----------------------------------------------------------------*/
  const audio = $("player");
  let audioCtx = null;
  let srcNode = null;
  let splitter = null;
  let analyserMix = null;
  let analyserL = null;
  let analyserR = null;
  let mixData = null;
  let lData = null;
  let rData = null;

  audio.volume = state.masterVolume;

  function ensureAudioGraph() {
    if (audioCtx) return;
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      srcNode = audioCtx.createMediaElementSource(audio);
      analyserMix = audioCtx.createAnalyser();
      analyserMix.fftSize = 256;
      analyserMix.smoothingTimeConstant = 0.78;
      mixData = new Uint8Array(analyserMix.frequencyBinCount);

      splitter = audioCtx.createChannelSplitter(2);
      analyserL = audioCtx.createAnalyser();
      analyserR = audioCtx.createAnalyser();
      analyserL.fftSize = 256; analyserL.smoothingTimeConstant = 0.6;
      analyserR.fftSize = 256; analyserR.smoothingTimeConstant = 0.6;
      lData = new Uint8Array(analyserL.frequencyBinCount);
      rData = new Uint8Array(analyserR.frequencyBinCount);

      srcNode.connect(analyserMix);
      srcNode.connect(splitter);
      splitter.connect(analyserL, 0);
      splitter.connect(analyserR, 1);
      srcNode.connect(audioCtx.destination);
    } catch (err) {
      console.warn("Web Audio graph unavailable:", err);
    }
  }

  function rmsFromBins(buf) {
    let sum = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = (buf[i] / 255) - 0.5;
      sum += v * v;
    }
    return Math.sqrt(sum / buf.length) * 2;  // 0..1
  }

  /* spectrum + meters render loop */
  const spectrumCanvas = $("spectrum");
  const sctx = spectrumCanvas.getContext("2d");
  function resizeCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const w = spectrumCanvas.clientWidth || 800;
    const h = spectrumCanvas.clientHeight || 100;
    if (spectrumCanvas.width !== Math.round(w * dpr) || spectrumCanvas.height !== Math.round(h * dpr)) {
      spectrumCanvas.width = Math.round(w * dpr);
      spectrumCanvas.height = Math.round(h * dpr);
      sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  }
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();

  function drawSpectrum() {
    const w = spectrumCanvas.clientWidth;
    const h = spectrumCanvas.clientHeight;
    sctx.clearRect(0, 0, w, h);
    if (!analyserMix) {
      // idle: faint baseline
      sctx.fillStyle = "rgba(94,234,212,0.18)";
      for (let i = 0; i < 64; i++) {
        const x = (i / 64) * w;
        const bw = (w / 64) - 2;
        sctx.fillRect(x, h - 4, bw, 3);
      }
      return;
    }
    analyserMix.getByteFrequencyData(mixData);
    const bars = 64;
    const binsPerBar = Math.max(1, Math.floor(mixData.length / bars));
    const grad = sctx.createLinearGradient(0, h, 0, 0);
    grad.addColorStop(0,   "#7c3aed");
    grad.addColorStop(0.3, "#a78bfa");
    grad.addColorStop(0.7, "#5eead4");
    grad.addColorStop(1,   "#ccfbf1");
    sctx.fillStyle = grad;
    for (let i = 0; i < bars; i++) {
      let sum = 0;
      for (let j = 0; j < binsPerBar; j++) sum += mixData[i * binsPerBar + j];
      const v = sum / binsPerBar / 255;
      const bh = clamp(v * h, 1, h);
      const x = (i / bars) * w;
      const bw = Math.max(2, (w / bars) - 2);
      sctx.fillRect(x, h - bh, bw, bh);
    }
  }

  function drawMeters() {
    if (analyserL && analyserR && !audio.paused) {
      analyserL.getByteFrequencyData(lData);
      analyserR.getByteFrequencyData(rData);
      const lv = clamp(rmsFromBins(lData) * 130, 0, 100);
      const rv = clamp(rmsFromBins(rData) * 130, 0, 100);
      $("meter-l").style.setProperty("--lvl", lv + "%");
      $("meter-r").style.setProperty("--lvl", rv + "%");
    } else {
      $("meter-l").style.setProperty("--lvl", "0%");
      $("meter-r").style.setProperty("--lvl", "0%");
    }
  }

  function rafLoop() {
    drawSpectrum();
    drawMeters();
    requestAnimationFrame(rafLoop);
  }
  requestAnimationFrame(rafLoop);

  /* ------------------------------------------------------------------
   * AUDIO SOURCE MANAGEMENT
   * ----------------------------------------------------------------*/
  function destroyHls() {
    if (state.hlsInstance) {
      try { state.hlsInstance.destroy(); } catch (_) { /* ignore */ }
      state.hlsInstance = null;
    }
  }

  function attachLiveStream() {
    if (!radioAllowsLive()) {
      return Promise.reject(new Error("Radio is offline outside the 5:00 AM–7:00 PM EST broadcast window."));
    }
    destroyHls();
    state.isLive = true;
    if (audio.canPlayType("application/vnd.apple.mpegurl")) {
      audio.src = PATHS.streamHls + "?v=" + Date.now();
      audio.load();
      return new Promise((resolve, reject) => {
        const t = setTimeout(() => { reject(new Error("Timed out buffering live audio.")); }, 20000);
        audio.addEventListener("canplay", () => { clearTimeout(t); resolve(); }, { once: true });
        audio.addEventListener("error", () => { clearTimeout(t); reject(new Error("Audio element rejected the live source.")); }, { once: true });
      });
    }
    if (!window.Hls || !window.Hls.isSupported()) {
      return Promise.reject(new Error("This browser cannot play HLS and hls.js is unavailable."));
    }
    return new Promise((resolve, reject) => {
      const hls = new window.Hls({ defaultAudioCodec: "mp4a.40.2", initialLiveManifestSize: 2 });
      const t = setTimeout(() => { reject(new Error("Timed out buffering HLS segments.")); }, 25000);
      hls.on(window.Hls.Events.FRAG_BUFFERED, () => { clearTimeout(t); resolve(); });
      hls.on(window.Hls.Events.ERROR, (_e, data) => {
        if (data.fatal) {
          clearTimeout(t);
          destroyHls();
          reject(new Error("HLS error: " + (data.details || "fatal")));
        }
      });
      hls.loadSource(PATHS.streamHls + "?v=" + Date.now());
      hls.attachMedia(audio);
      state.hlsInstance = hls;
    });
  }

  function playRecording(url, label) {
    destroyHls();
    state.isLive = false;
    audio.src = mediaUrl(url);
    audio.load();
    return audio.play().then(() => {
      state.audioStartedAt = Date.now();
      $("buffer-text").textContent = label || "Playing archived recording";
      $("buffer-dot").classList.remove("bad");
    });
  }

  /* ------------------------------------------------------------------
   * APPLY PROMPT + START LIVE
   * ----------------------------------------------------------------*/
  function waitForLiveReady(maxAttempts) {
    if (typeof maxAttempts !== "number") maxAttempts = 30;
    let n = 0;
    return new Promise((resolve, reject) => {
      function tick() {
        n++;
        getJson(PATHS.conductorStatus).then(c => {
          state.conductor = c;
          if (c && c.live_ready) return resolve(c);
          if (n >= maxAttempts) return reject(new Error("Live stream still prebuffering. Try again shortly."));
          setTimeout(tick, 2000);
        });
      }
      tick();
    });
  }

  bindClick("btn-apply", () => {
    if (!radioAllowsLive()) {
      setStatus($("apply-status"), "Radio is offline outside the 5:00 AM–7:00 PM EST broadcast window.", "error");
      return;
    }
    const btn = $("btn-apply");
    btn.disabled = true;
    setStatus($("apply-status"), "Applying prompt…", null);
    const payload = {
      prompt: $("prompt-box").value,
      psychosis_level: Number($("drift").value) / 100,
    };
    return postJson(PATHS.apiLiveControl, payload)
      .then(result => {
        renderLiveControl(result.live_control);
        ensureAudioGraph();
        if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
        setStatus($("apply-status"), "Prompt confirmed. Waiting for live buffer…", "ok");
        return Promise.all([refreshRadioStatus(), waitForLiveReady()]);
      })
      .then(() => attachLiveStream())
      .then(() => audio.play())
      .then(() => {
        state.audioStartedAt = Date.now();
        setStatus($("apply-status"), "Live audio playing.", "ok");
      })
      .catch(err => {
        setStatus($("apply-status"), err.message + " Trying archive fallback…", "error");
        return getJson(PATHS.apiFallback)
          .then(fallback => {
            if (fallback && fallback.recording) return playRecording(mediaUrl(fallback.recording), "Live stream unavailable. Playing latest archived recording.");
            throw new Error("Live stream unavailable and no archive exists yet. Stream initializing.");
          })
          .then(() => setStatus($("apply-status"), "Archive fallback playing.", "ok"))
          .catch(fallbackErr => setStatus($("apply-status"), fallbackErr.message, "error"));
      })
      .finally(() => { btn.disabled = false; });
  });

  bindClick("btn-archive", () => {
    ensureAudioGraph();
    if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    playRecording(state.latestArchiveRecording, "Manual fallback selected. Playing latest archived recording.")
      .catch(err => setStatus($("apply-status"), err.message, "error"));
  });

  /* ------------------------------------------------------------------
   * TRANSPORT
   * ----------------------------------------------------------------*/
  bindClick("t-play", () => {
    ensureAudioGraph();
    if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    if (audio.paused) {
      if (!audio.src) audio.src = state.latestArchiveRecording;
      audio.play().then(() => { state.audioStartedAt = state.audioStartedAt || Date.now(); });
    } else {
      audio.pause();
    }
  });
  audio.addEventListener("play",  () => { $("t-play").textContent = "⏸"; });
  audio.addEventListener("pause", () => { $("t-play").textContent = "▶"; });
  audio.addEventListener("ended", () => { $("t-play").textContent = "▶"; });

  bindClick("t-stop", () => {
    audio.pause();
    try { audio.currentTime = 0; } catch (_) { /* live HLS may reject */ }
    state.audioStartedAt = null;
  });
  bindClick("t-rew", () => {
    try { audio.currentTime = Math.max(0, audio.currentTime - 10); } catch (_) {}
  });
  bindClick("t-ff", () => {
    try { audio.currentTime = Math.min((audio.duration || 0) || audio.currentTime + 10, audio.currentTime + 10); } catch (_) {}
  });
  bindClick("t-skip-back", () => {
    try { audio.currentTime = Math.max(0, audio.currentTime - 30); } catch (_) {}
  });
  bindClick("t-skip-fwd", () => {
    try { audio.currentTime = audio.currentTime + 30; } catch (_) {}
  });

  bindClick("t-sync", (e) => {
    const cur = e.currentTarget.getAttribute("aria-pressed") === "true";
    e.currentTarget.setAttribute("aria-pressed", cur ? "false" : "true");
  });

  /* TAP TEMPO — last 4 taps in the past 3s → median interval → BPM */
  bindClick("t-tap", () => {
    const now = performance.now();
    state.tapTimes = state.tapTimes.filter(t => now - t < 3000);
    state.tapTimes.push(now);
    if (state.tapTimes.length >= 2) {
      const intervals = [];
      for (let i = 1; i < state.tapTimes.length; i++) intervals.push(state.tapTimes[i] - state.tapTimes[i - 1]);
      intervals.sort((a, b) => a - b);
      const median = intervals[Math.floor(intervals.length / 2)];
      const bpm = clamp(Math.round(60000 / median), 30, 240);
      $("tap-bpm").textContent = bpm + " bpm";
    } else {
      $("tap-bpm").textContent = "…";
    }
  });

  /* timer */
  setInterval(() => {
    const t = audio.currentTime || 0;
    $("audio-timer").textContent = fmtClock(t);
  }, 250);

  /* ------------------------------------------------------------------
   * MASTER KNOB — ns-resize drag, wheel, arrow keys → audio.volume
   * ----------------------------------------------------------------*/
  function setMaster(vol) {
    const v = clamp(vol, 0, 1);
    state.masterVolume = v;
    audio.volume = v;
    const knob = $("master-knob");
    const deg = -135 + v * 270;       // sweep -135° to +135°
    knob.style.setProperty("--rot", deg + "deg");
    knob.setAttribute("aria-valuenow", String(Math.round(v * 100)));
    $("master-level").textContent = fmtDb(v);
  }
  setMaster(state.masterVolume);

  (function bindKnob() {
    const knob = $("master-knob");
    let dragging = false;
    let startY = 0;
    let startVol = 0;

    function onMove(e) {
      if (!dragging) return;
      const y = (e.touches ? e.touches[0].clientY : e.clientY);
      const dy = startY - y;
      setMaster(startVol + dy / 200);   // 200px = full sweep
    }
    function onUp() {
      dragging = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onUp);
    }
    function onDown(e) {
      e.preventDefault();
      dragging = true;
      startY = (e.touches ? e.touches[0].clientY : e.clientY);
      startVol = state.masterVolume;
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
      window.addEventListener("touchmove", onMove, { passive: false });
      window.addEventListener("touchend", onUp);
    }
    knob.addEventListener("mousedown", onDown);
    knob.addEventListener("touchstart", onDown, { passive: false });
    knob.addEventListener("wheel", (e) => {
      e.preventDefault();
      setMaster(state.masterVolume - Math.sign(e.deltaY) * 0.04);
    }, { passive: false });
    knob.addEventListener("keydown", (e) => {
      if (e.key === "ArrowUp"   || e.key === "ArrowRight") { e.preventDefault(); setMaster(state.masterVolume + 0.05); }
      if (e.key === "ArrowDown" || e.key === "ArrowLeft")  { e.preventDefault(); setMaster(state.masterVolume - 0.05); }
      if (e.key === "Home") { e.preventDefault(); setMaster(0); }
      if (e.key === "End")  { e.preventDefault(); setMaster(1); }
    });
  })();

  /* ------------------------------------------------------------------
   * STATE.JSON + ROLE-BUNDLES — BPM/KEY + per-role stats every 5s
   * ----------------------------------------------------------------*/
  const ROLE_PARAMS = {
    percussion: { key: "Swing",     fn: derSwing },
    bass:       { key: "Groove",    fn: derGroove },
    piano:      { key: "Dynamics",  fn: derDynamics },
    lead:       { key: "Intensity", fn: derIntensity },
    texture:    { key: "Density",   fn: derDensity },
  };
  const STATUS_VERB = {
    percussion: ["active",    "listening"],
    bass:       ["listening", "active"],
    piano:      ["active",    "listening"],
    lead:       ["mutating",  "listening"],
    texture:    ["queued",    "listening"],
  };
  const ROLE_LED = {
    percussion: "led-green",
    bass:       "led-green",
    piano:      "led-teal",
    lead:       "led-violet",
    texture:    "led-amber",
  };

  function eventsForRole(roleBundles, role) {
    if (!roleBundles || !Array.isArray(roleBundles.bundles)) return [];
    const b = roleBundles.bundles.find(x => x.role === role);
    return (b && Array.isArray(b.events)) ? b.events : [];
  }

  function derSwing(events, sectionBars) {
    if (!events.length) return 0;
    // Stdev of beat fractional offset from grid (0, 0.5)
    const offsets = events.map(e => {
      const f = (e.beat % 1);
      return Math.min(f, Math.abs(f - 0.5)) * 2;  // 0..1
    });
    const mean = offsets.reduce((a, b) => a + b, 0) / offsets.length;
    const variance = offsets.reduce((a, b) => a + (b - mean) * (b - mean), 0) / offsets.length;
    return clamp(Math.round(Math.sqrt(variance) * 360), 0, 100);
  }
  function derGroove(events, sectionBars) {
    const target = (sectionBars || 4) * 4;        // 4 events per bar = baseline
    return clamp(Math.round((events.length / target) * 100), 0, 100);
  }
  function derDynamics(events) {
    if (!events.length) return 0;
    const vels = events.map(e => Number(e.velocity) || 0);
    const range = Math.max(...vels) - Math.min(...vels);
    return clamp(Math.round((range / 127) * 100), 0, 100);
  }
  function derIntensity(events) {
    if (!events.length) return 0;
    const vels = events.map(e => Number(e.velocity) || 0);
    return clamp(Math.round((Math.max(...vels) / 127) * 100), 0, 100);
  }
  function derDensity(events, sectionBars) {
    const target = (sectionBars || 4) * 2;        // texture is sparse
    return clamp(Math.round((events.length / target) * 100), 0, 100);
  }

  function eventsHistogram(events, sectionBars) {
    const bins = 8;
    const counts = new Array(bins).fill(0);
    if (!events.length) return counts;
    const beatsTotal = (sectionBars || 4) * 4;
    events.forEach(e => {
      const beat = ((Number(e.bar) - 1) || 0) * 4 + ((Number(e.beat) - 1) || 0);
      const idx = clamp(Math.floor((beat / beatsTotal) * bins), 0, bins - 1);
      counts[idx]++;
    });
    return counts;
  }

  function renderBand() {
    const stateJson = state.stateJson;
    const bundles = state.roleBundles;
    const sectionBars = (bundles && bundles.conductor_state && bundles.conductor_state.section_bars) || 4;
    if (stateJson) {
      $("meta-bpm").textContent = stateJson.tempo_bpm ?? "—";
      $("meta-key").textContent = stateJson.key || "—";
    }

    Object.keys(ROLE_PARAMS).forEach(role => {
      const card = document.querySelector('[data-role="' + role + '"]');
      if (!card) return;
      const events = eventsForRole(bundles, role);
      const param = ROLE_PARAMS[role];
      const value = param.fn(events, sectionBars);
      const status = (stateJson && stateJson.status && stateJson.status[role]) || "—";

      // Status verb mapping: prefer state.status; else default per-role mutating verb
      const verbs = STATUS_VERB[role];
      let verbText = status;
      if (status === "playing") verbText = verbs[0];
      if (status === "waiting") verbText = verbs[1];

      card.querySelector("[data-role-status]").textContent = verbText;
      card.querySelector("[data-param-key]").textContent = param.key;
      card.querySelector("[data-param-val]").textContent = value + "%";
      const knob = card.querySelector("[data-role-knob]");
      knob.style.setProperty("--rot", (-45 + (value / 100) * 90) + "deg");

      const led = card.querySelector("[data-role-led]");
      const ledClass = ROLE_LED[role];
      led.className = "led " + (events.length ? ledClass : "led-gray");

      const bars = card.querySelectorAll("[data-role-bars] span");
      const hist = eventsHistogram(events, sectionBars);
      const peak = Math.max(1, ...hist);
      bars.forEach((b, i) => {
        const pct = clamp((hist[i] / peak) * 100, 6, 100);
        b.style.height = pct + "%";
      });
    });
  }

  function refreshState() {
    return Promise.all([getJson(PATHS.state), getJson(PATHS.roleBundles)])
      .then(([s, b]) => { state.stateJson = s; state.roleBundles = b; renderBand(); });
  }
  refreshState();
  setInterval(refreshState, 5000);

  /* ------------------------------------------------------------------
   * CURRENT SESSION — every 10s
   * ----------------------------------------------------------------*/
  function renderCurrentSession(s) {
    const list = $("current-session-list");
    const status = $("current-session-status");
    if (!s) {
      list.innerHTML = '<p class="form-label">No active current-stream session yet.</p>';
      return;
    }
    const minutes = Math.max(1, Math.round((s.duration_seconds || 0) / 60));
    status.textContent = (s.title || "Current session") + " · ~" + minutes + " min captured · updates every " + Math.max(1, Math.round((s.chunk_seconds || 0) / 60)) + " min";
    if (!s.recording) {
      list.innerHTML = '<p class="form-label">No saved current-stream recording yet. Keep the conductor running; the first chunk closes shortly.</p>';
      return;
    }
    list.innerHTML =
      '<article class="session-chunk">' +
        '<h3>Current stream recording</h3>' +
        '<p>Updated ' + escapeHtml(s.updated_at || "") + ' · ' + (s.chunks ? s.chunks.length : 0) + ' chunks</p>' +
        '<audio controls preload="metadata" src="' + escapeHtml(mediaUrl(s.recording)) + '?v=' + encodeURIComponent(s.updated_at || "") + '"></audio>' +
      '</article>';
  }
  function refreshCurrentSession() {
    return getJson(PATHS.currentSession).then(renderCurrentSession);
  }
  refreshCurrentSession();
  setInterval(refreshCurrentSession, 10000);

  /* ------------------------------------------------------------------
   * ARCHIVE
   * ----------------------------------------------------------------*/
  getJson(PATHS.archiveIndex).then(runs => {
    const list = $("archive-list");
    if (!Array.isArray(runs) || !runs.length) {
      list.innerHTML = '<p class="form-label">No archived runs yet. Run the generator once to create one.</p>';
      return;
    }
    state.latestArchiveRecording = mediaUrl(runs[0].recording);
    list.innerHTML = runs.map(run =>
      '<article class="archive-item">' +
        '<h3>' + escapeHtml(run.title || run.id) + '</h3>' +
        '<p>' + (run.tempo_bpm || "—") + ' bpm · ' + escapeHtml(run.key || "—") + ' · ' + (run.roles || []).map(escapeHtml).join(", ") + '</p>' +
        '<audio controls preload="metadata" src="' + escapeHtml(mediaUrl(run.recording)) + '"></audio>' +
        '<p><a href="' + escapeHtml(mediaUrl(run.midi) || "#") + '">MIDI</a> · <a href="' + escapeHtml(mediaUrl(run.wav) || "#") + '">WAV</a> · <a href="' + escapeHtml(mediaUrl(run.state) || "#") + '">state.json</a></p>' +
      '</article>'
    ).join("");
  });

  /* ------------------------------------------------------------------
   * ADMIN + COLLAPSE SIGNALS
   * ----------------------------------------------------------------*/
  function refreshAdminSuggestions() {
    return getJson(PATHS.apiAdminSuggestions).then(result => {
      const root = $("admin-suggestions");
      if (!root || !result || !Array.isArray(result.suggestions)) return;
      root.innerHTML = result.suggestions.slice(0, 12).map(item =>
        '<article class="session-chunk"><h3>' + escapeHtml(item.status || "pending") + ' suggestion</h3><p>' + escapeHtml(item.text || "") + '</p><p>' + escapeHtml(item.reason || "") + '</p><div class="form-actions"><button class="btn btn-secondary" data-suggestion-action="approved" data-suggestion-id="' + escapeHtml(item.id || "") + '" type="button">Approve</button><button class="btn btn-secondary" data-suggestion-action="rejected" data-suggestion-id="' + escapeHtml(item.id || "") + '" type="button">Reject</button><button class="btn btn-secondary" data-suggestion-promote="' + escapeHtml(item.id || "") + '" type="button">Promote</button></div></article>'
      ).join("") || '<p class="form-label">No suggestions yet.</p>';
      root.querySelectorAll("[data-suggestion-action]").forEach(btn => {
        btn.addEventListener("click", () => {
          postJson(PATHS.apiAdminSuggestions, { id: btn.getAttribute("data-suggestion-id"), action: btn.getAttribute("data-suggestion-action") })
            .then(refreshAdminSuggestions)
            .catch(err => setStatus($("admin-status"), err.message, "error"));
        });
      });
      root.querySelectorAll("[data-suggestion-promote]").forEach(btn => {
        btn.addEventListener("click", () => {
          postJson(PATHS.apiAdminPromoteSuggestion, { id: btn.getAttribute("data-suggestion-promote") })
            .then(result => { setStatus($("admin-status"), "Promoted " + result.option.label + " into the current menu.", "ok"); return refreshVoteRound(); })
            .catch(err => setStatus($("admin-status"), err.message, "error"));
        });
      });
    });
  }

  function refreshCollapseMetrics() {
    return getJson(PATHS.apiCollapse).then(result => {
      const root = $("collapse-metrics");
      if (!root || !result || result.ok === false) return;
      root.innerHTML = '<article class="session-chunk"><h3>Collapse signals</h3><p>Votes: ' + escapeHtml(result.vote_frequency) + ' · Suggestions: ' + escapeHtml(result.suggestion_rate) + ' · Inactive: ' + escapeHtml(result.inactivity_seconds) + 's · Convergence streak: ' + escapeHtml(result.convergence_streak) + '</p><p>' + escapeHtml(result.interpretation || '') + '</p></article>';
    });
  }

  function setAdminUnlocked(unlocked) {
    const privatePanel = $("admin-private");
    if (privatePanel) privatePanel.hidden = !unlocked;
  }

  function refreshAdminSession() {
    if (!IS_ADMIN_ROUTE) return Promise.resolve(false);
    return getJson(PATHS.apiAdminSession).then(result => {
      const unlocked = !!(result && result.admin);
      setAdminUnlocked(unlocked);
      if (unlocked) {
        setStatus($("admin-status"), "Admin session active.", "ok");
        return Promise.all([refreshAdminSuggestions(), refreshCollapseMetrics()]).then(() => true);
      }
      setStatus($("admin-status"), "Enter the admin value to unlock controls.", null);
      return false;
    });
  }

  bindClick("btn-admin-login", () => {
    postJson(PATHS.apiAdminLogin, { password: $("admin-password").value })
      .then(() => { $("admin-password").value = ""; setAdminUnlocked(true); setStatus($("admin-status"), "Admin session active.", "ok"); return Promise.all([refreshAdminSuggestions(), refreshCollapseMetrics()]); })
      .catch(err => setStatus($("admin-status"), err.message, "error"));
  });
  bindClick("btn-admin-logout", () => {
    postJson(PATHS.apiAdminLogout, {})
      .then(() => { setAdminUnlocked(false); setStatus($("admin-status"), "Logged out.", "ok"); })
      .catch(err => setStatus($("admin-status"), err.message, "error"));
  });
  bindClick("btn-admin-save-round", () => {
    let options;
    try { options = JSON.parse($("admin-round-json").value); }
    catch (err) { setStatus($("admin-round-status"), "Vote round JSON is invalid.", "error"); return; }
    postJson(PATHS.apiAdminVoteRound, { options: options })
      .then(() => { setStatus($("admin-round-status"), "Vote round saved.", "ok"); return refreshVoteRound(); })
      .catch(err => setStatus($("admin-round-status"), err.message, "error"));
  });
  bindClick("btn-admin-save-override", () => {
    let payload;
    try { payload = JSON.parse($("admin-override-json").value); }
    catch (err) { setStatus($("admin-override-status"), "Override JSON is invalid.", "error"); return; }
    postJson(PATHS.apiAdminOverride, payload)
      .then(() => setStatus($("admin-override-status"), "Override saved.", "ok"))
      .catch(err => setStatus($("admin-override-status"), err.message, "error"));
  });
  bindClick("btn-admin-clear-override", () => {
    postJson(PATHS.apiAdminOverride, { enabled: false })
      .then(() => setStatus($("admin-override-status"), "Override cleared.", "ok"))
      .catch(err => setStatus($("admin-override-status"), err.message, "error"));
  });
  bindClick("btn-admin-force-fallback", () => {
    getJson(PATHS.apiAdminFallback)
      .then(result => postJson(PATHS.apiAdminFallback, { enabled: !(result.fallback && result.fallback.enabled) }))
      .then(result => setStatus($("admin-override-status"), "Archive fallback " + (result.fallback.enabled ? "enabled" : "disabled") + ".", "ok"))
      .catch(err => setStatus($("admin-override-status"), err.message, "error"));
  });
  refreshAdminSession();

  /* ------------------------------------------------------------------
   * PRESET MODES
   * ----------------------------------------------------------------*/
  const ROLE_LABELS = {
    percussion: "Percussion",
    bass: "Bass",
    piano: "Piano",
    lead: "Lead",
    texture: "Texture",
  };

  function clonePresetModes(presetModes) {
    return JSON.parse(JSON.stringify(presetModes));
  }

  function activePreset(presetModes) {
    if (!presetModes || !presetModes.profiles) return null;
    return presetModes.profiles[presetModes.active_profile] || presetModes.profiles.none || null;
  }

  function presetLabelFromId(id) {
    return String(id || "Custom")
      .split(/[-_\s]+/)
      .filter(Boolean)
      .map(part => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  function effectiveRolePrompt(basePrompt, presetModes, role) {
    const active = activePreset(presetModes);
    const activeRoles = (presetModes && presetModes.active_roles) || {};
    if (!active || !active.roles || activeRoles[role] === false) return basePrompt;
    const overlay = active.roles[role];
    if (!overlay) return basePrompt;
    return basePrompt + "\n\nPreset mode overlay (" + (active.label || presetModes.active_profile) + "): " + overlay;
  }

  function stripPresetOverlay(prompt) {
    return String(prompt || "").split("\n\nPreset mode overlay (")[0].trim();
  }

  function renderEffectivePersonaPrompts(presetModes) {
    if (!state.personas) return;
    document.querySelectorAll("#persona-list textarea[data-role]").forEach(t => {
      const role = t.getAttribute("data-role");
      const persona = state.personas[role];
      if (!persona) return;
      const basePrompt = t.getAttribute("data-base-prompt") || persona.prompt || "";
      t.value = effectiveRolePrompt(basePrompt, presetModes || state.presetModes, role);
    });
  }

  function renderPresetModes(presetModes) {
    if (!presetModes || !presetModes.profiles) return;
    state.presetModes = presetModes;
    const grid = $("preset-grid");
    const toggles = $("preset-role-toggles");
    const active = activePreset(presetModes);
    const activeLabel = active ? active.label : "None";
    $("preset-active-label").textContent = "Active: " + activeLabel;
    $("preset-description").textContent = active && active.description
      ? active.description
      : "Preset overlays sit on top of your base personas without overwriting them.";

    const ids = Object.keys(presetModes.profiles).filter(id => id !== "none");
    grid.innerHTML = ids.map(id => {
      const p = presetModes.profiles[id];
      return '<button class="preset-btn" type="button" data-preset-id="' + escapeHtml(id) + '" aria-pressed="' + String(presetModes.active_profile === id) + '">' + escapeHtml(p.label || id) + '</button>';
    }).join("");

    const activeRoles = presetModes.active_roles || {};
    toggles.innerHTML = Object.keys(ROLE_LABELS).map(role =>
      '<label class="preset-toggle"><input type="checkbox" data-preset-role="' + escapeHtml(role) + '" ' + (activeRoles[role] !== false ? 'checked' : '') + '> ' + escapeHtml(ROLE_LABELS[role]) + '</label>'
    ).join("");

    grid.querySelectorAll("[data-preset-id]").forEach(btn => {
      btn.addEventListener("click", () => applyPreset(btn.getAttribute("data-preset-id")));
    });
    toggles.querySelectorAll("[data-preset-role]").forEach(input => {
      input.addEventListener("change", () => updatePresetRole(input.getAttribute("data-preset-role"), input.checked));
    });
    renderEffectivePersonaPrompts(presetModes);
    var activeProfile = presetModes.profiles[presetModes.active_profile] || {};
    renderItunesPlayer({
      prompt: $("prompt-box").value || activeProfile.live_prompt || "",
      psychosis_level: Number($("drift").value) / 100,
      tempo_bpm: activeProfile.tempo_bpm,
      key: activeProfile.key,
    });
  }

  function savePresetModes(next, statusMessage) {
    setStatus($("preset-status"), statusMessage || "Saving preset…", null);
    return postJson(PATHS.apiPresetModes, next)
      .then(result => {
        const presetModes = result.preset_modes || result;
        renderPresetModes(presetModes);
        setStatus($("preset-status"), "Preset saved.", "ok");
        return presetModes;
      })
      .catch(err => {
        // Most common cause during development: the control server is still the
        // old process and needs a restart. Keep the UI responsive locally, but
        // be explicit that the conductor will not see the overlay until restart.
        renderPresetModes(next);
        if (/Unknown API route|404|preset/i.test(err.message)) {
          setStatus($("preset-status"), "Preset shown locally, but /api/preset-modes is missing. Restart scripts/control_server.py.", "error");
          return next;
        }
        setStatus($("preset-status"), err.message, "error");
        throw err;
      });
  }

  function liveControlForPreset(profile) {
    return {
      prompt: profile.live_prompt || "",
      psychosis_level: Number(profile.psychosis_level || 0.25),
      tempo_bpm: profile.tempo_bpm,
      key: profile.key,
    };
  }

  function applyPreset(profileId) {
    if (!state.presetModes || !state.presetModes.profiles || !state.presetModes.profiles[profileId]) return;
    const next = clonePresetModes(state.presetModes);
    next.active_profile = profileId;
    const profile = next.profiles[profileId];
    renderPresetModes(next);
    savePresetModes(next, "Applying preset…")
      .then(() => postJson(PATHS.apiLiveControl, liveControlForPreset(profile)))
      .then(result => {
        renderLiveControl(result.live_control);
        setStatus($("preset-status"), "Preset active. Next section will use " + (profile.label || profileId) + ".", "ok");
      })
      .catch(() => {});
  }

  function updatePresetRole(role, enabled) {
    if (!role || !state.presetModes) return;
    const next = clonePresetModes(state.presetModes);
    next.active_roles = next.active_roles || {};
    next.active_roles[role] = !!enabled;
    renderPresetModes(next);
    savePresetModes(next, "Saving role overlay…").catch(() => {});
  }

  getJson(PATHS.apiPresetModes)
    .then(presetModes => {
      if (presetModes && presetModes.ok) delete presetModes.ok;
      return presetModes || getJson(PATHS.presetModes);
    })
    .then(renderPresetModes);

  /* ------------------------------------------------------------------
   * PERSONAS
   * ----------------------------------------------------------------*/
  getJson(PATHS.personas).then(personas => {
    if (!personas) return;
    state.personas = personas;
    const list = $("persona-list");
    list.innerHTML = Object.entries(personas).map(([role, p]) =>
      '<article class="persona-item">' +
        '<h3>' + escapeHtml(p.label) + '</h3>' +
        '<p>' + escapeHtml(p.purpose) + '</p>' +
        '<details><summary>Edit prompt</summary>' +
        '<textarea data-role="' + escapeHtml(role) + '" data-base-prompt="' + escapeHtml(p.prompt) + '" aria-label="' + escapeHtml(p.label) + ' prompt">' + escapeHtml(effectiveRolePrompt(p.prompt, state.presetModes, role)) + '</textarea>' +
        '</details>' +
      '</article>'
    ).join("");
    renderEffectivePersonaPrompts(state.presetModes);
  });

  bindClick("btn-save-personas", () => {
    const next = Object.assign({}, state.personas);
    document.querySelectorAll("#persona-list textarea[data-role]").forEach(t => {
      const role = t.getAttribute("data-role");
      const basePrompt = stripPresetOverlay(t.value);
      next[role] = Object.assign({}, next[role], { prompt: basePrompt });
      t.setAttribute("data-base-prompt", basePrompt);
    });
    setStatus($("personas-status"), "Saving…", null);
    postJson(PATHS.apiPersonas, next)
      .then(r => { state.personas = r.personas; setStatus($("personas-status"), "Saved.", "ok"); })
      .catch(err => setStatus($("personas-status"), err.message, "error"));
  });

  /* ------------------------------------------------------------------
   * Left rail nav — scroll to panel
   * ----------------------------------------------------------------*/
  document.querySelectorAll(".icon-btn[data-scroll]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".icon-btn[data-scroll]").forEach(b => b.removeAttribute("aria-current"));
      btn.setAttribute("aria-current", "true");
      const target = btn.getAttribute("data-scroll");
      const map = { llm: "panel-llm", audio: "panel-audio", personas: "panel-personas", settings: "panel-settings", about: "panel-about" };
      const node = $(map[target]);
      if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

})();
