(() => {
  "use strict";

  const conversation = document.getElementById("conversation");
  const emptyState = document.getElementById("empty-state");
  const householdSelect = document.getElementById("household-select");
  const chips = document.getElementById("whatif-chips");
  const composer = document.getElementById("composer");
  const messageInput = document.getElementById("message-input");

  let sessionId = null;
  let lastEstimate = null; // for before/after rendering on chip use
  let currentView = "ask";

  const EVIDENCE_LABELS = {
    source_data: "Source data",
    assumption: "Assumption",
    model_estimate: "Model estimate",
    not_available: "Not available",
  };

  // Simple hand-drawn outline icons, styled in CSS as a colored circle with
  // a white stroke glyph — echoes the AEP site's four quick-link icons.
  const ICON_PATHS = {
    warning: '<polygon points="12,3 2,20 22,20"/><line x1="12" y1="9" x2="12" y2="15"/><line x1="12" y1="17" x2="12" y2="17.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><line x1="12" y1="8" x2="12" y2="8.01"/>',
    check: '<circle cx="12" cy="12" r="9"/><polyline points="8,12 11,15 16,9"/>',
    clock: '<circle cx="12" cy="12" r="9"/><polyline points="12,7 12,12 16,14"/>',
    bell: '<path d="M6 10a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    shield: '<path d="M12 3 4 6v6c0 5 4 8 8 9 4-1 8-4 8-9V6l-8-3z"/>',
    checklist: '<rect x="4" y="4" width="16" height="16" rx="2"/><polyline points="8,12 10,14 15,9"/>',
    list: '<line x1="9" y1="6" x2="20" y2="6"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="18" x2="20" y2="18"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  };

  function iconCircle(kind, color, small) {
    const span = document.createElement("span");
    span.className = "icon-circle" + (small ? " icon-circle-sm" : "");
    span.style.background = color;
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = `<svg viewBox="0 0 24 24">${ICON_PATHS[kind]}</svg>`;
    return span;
  }

  const RISK_ICON = { Low: "check", Moderate: "info", High: "warning" };
  const RISK_COLOR_VAR = { Low: "--color-risk-low", Moderate: "--color-risk-moderate", High: "--color-risk-high" };

  function applyStoredTheme() {
    try {
      const stored = localStorage.getItem("wattsnext-theme");
      if (stored) document.documentElement.setAttribute("data-theme", stored);
    } catch (_) { /* private browsing or blocked storage */ }
  }

  function setTheme(value) {
    if (value === "system") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", value);
    }
    try { localStorage.setItem("wattsnext-theme", value); } catch (_) { /* ignore */ }
  }

  async function api(path, options) {
    const resp = await fetch(path, options);
    const body = await resp.json().catch(() => ({}));
    return { ok: resp.ok, status: resp.status, body };
  }

  async function loadHouseholds() {
    const { body } = await api("/api/households");
    const byCity = {};
    for (const h of body.households) {
      (byCity[h.city] = byCity[h.city] || []).push(h);
    }
    householdSelect.innerHTML = "";
    for (const city of Object.keys(byCity).sort()) {
      const group = document.createElement("optgroup");
      group.label = city;
      for (const h of byCity[city]) {
        const opt = document.createElement("option");
        opt.value = h.household_id;
        opt.textContent = h.display_name;
        group.appendChild(opt);
      }
      householdSelect.appendChild(group);
    }
  }

  async function startSession(householdId) {
    const { body } = await api("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ household_id: householdId }),
    });
    sessionId = body.session_id;
    lastEstimate = null;
    conversation.innerHTML = "";
    conversation.appendChild(emptyState);
    emptyState.hidden = false;
    chips.hidden = false;
    if (currentView === "dashboard") loadDashboard();
  }

  function evidenceTag(tag, labelOverride) {
    if (!tag) return "";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "evidence-tag";
    btn.textContent = labelOverride || EVIDENCE_LABELS[tag.evidence] || tag.evidence;
    btn.addEventListener("click", () => openEvidenceDialog(tag));
    return btn;
  }

  function openEvidenceDialog(tag) {
    document.getElementById("evidence-kind").textContent = EVIDENCE_LABELS[tag.evidence] || tag.evidence;
    document.getElementById("evidence-note").textContent = tag.note || "No additional detail for this value.";
    document.getElementById("evidence-dialog").showModal();
  }

  function appendChild(parent, el) { if (el) parent.appendChild(el); }

  function riskCard(risk) {
    const card = document.createElement("div");
    card.className = "card";
    if (risk.fallback && risk.fallback.fallback) {
      card.textContent = "We can't give a reliable estimate for this location. " + risk.fallback.reason;
      return card;
    }
    const chipRow = document.createElement("div");
    const chip = document.createElement("span");
    chip.className = "risk-chip risk-" + risk.risk_band.value;
    const band = risk.risk_band.value;
    chip.appendChild(iconCircle(RISK_ICON[band] || "info", `var(${RISK_COLOR_VAR[band] || "--color-risk-moderate"})`, true));
    chip.appendChild(document.createTextNode(band + " risk"));
    chipRow.appendChild(chip);
    appendChild(chipRow, evidenceTag(risk.risk_band));
    const conf = document.createElement("span");
    conf.className = "confidence-label";
    conf.textContent = risk.confidence.value + " confidence";
    chipRow.appendChild(conf);
    appendChild(chipRow, evidenceTag(risk.confidence));
    card.appendChild(chipRow);

    const reason = document.createElement("p");
    reason.textContent = risk.risk_reason;
    card.appendChild(reason);
    return card;
  }

  function rangeBar(low, high, maxScale) {
    const wrap = document.createElement("div");
    const label = document.createElement("div");
    label.className = "range-bar-label";
    label.textContent = "Model estimate — not confirmed by the utility (scenario range, not a confidence interval)";
    wrap.appendChild(label);
    const track = document.createElement("div");
    track.className = "range-bar-track";
    const fill = document.createElement("div");
    fill.className = "range-bar-fill";
    const leftPct = Math.min(100, (low / maxScale) * 100);
    const widthPct = Math.max(2, Math.min(100 - leftPct, ((high - low) / maxScale) * 100));
    fill.style.left = leftPct + "%";
    fill.style.width = widthPct + "%";
    track.appendChild(fill);
    wrap.appendChild(track);
    const values = document.createElement("div");
    values.className = "range-bar-values";
    values.innerHTML = `<span>${low.toFixed(1)} h</span><span>${high.toFixed(1)} h</span>`;
    wrap.appendChild(values);
    return wrap;
  }

  function laneHeading(text, iconKind, iconColor) {
    const h4 = document.createElement("h4");
    h4.className = "section-title";
    h4.appendChild(iconCircle(iconKind, iconColor, true));
    h4.appendChild(document.createTextNode(text));
    return h4;
  }

  function threeLaneCard(restoration, prep) {
    const card = document.createElement("div");
    card.className = "card lanes";

    const estimateLane = document.createElement("div");
    estimateLane.className = "lane";
    estimateLane.appendChild(laneHeading("Estimate", "clock", "var(--color-icon-blue)"));
    if (restoration && !restoration.fallback.fallback) {
      if (restoration.reference_effort_hours.value === 0) {
        const p = document.createElement("p");
        p.textContent = "Power should be back on per this simulation.";
        estimateLane.appendChild(p);
      } else {
        estimateLane.appendChild(rangeBar(restoration.low_hours.value, restoration.high_hours.value, 24));
        const tagRow = document.createElement("div");
        appendChild(tagRow, evidenceTag(restoration.low_hours, "low"));
        appendChild(tagRow, evidenceTag(restoration.high_hours, "high"));
        estimateLane.appendChild(tagRow);
      }
    } else {
      const p = document.createElement("p");
      p.className = "empty-lane";
      p.textContent = "No estimate available.";
      estimateLane.appendChild(p);
    }
    card.appendChild(estimateLane);

    const confirmedLane = document.createElement("div");
    confirmedLane.className = "lane";
    confirmedLane.appendChild(laneHeading("Confirmed by utility", "shield", "var(--color-icon-teal)"));
    const confirmedEmpty = document.createElement("p");
    confirmedEmpty.className = "empty-lane";
    confirmedEmpty.textContent = "Nothing is confirmed by the utility in this prototype.";
    confirmedLane.appendChild(confirmedEmpty);
    card.appendChild(confirmedLane);

    const actionsLane = document.createElement("div");
    actionsLane.className = "lane";
    actionsLane.appendChild(laneHeading("What you can do", "checklist", "var(--color-icon-green)"));
    const actions = (prep && prep.actions) || [];
    if (actions.length) {
      const ul = document.createElement("ul");
      for (const a of actions) {
        const li = document.createElement("li");
        li.textContent = a;
        ul.appendChild(li);
      }
      actionsLane.appendChild(ul);
    } else {
      const p = document.createElement("p");
      p.className = "empty-lane";
      p.textContent = "Ask “What should I do to prepare?” for tailored guidance.";
      actionsLane.appendChild(p);
    }
    card.appendChild(actionsLane);

    return card;
  }

  function alertsCard(alerts) {
    const card = document.createElement("div");
    card.className = "card";
    if (alerts.fallback && alerts.fallback.fallback) {
      card.textContent = alerts.fallback.reason;
      return card;
    }
    card.appendChild(laneHeading("Alerts", "bell", "var(--color-icon-orange)"));
    const header = document.createElement("p");
    header.innerHTML = alerts.eligible
      ? `<strong>Eligible for alerts</strong> via ${alerts.channel}.`
      : `<strong>Not opted in to alerts.</strong>`;
    card.appendChild(header);

    if (alerts.escalation_triggers && alerts.escalation_triggers.length) {
      const triggersTitle = document.createElement("p");
      triggersTitle.innerHTML = "<strong>Escalation triggers</strong>";
      card.appendChild(triggersTitle);
      const ul = document.createElement("ul");
      for (const t of alerts.escalation_triggers) {
        const li = document.createElement("li");
        li.textContent = `${t.trigger} → ${t.action}`;
        ul.appendChild(li);
      }
      card.appendChild(ul);
    }

    for (const preview of alerts.message_previews || []) {
      const meta = document.createElement("div");
      meta.className = "sms-meta";
      meta.textContent = `${preview.channel} • ${preview.timing}`;
      card.appendChild(meta);
      const bubble = document.createElement("div");
      bubble.className = "sms-bubble";
      bubble.textContent = preview.message;
      card.appendChild(bubble);
    }
    return card;
  }

  function cardMessage(card) {
    const message = document.createElement("div");
    message.className = "message assistant structured-message";
    message.appendChild(card);
    conversation.appendChild(message);
    return message;
  }

  function estimateMessage(restoration) {
    const card = document.createElement("div");
    card.className = "card";
    card.appendChild(laneHeading("Estimate", "clock", "var(--color-icon-blue)"));
    if (!restoration || restoration.fallback.fallback) {
      const p = document.createElement("p"); p.className = "empty-lane"; p.textContent = "No reliable estimate is available for this location."; card.appendChild(p);
    } else if (restoration.reference_effort_hours.value === 0) {
      const p = document.createElement("p"); p.textContent = "Power should be back on per this simulation."; card.appendChild(p);
    } else {
      card.appendChild(rangeBar(restoration.low_hours.value, restoration.high_hours.value, 24));
      const tags = document.createElement("div"); appendChild(tags, evidenceTag(restoration.low_hours, "low")); appendChild(tags, evidenceTag(restoration.high_hours, "high")); card.appendChild(tags);
    }
    return card;
  }

  function confirmedMessage(restoration) {
    const card = document.createElement("div"); card.className = "card";
    card.appendChild(laneHeading("Confirmed by utility", "shield", "var(--color-icon-teal)"));
    const p = document.createElement("p"); p.className = "empty-lane"; p.textContent = "Nothing is confirmed by the utility in this prototype."; card.appendChild(p);
    return card;
  }

  function actionsMessage(prep) {
    const card = document.createElement("div"); card.className = "card";
    card.appendChild(laneHeading("What you can do", "checklist", "var(--color-icon-green)"));
    const actions = (prep && prep.actions) || [];
    const ul = document.createElement("ul"); actions.forEach(a => { const li = document.createElement("li"); li.textContent = a; ul.appendChild(li); });
    card.appendChild(ul); return card;
  }

  function renderCards(cards) {
    if (cards.risk) cardMessage(riskCard(cards.risk));
    if (cards.restoration) cardMessage(estimateMessage(cards.restoration));
    if (cards.restoration || cards.prep) cardMessage(confirmedMessage(cards.restoration));
    if (cards.prep) cardMessage(actionsMessage(cards.prep));
    if (cards.alerts) cardMessage(alertsCard(cards.alerts));
  }

  function addMessage(role, text, offline, cards) {
    emptyState.hidden = true;
    const msg = document.createElement("div");
    msg.className = "message " + role;
    if (offline) {
      const banner = document.createElement("div");
      banner.className = "offline-banner";
      banner.textContent = "Offline mode — generated from rules, not AI.";
      msg.appendChild(banner);
    }
    const p = document.createElement("p");
    p.style.margin = "0";
    p.textContent = text;
    msg.appendChild(p);
    if (cards) renderCards(cards);
    conversation.appendChild(msg);
    conversation.scrollTop = conversation.scrollHeight;
    return msg;
  }

  function showTyping() {
    const el = document.createElement("div");
    el.className = "typing-indicator";
    el.id = "typing-indicator";
    el.innerHTML = "<span></span><span></span><span></span>";
    conversation.appendChild(el);
    conversation.scrollTop = conversation.scrollHeight;
  }

  function hideTyping() {
    const el = document.getElementById("typing-indicator");
    if (el) el.remove();
  }

  async function sendMessage(text) {
    if (!text.trim() || !sessionId) return;
    addMessage("user", text, false, null);
    showTyping();
    const { ok, status, body } = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });
    hideTyping();
    if (!ok && status === 502) {
      addMessage("assistant", "I couldn't reach the AI provider (" + body.category + ").", false, null);
      offerOfflineMode();
      return;
    }
    addMessage("assistant", body.text, body.offline, body.cards);
    if (body.cards && body.cards.restoration && !body.cards.restoration.fallback.fallback) {
      lastEstimate = body.cards.restoration;
    }
    if (currentView === "dashboard") loadDashboard();
  }

  function offerOfflineMode() {
    const card = document.createElement("div");
    card.className = "card";
    const p = document.createElement("p");
    p.textContent = "Switch to offline explanation mode to keep going?";
    card.appendChild(p);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Use offline mode";
    btn.addEventListener("click", async () => {
      await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ offline_mode: true }),
      });
      card.remove();
      addMessage("assistant", "Offline mode is on. Ask me again.", true, null);
    });
    card.appendChild(btn);
    conversation.appendChild(card);
    conversation.scrollTop = conversation.scrollHeight;
  }

  async function runWhatIf(action) {
    if (!sessionId) return;
    const { body } = await api("/api/whatif", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, action }),
    });

    emptyState.hidden = true;
    const msg = document.createElement("div");
    msg.className = "message assistant";

    if (!body.after.fallback.fallback && body.before.low_hours && body.after.low_hours) {
      const before = body.before, after = body.after;
      const ba = document.createElement("div");
      ba.className = "before-after";
      ba.innerHTML = `<span class="before">${before.low_hours.value}-${before.high_hours.value} h</span><span>→</span><span class="after">${after.low_hours.value}-${after.high_hours.value} h</span>`;
      msg.appendChild(ba);
    }

    const label = {
      block_access: "Access is now assumed blocked — the change is attributed only to that assumption.",
      clear_access: "Access assumption cleared.",
      add_crews: "Two extra crews are now assumed available.",
      complete_repairs: "Repairs on this path are marked complete.",
      reset: "Scenario reset to before the storm.",
    }[action];
    const p = document.createElement("p");
    p.textContent = label;
    msg.appendChild(p);

    renderCards({ risk: body.risk, restoration: body.after, prep: body.prep, alerts: body.alerts });
    conversation.appendChild(msg);
    conversation.scrollTop = conversation.scrollHeight;

    if (currentView === "dashboard") loadDashboard();
  }

  document.getElementById("empty-state").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-question]");
    if (btn) sendMessage(btn.dataset.question);
  });

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = messageInput.value;
    messageInput.value = "";
    sendMessage(text);
  });

  chips.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-action]");
    if (btn) runWhatIf(btn.dataset.action);
  });

  householdSelect.addEventListener("change", () => startSession(householdSelect.value));

  document.getElementById("new-conversation-btn").addEventListener("click", () => startSession(householdSelect.value));

  document.getElementById("evidence-close").addEventListener("click", () => {
    document.getElementById("evidence-dialog").close();
  });

  const settingsDialog = document.getElementById("settings-dialog");
  document.getElementById("settings-btn").addEventListener("click", async () => {
    const { body } = await api("/api/settings");
    document.getElementById("offline-toggle").checked = body.offline_mode;
    document.getElementById("provider-select").value = body.provider || (body.connected ? "gemini" : "local");
    document.getElementById("settings-status").textContent = body.connected
      ? "Connected — model: " + body.model
      : (body.last_error ? "Last error: " + body.last_error.category : "Not connected.");
    settingsDialog.showModal();
  });
  document.getElementById("settings-close").addEventListener("click", () => settingsDialog.close());
  document.getElementById("settings-save").addEventListener("click", async () => {
    const apiKey = document.getElementById("api-key-input").value;
    const offline = document.getElementById("offline-toggle").checked;
    const payload = { offline_mode: offline, provider: document.getElementById("provider-select").value };
    if (apiKey) payload.api_key = apiKey;
    const { ok, body } = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("api-key-input").value = "";
    document.getElementById("settings-status").textContent = ok
      ? (body.connected ? "Connected — model: " + body.model : "Offline mode is on.")
      : "Connection failed (" + body.category + "). Offline mode is available.";
  });

  document.getElementById("theme-select").addEventListener("change", (e) => setTheme(e.target.value));

  // Storm activity dashboard
  const ALERT_LABELS = {
    pre_storm: "Pre-storm",
    outage_confirmed: "Outage confirmed",
    estimate_updated: "Estimate updated",
    restoration_complete: "Restoration complete",
  };
  function eventText(event) {
    if (event.type === "whatif_applied") return "What-if: " + event.detail.action.replace(/_/g, " ");
    if (event.type === "estimate_changed") return `Estimate changed: ${event.detail.before[0]}-${event.detail.before[1]} h → ${event.detail.after[0]}-${event.detail.after[1]} h`;
    if (event.type === "alert_previewed") return "Alert previewed: " + (ALERT_LABELS[event.detail.alert_type] || event.detail.alert_type);
    return event.type;
  }

  function dashboardSection(title, iconKind, iconColor) {
    const section = document.createElement("div");
    section.className = "dashboard-section";
    const h3 = document.createElement("h3");
    h3.className = "section-title";
    if (iconKind) h3.appendChild(iconCircle(iconKind, iconColor, true));
    h3.appendChild(document.createTextNode(title));
    section.appendChild(h3);
    return section;
  }

  function renderDashboard(data) {
    const root = document.getElementById("dashboard-content");
    root.innerHTML = "";

    if (data.risk.fallback && data.risk.fallback.fallback) {
      const p = document.createElement("p");
      p.textContent = "We can't give a reliable estimate for this location. " + data.risk.fallback.reason;
      root.appendChild(p);
      return;
    }

    const grid = document.createElement("div");
    grid.className = "dashboard-grid";

    const riskSection = dashboardSection("Risk", "warning", "var(--color-icon-orange)");
    riskSection.appendChild(riskCard(data.risk));
    grid.appendChild(riskSection);

    const estimateSection = dashboardSection("Restoration estimate", "clock", "var(--color-icon-blue)");
    if (data.restoration.reference_effort_hours.value === 0) {
      const p = document.createElement("p");
      p.textContent = "Power should be back on per this simulation.";
      estimateSection.appendChild(p);
    } else {
      if (data.previous_estimate && (data.previous_estimate.low_hours !== data.restoration.low_hours.value || data.previous_estimate.high_hours !== data.restoration.high_hours.value)) {
        const ba = document.createElement("div");
        ba.className = "before-after";
        ba.innerHTML = `<span class="before">${data.previous_estimate.low_hours}-${data.previous_estimate.high_hours} h</span><span>→</span><span class="after">${data.restoration.low_hours.value}-${data.restoration.high_hours.value} h</span>`;
        estimateSection.appendChild(ba);
      }
      estimateSection.appendChild(rangeBar(data.restoration.low_hours.value, data.restoration.high_hours.value, 24));
      const tagRow = document.createElement("div");
      appendChild(tagRow, evidenceTag(data.restoration.low_hours, "low"));
      appendChild(tagRow, evidenceTag(data.restoration.high_hours, "high"));
      estimateSection.appendChild(tagRow);
    }
    grid.appendChild(estimateSection);
    root.appendChild(grid);

    const simulationSection = dashboardSection("Probability fan & topology", "pulse", "var(--color-icon-blue)");
    const mc = data.monte_carlo;
    if (mc) {
      const fan = document.createElement("div");
      fan.className = "probability-fan";
      [ ["P10 optimistic", mc.p10], ["P50 median", mc.p50], ["P90 conservative", mc.p90] ].forEach(([label, value]) => {
        const item = document.createElement("div"); item.className = "fan-item";
        item.innerHTML = `<span>${label}</span><strong>${value.toFixed(1)} h</strong>`;
        fan.appendChild(item);
      });
      simulationSection.appendChild(fan);
    }
    const topology = document.createElement("div"); topology.className = "topology-flow";
    (data.topology || []).forEach((node, index) => {
      const step = document.createElement("div"); step.className = "topology-step";
      step.innerHTML = `<span class="topology-node">${index + 1}</span><span>${node.stage.replace(/_/g, " ")}</span><small>${node.status.replace(/_/g, " ")}</small>`;
      topology.appendChild(step);
    });
    simulationSection.appendChild(topology);
    root.appendChild(simulationSection);

    const timelineSection = dashboardSection("Restoration step timeline", "list", "var(--color-icon-teal)");
    const jobs = (data.timeline && data.timeline.jobs) || [];
    if (!jobs.length) {
      const p = document.createElement("p");
      p.className = "empty-lane";
      p.textContent = "No repair jobs on this path.";
      timelineSection.appendChild(p);
    } else {
      for (const job of jobs) {
        const row = document.createElement("div");
        row.className = "timeline-row";
        const crew = document.createElement("span");
        crew.className = "crew-badge";
        crew.textContent = "Crew " + job.crew;
        row.appendChild(crew);
        const label = document.createElement("span");
        label.textContent = job.label.value + " — " + job.duration_hours.value + " h";
        row.appendChild(label);
        const status = document.createElement("span");
        status.className = "status-badge status-" + job.status;
        status.textContent = job.status.replace("_", " ");
        row.appendChild(status);
        timelineSection.appendChild(row);
      }
    }
    root.appendChild(timelineSection);

    const alertsSection = dashboardSection("Alert messages", "bell", "var(--color-icon-orange)");
    for (const alert of data.alerts) {
      const row = document.createElement("div");
      row.className = "alert-row";
      const left = document.createElement("div");
      const name = document.createElement("div");
      name.className = "alert-name";
      name.textContent = ALERT_LABELS[alert.type] || alert.type;
      left.appendChild(name);
      const timing = document.createElement("div");
      timing.className = "alert-timing";
      timing.textContent = alert.timing;
      left.appendChild(timing);
      if (alert.triggered) {
        const msg = document.createElement("div");
        msg.className = "alert-msg";
        msg.textContent = alert.message;
        left.appendChild(msg);
      }
      row.appendChild(left);
      const badge = document.createElement("span");
      badge.className = alert.triggered ? "triggered-badge" : "not-triggered-badge";
      badge.textContent = alert.triggered ? "Triggered" : "Not yet";
      row.appendChild(badge);
      alertsSection.appendChild(row);
    }
    root.appendChild(alertsSection);

    const eventsSection = dashboardSection("Session event feed", "clock", "var(--color-icon-teal)");
    if (!data.events.length) {
      const p = document.createElement("p");
      p.className = "empty-lane";
      p.textContent = "No events yet — try a what-if chip.";
      eventsSection.appendChild(p);
    } else {
      for (const event of data.events) {
        const row = document.createElement("div");
        row.className = "event-row";
        const time = document.createElement("time");
        time.textContent = event.timestamp.slice(11, 19) + " UTC";
        row.appendChild(time);
        const span = document.createElement("span");
        span.textContent = eventText(event);
        row.appendChild(span);
        eventsSection.appendChild(row);
      }
    }
    root.appendChild(eventsSection);
    loadWeatherMap(root);
  }

  async function loadWeatherMap(root) {
    const section = dashboardSection("Live U.S. weather activity", "warning", "var(--color-icon-orange)");
    const note = document.createElement("p");
    note.className = "weather-disclaimer";
    note.textContent = "Current National Weather Service alerts. This is weather information, not a utility outage or crew-status feed.";
    section.appendChild(note);
    const map = document.createElement("div"); map.id = "weather-map"; map.className = "weather-map"; section.appendChild(map); root.appendChild(section);
    if (!window.L) { map.textContent = "Map library unavailable. Check the NWS alerts source directly."; return; }
    const leafletMap = L.map(map, { scrollWheelZoom: false }).setView([39.5, -98.5], 4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap contributors" }).addTo(leafletMap);
    try {
      const response = await fetch("/api/weather/alerts");
      const geo = await response.json();
      const colors = { Extreme: "#8e24aa", Severe: "#d32f2f", Moderate: "#ef6c00", Minor: "#2e7d32" };
      L.geoJSON(geo, { style: feature => ({ color: colors[feature.properties.severity] || "#546e7a", fillOpacity: .35, weight: 1 }),
        onEachFeature: (feature, layer) => layer.bindPopup(`<strong>${feature.properties.event}</strong><br>${feature.properties.area}<br><small>${feature.properties.headline || "Active NWS alert"}</small>`)
      }).addTo(leafletMap);
      note.textContent = `${geo.features.length} active NWS weather alert areas. Weather data is separate from Watt'sNext utility replay data.`;
    } catch (_) { note.textContent = "Weather alerts are temporarily unavailable. Utility replay data remains available."; }
  }

  async function loadDashboard() {
    if (!sessionId) return;
    const { body } = await api("/api/dashboard?session_id=" + encodeURIComponent(sessionId));
    renderDashboard(body);
  }

  function setView(view) {
    currentView = view;
    const askBtn = document.getElementById("view-ask-btn");
    const dashBtn = document.getElementById("view-dashboard-btn");
    const dashView = document.getElementById("dashboard-view");
    if (view === "ask") {
      conversation.hidden = false;
      dashView.hidden = true;
      askBtn.setAttribute("aria-pressed", "true");
      dashBtn.setAttribute("aria-pressed", "false");
    } else {
      conversation.hidden = true;
      dashView.hidden = false;
      askBtn.setAttribute("aria-pressed", "false");
      dashBtn.setAttribute("aria-pressed", "true");
      loadDashboard();
    }
  }

  document.getElementById("view-ask-btn").addEventListener("click", () => setView("ask"));
  document.getElementById("view-dashboard-btn").addEventListener("click", () => setView("dashboard"));

  applyStoredTheme();
  loadHouseholds().then(() => startSession(householdSelect.value));
})();
