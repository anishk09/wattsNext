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

  const EVIDENCE_LABELS = {
    source_data: "Source data",
    assumption: "Assumption",
    model_estimate: "Model estimate",
    not_available: "Not available",
  };

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
    const dot = document.createElement("span");
    dot.className = "dot";
    chip.appendChild(dot);
    chip.appendChild(document.createTextNode(risk.risk_band.value + " risk"));
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

  function threeLaneCard(restoration, prep) {
    const card = document.createElement("div");
    card.className = "card lanes";

    const estimateLane = document.createElement("div");
    estimateLane.className = "lane";
    estimateLane.innerHTML = "<h4>Estimate</h4>";
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
      estimateLane.innerHTML += '<p class="empty-lane">No estimate available.</p>';
    }
    card.appendChild(estimateLane);

    const confirmedLane = document.createElement("div");
    confirmedLane.className = "lane";
    confirmedLane.innerHTML = "<h4>Confirmed by utility</h4><p class=\"empty-lane\">Nothing is confirmed by the utility in this prototype.</p>";
    card.appendChild(confirmedLane);

    const actionsLane = document.createElement("div");
    actionsLane.className = "lane";
    actionsLane.innerHTML = "<h4>What you can do</h4>";
    const ul = document.createElement("ul");
    const actions = (prep && prep.actions) || [];
    for (const a of actions) {
      const li = document.createElement("li");
      li.textContent = a;
      ul.appendChild(li);
    }
    actionsLane.appendChild(ul);
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

  function renderCards(cards, container) {
    if (cards.risk) container.appendChild(riskCard(cards.risk));
    if (cards.restoration || cards.prep) container.appendChild(threeLaneCard(cards.restoration, cards.prep));
    if (cards.alerts) container.appendChild(alertsCard(cards.alerts));
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
    if (cards) renderCards(cards, msg);
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

    renderCards({ risk: body.risk, restoration: body.after, alerts: body.alerts }, msg);
    conversation.appendChild(msg);
    conversation.scrollTop = conversation.scrollHeight;
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
    document.getElementById("settings-status").textContent = body.connected
      ? "Connected — model: " + body.model
      : (body.last_error ? "Last error: " + body.last_error.category : "Not connected.");
    settingsDialog.showModal();
  });
  document.getElementById("settings-close").addEventListener("click", () => settingsDialog.close());
  document.getElementById("settings-save").addEventListener("click", async () => {
    const apiKey = document.getElementById("api-key-input").value;
    const offline = document.getElementById("offline-toggle").checked;
    const payload = { offline_mode: offline };
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

  applyStoredTheme();
  loadHouseholds().then(() => startSession(householdSelect.value));
})();
