"use strict";

let lastCompareReport = "";

async function requestJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  const result = await response.json();
  if (!response.ok) {
    const problem = new Error(result.error || "The request could not be completed.");
    problem.data = result;
    throw problem;
  }
  return result;
}

function appendListItems(list, values) {
  list.replaceChildren();
  values.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  });
}

function appendMemoryQuotes(list, values, sources = []) {
  list.replaceChildren();
  values.forEach((value) => {
    const item = document.createElement("li");
    const quote = document.createElement("blockquote");
    quote.textContent = value;
    const citation = document.createElement("span");
    citation.className = "memory-citation";
    citation.textContent = "Recalled incident memory";
    item.append(quote, citation);
    const source = sources.find((entry) => entry.memory === value);
    if (source) addCitationButtons(item, [source]);
    list.append(item);
  });
}

function addCitationButtons(container, sources) {
  if (!container) return;
  container.querySelectorAll(":scope > .claim-citations").forEach((item) => item.remove());
  if (!sources.length) return;
  const citations = document.createElement("span");
  citations.className = "claim-citations";
  sources.forEach((source, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "citation-marker";
    button.dataset.memorySource = String(source.incident_id);
    button.dataset.matchMethod = source.method;
    button.setAttribute("aria-label", `Open source incident ${source.incident_id}`);
    button.textContent = `[${index + 1}]`;
    citations.append(button);
  });
  container.append(citations);
}

function updateSuccessRecord(summary) {
  renderSuccessRecord("success-record", summary);
}

function renderSuccessRecord(id, summary) {
  const record = document.getElementById(id);
  if (!record) return;
  record.hidden = !summary;
  record.replaceChildren();
  if (!summary) return;
  record.append(document.createTextNode(summary.text));
  if (summary.needs_review) {
    const badge = document.createElement("span");
    badge.className = "review-badge";
    badge.textContent = "Needs review";
    record.append(" ", badge);
  }
}

function renderBriefing(briefing) {
  const content = document.getElementById("briefing-content");
  content.hidden = false;
  const outcomeCard = document.getElementById("outcome-card");
  if (outcomeCard) outcomeCard.hidden = false;
  const memoryBadge = document.getElementById("from-memory-badge");
  if (memoryBadge) memoryBadge.hidden = !(briefing.memories || []).length;
  document.getElementById("likely-match").textContent = briefing.likely_match;
  const matchNote = document.getElementById("match-note");
  if (matchNote) {
    matchNote.textContent = briefing.match_note || "";
    matchNote.hidden = !briefing.match_note;
  }
  document.getElementById("root-cause-hypothesis").textContent = briefing.root_cause;
  const sources = briefing.memory_sources || [];
  addCitationButtons(
    document.getElementById("likely-match").parentElement,
    sources,
  );
  addCitationButtons(
    document.getElementById("root-cause-hypothesis").parentElement,
    sources,
  );

  const confidence = Math.max(0, Math.min(100, Number(briefing.match_confidence) || 0));
  document.getElementById("confidence-value").textContent = `${confidence}%`;
  const track = document.querySelector(".confidence-track");
  track.setAttribute("aria-valuenow", String(confidence));
  document.getElementById("confidence-bar").style.width = `${confidence}%`;

  appendListItems(document.getElementById("fix-steps"), briefing.fix_steps || []);
  appendListItems(document.getElementById("skip-these"), briefing.skip_these || []);
  document.querySelectorAll("#fix-steps li, #skip-these li").forEach((item) => {
    addCitationButtons(item, sources);
  });
  appendMemoryQuotes(
    document.getElementById("memories-used"),
    briefing.memories || [],
    sources,
  );
  document.getElementById("memories-heading").textContent =
    `Memories used · ${(briefing.memories || []).length}`;
  appendMemoryQuotes(
    document.getElementById("other-memories"),
    briefing.other_memories || [],
  );
  const otherMemorySection = document.getElementById("other-memory-section");
  if (otherMemorySection) {
    otherMemorySection.hidden = !(briefing.other_memories || []).length;
  }
  document.getElementById("skip-panel").hidden = !(briefing.skip_these || []).length;
  document.getElementById("no-memories").hidden = !!(
    (briefing.memories || []).length || (briefing.other_memories || []).length
  );
  updateSuccessRecord(briefing.outcome_summary);
}

function renderRecalledMemories(memories, sources = []) {
  const content = document.getElementById("briefing-content");
  content.hidden = false;
  appendMemoryQuotes(document.getElementById("memories-used"), memories, sources);
  document.getElementById("memories-heading").textContent =
    `Memories recalled · ${memories.length}`;
  document.getElementById("no-memories").hidden = !!memories.length;
  const otherMemorySection = document.getElementById("other-memory-section");
  if (otherMemorySection) otherMemorySection.hidden = true;
}

function setupLoginCounters() {
  const counters = document.querySelectorAll("[data-count-target]");
  if (!counters.length) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  counters.forEach((counter) => {
    const target = Number(counter.dataset.countTarget);
    if (!Number.isFinite(target)) return;
    const suffix = counter.dataset.countSuffix || "";
    if (reduceMotion) {
      counter.textContent = `${target.toLocaleString()}${suffix}`;
      return;
    }
    const started = performance.now();
    const duration = 480;
    function update(now) {
      const progress = Math.min(1, (now - started) / duration);
      const eased = 1 - (1 - progress) ** 3;
      counter.textContent = `${Math.round(target * eased).toLocaleString()}${suffix}`;
      if (progress < 1) window.requestAnimationFrame(update);
    }
    window.requestAnimationFrame(update);
  });
}

function setupPasswordToggles() {
  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.passwordToggle);
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
      button.setAttribute("aria-pressed", String(show));
      button.setAttribute(
        "aria-label",
        show ? "Hide password" : "Show password",
      );
    });
  });
}

function setupMemoryDrawer() {
  const drawer = document.getElementById("memory-drawer");
  if (!drawer) return;
  const backdrop = document.getElementById("memory-drawer-backdrop");
  const closeButton = document.getElementById("memory-drawer-close");
  let trigger = null;

  function close() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    drawer.inert = true;
    backdrop.hidden = true;
    if (trigger) trigger.focus();
  }

  closeButton.addEventListener("click", close);
  backdrop.addEventListener("click", close);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && drawer.classList.contains("open")) close();
  });
  document.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-memory-source]");
      if (!button) return;
      trigger = button;
      const error = document.getElementById("memory-drawer-error");
      error.hidden = true;
      document.getElementById("memory-drawer-title").textContent =
        `Incident #${button.dataset.memorySource}`;
      document.getElementById("memory-match-method").textContent =
        button.dataset.matchMethod === "matched by similarity"
          ? "Source matched by similarity to the stored incident."
          : "Source matched by incident ID.";
      drawer.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
      drawer.inert = false;
      backdrop.hidden = false;
      closeButton.focus();
      try {
        const response = await fetch(`/api/memory/source/${button.dataset.memorySource}`);
        const source = await response.json();
        if (!response.ok) throw new Error(source.error || "Could not load the source incident.");
        document.getElementById("memory-drawer-title").textContent =
          `Incident #${source.id} · ${source.title}`;
        document.getElementById("memory-source-report").textContent = source.report;
        document.getElementById("memory-source-root").textContent = source.root_cause || "Not recorded";
        document.getElementById("memory-source-fix").textContent = source.fix || "Not recorded";
        document.getElementById("memory-source-failed").textContent = source.not_worked || "Not recorded";
        document.getElementById("memory-source-date").textContent =
          source.resolved_at ? source.resolved_at.slice(0, 10) : "Not recorded";
      } catch (problem) {
        error.textContent = problem.message;
        error.hidden = false;
      }
  });
}

function setupOutcomeForm() {
  const form = document.getElementById("outcome-form");
  if (!form) return;
  const button = document.getElementById("outcome-submit");
  const status = document.getElementById("outcome-status");
  const error = document.getElementById("outcome-error");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    status.hidden = true;
    button.disabled = true;
    button.textContent = "Saving…";
    const values = new FormData(form);
    try {
      const saved = await requestJson(
        `/api/incidents/${form.dataset.incidentId}/outcome`,
        Object.fromEntries(values.entries()),
      );
      status.textContent = "Outcome saved. Retaining it in memory…";
      status.hidden = false;
      const deadline = Date.now() + 120000;
      while (Date.now() < deadline) {
        const response = await fetch(`/api/outcomes/${saved.outcome_id}/memory-sync`);
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not check outcome memory status.");
        updateSuccessRecord(result.outcome_summary);
        if (result.memory_sync === "synced") {
          status.textContent = "Outcome saved and retained in memory.";
          form.reset();
          return;
        }
        if (result.memory_sync === "failed") {
          status.textContent = "Outcome saved in SQLite, but memory retention failed.";
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 900));
      }
      status.textContent = "Outcome saved. Memory retention is still running.";
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "Save outcome";
    }
  });
}

function setupOverviewFeed() {
  const feed = document.getElementById("live-feed-list");
  if (!feed) return;
  const status = document.getElementById("feed-status");
  const refreshUrl = feed.dataset.refreshUrl;

  async function refreshFeed() {
    try {
      const response = await fetch(refreshUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin"
      });
      if (!response.ok) throw new Error("The incident feed could not be refreshed.");
      const html = await response.text();
      const page = new DOMParser().parseFromString(html, "text/html");
      const sourceRows = page.querySelectorAll("#incident-list tbody tr");
      if (!page.querySelector("#incident-list")) {
        throw new Error("The incident feed response was incomplete.");
      }

      if (!sourceRows.length) {
        feed.replaceChildren();
        const empty = document.createElement("div");
        empty.className = "empty-state compact-empty";
        const message = document.createElement("p");
        message.textContent = "No incidents have been reported yet.";
        const link = document.createElement("a");
        link.className = "button primary";
        link.href = "/report";
        link.textContent = "Report an incident";
        empty.append(message, link);
        feed.append(empty);
      } else {
        const rows = Array.from(sourceRows, (sourceRow) => {
          const cells = sourceRow.querySelectorAll("td");
          const titleLink = cells[1].querySelector(".table-title");
          const time = cells[6].querySelector("time");
          const row = document.createElement("a");
          row.className = "live-feed-row";
          row.href = titleLink.href;
          const source = document.createElement("span");
          source.className = `feed-source feed-source-${cells[5].textContent.trim().toLowerCase()}`;
          source.textContent = cells[5].textContent.trim();
          const title = document.createElement("span");
          title.className = "feed-title";
          title.textContent = titleLink.textContent;
          const severity = document.createElement("span");
          severity.className = cells[3].querySelector(".badge").className;
          severity.textContent = cells[3].textContent.trim();
          const incidentStatus = document.createElement("span");
          incidentStatus.className = cells[4].querySelector(".badge").className;
          incidentStatus.textContent = cells[4].textContent.trim();
          const reported = document.createElement("time");
          reported.dateTime = time.dateTime;
          reported.textContent = time.textContent.trim();
          row.append(source, title, severity, incidentStatus, reported);
          return row;
        });
        feed.replaceChildren(...rows);
      }
      status.hidden = true;
    } catch (problem) {
      status.textContent = "The live feed could not refresh. The incidents shown may be out of date.";
      status.hidden = false;
    }
  }

  window.setInterval(refreshFeed, 10000);
}

function renderAskBriefing(prefix, briefing) {
  const memories = briefing.memories || [];
  const sources = briefing.memory_sources || [];
  const likelyMatch = document.getElementById(`${prefix}-likely-match`);
  const rootCause = document.getElementById(`${prefix}-root-cause`);
  likelyMatch.textContent = briefing.likely_match || "Checking recalled memories…";
  const matchNote = document.getElementById(`${prefix}-match-note`);
  if (matchNote) {
    matchNote.textContent = briefing.match_note || "";
    matchNote.hidden = !briefing.match_note;
  }
  rootCause.textContent = briefing.root_cause;
  addCitationButtons(likelyMatch.parentElement, sources);
  addCitationButtons(rootCause.parentElement, sources);
  const confidence = Math.max(0, Math.min(100, Number(briefing.match_confidence) || 0));
  document.getElementById(`${prefix}-confidence-value`).textContent = `${confidence}%`;
  const track = document.getElementById(`${prefix}-confidence-track`);
  track.setAttribute("aria-valuenow", String(confidence));
  document.getElementById(`${prefix}-confidence-bar`).style.width = `${confidence}%`;
  const fixSteps = briefing.fix_steps || [];
  const skipThese = briefing.skip_these || [];
  appendListItems(document.getElementById(`${prefix}-fix-steps`), fixSteps);
  appendListItems(document.getElementById(`${prefix}-skip-these`), skipThese);
  document.querySelectorAll(`#${prefix}-fix-steps li, #${prefix}-skip-these li`).forEach((item) => {
    addCitationButtons(item, sources);
  });
  document.getElementById(`${prefix}-skip-panel`).hidden = !skipThese.length;
  document.getElementById(`${prefix}-memory-heading`).textContent =
    briefing.complete === false
      ? `Memories recalled · ${memories.length}`
      : `Memories used · ${memories.length}`;
  appendMemoryQuotes(document.getElementById(`${prefix}-memories`), memories, sources);
  const otherMemories = briefing.other_memories || [];
  document.getElementById(`${prefix}-no-memories`).hidden =
    !!(memories.length || otherMemories.length);
  const otherMemoryList = document.getElementById(`${prefix}-other-memories`);
  const otherMemorySection = document.getElementById(
    `${prefix}-other-memory-section`,
  );
  if (otherMemoryList) appendMemoryQuotes(otherMemoryList, otherMemories);
  if (otherMemorySection) {
    otherMemorySection.hidden = !otherMemories.length;
  }
  renderSuccessRecord(`${prefix}-success-record`, briefing.outcome_summary);
}

function renderAskResult(result) {
  document.getElementById("ask-seen-before").textContent = "Agent briefing";
  const link = document.getElementById("ask-incident-link");
  link.href = result.url;
  const reportCount = document.getElementById("ask-report-count");
  reportCount.textContent = result.report_count > 1
    ? `This report was added to an existing incident (x${result.report_count} reports).`
    : "A new incident was saved.";
  reportCount.hidden = false;
  renderAskBriefing("ask", result.briefing);
  const panel = document.getElementById("ask-result");
  panel.hidden = false;
  panel.scrollIntoView({ block: "nearest" });
}

function setupAskForm() {
  const form = document.getElementById("ask-form");
  if (!form) return;
  const button = document.getElementById("ask-submit");
  const spinner = document.getElementById("ask-spinner");
  const error = document.getElementById("ask-error");
  const results = document.getElementById("ask-result");
  const savedLink = document.getElementById("ask-saved-link");
  const reportField = document.getElementById("ask-report");
  const characterCount = document.getElementById("ask-character-count");
  function updateCharacterCount() {
    characterCount.textContent = `${reportField.value.length.toLocaleString()} / 10,000`;
  }
  reportField.addEventListener("input", updateCharacterCount);
  updateCharacterCount();
  document.querySelectorAll("[data-ask-example]").forEach((example) => {
    example.addEventListener("click", () => {
      reportField.value = example.dataset.askExample;
      reportField.focus();
      updateCharacterCount();
    });
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    savedLink.hidden = true;
    results.hidden = true;
    button.disabled = true;
    button.textContent = "Asking…";
    document.getElementById("ask-spinner-text").textContent =
      "Checking related incidents…";
    spinner.hidden = false;
    try {
      const recall = await requestJson("/api/ask", {
        report: reportField.value.trim(),
        phase: "recall",
      });
      if (recall.complete) {
        renderAskResult(recall);
      } else {
        renderAskResult({
          ...recall,
          briefing: {
            complete: false,
            memories: recall.memories || [],
            memory_sources: recall.memory_sources || [],
          },
        });
        document.getElementById("ask-spinner-text").textContent =
          "Preparing the briefing…";
        const briefing = await requestJson(
          `/api/incidents/${recall.id}/triage`,
        );
        renderAskResult({ ...recall, briefing });
      }
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
      if (problem.data && problem.data.url) {
        savedLink.href = problem.data.url;
        savedLink.hidden = false;
      }
    } finally {
      spinner.hidden = true;
      button.disabled = false;
      button.textContent = "Ask the agent";
    }
  });
}

function setupCharacterCounts() {
  document.querySelectorAll("[data-character-count]").forEach((field) => {
    const counter = document.getElementById(field.dataset.characterCount);
    if (!counter) return;
    const update = () => {
      counter.textContent = `${field.value.length.toLocaleString()} / 10,000`;
    };
    field.addEventListener("input", update);
    update();
  });
}

async function runTriage() {
  const panel = document.getElementById("briefing-panel");
  if (!panel) return;
  const spinner = document.getElementById("triage-spinner");
  const error = document.getElementById("triage-error");
  const retry = document.getElementById("retry-triage");
  spinner.hidden = false;
  document.getElementById("triage-spinner-text").textContent =
    "Reviewing related incidents…";
  error.hidden = true;
  retry.hidden = true;
  try {
    const recall = await requestJson(
      `/api/incidents/${panel.dataset.incidentId}/recall`,
    );
    if (recall.complete) {
      renderBriefing(recall.briefing);
      panel.dataset.hasBriefing = "true";
      spinner.hidden = true;
      return;
    }
    renderRecalledMemories(recall.memories || [], recall.memory_sources || []);
    document.getElementById("triage-spinner-text").textContent =
      "Preparing the briefing…";
    const briefing = await requestJson(`/api/incidents/${panel.dataset.incidentId}/triage`);
    renderBriefing(briefing);
    panel.dataset.hasBriefing = "true";
    spinner.hidden = true;
  } catch (problem) {
    spinner.hidden = true;
    error.textContent = problem.message;
    error.hidden = false;
    retry.hidden = false;
  }
}

function setupReportForm() {
  const form = document.getElementById("report-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = document.getElementById("report-submit");
    const error = document.getElementById("report-error");
    error.hidden = true;
    button.disabled = true;
    button.textContent = "Saving…";
    const values = new FormData(form);
    const body = Object.fromEntries(values.entries());
    try {
      const result = await requestJson("/api/incidents", body);
      window.location.assign(result.url);
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
      button.disabled = false;
      button.textContent = "Save incident";
    }
  });
}

function setupStatusForm() {
  const form = document.getElementById("status-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const incidentId = document.getElementById("briefing-panel").dataset.incidentId;
    const message = document.getElementById("status-message");
    try {
      const result = await requestJson(`/api/incidents/${incidentId}/status`, {
        status: document.getElementById("incident-status").value
      });
      message.textContent = `Status updated to ${result.status}.`;
      message.hidden = false;
      window.location.reload();
    } catch (problem) {
      message.textContent = problem.message;
      message.hidden = false;
    }
  });
}

async function waitForMemorySync(incidentId, stateElement, retryButton, resolveButton) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const response = await fetch(`/api/incidents/${incidentId}/memory-sync`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not check memory status.");
    stateElement.textContent = `Memory sync: ${result.memory_sync}`;
    if (result.memory_sync === "synced") {
      stateElement.textContent = "Saved. The agent will recognise this next time.";
      retryButton.hidden = true;
      resolveButton.disabled = false;
      resolveButton.textContent = "Save resolution";
      const card = document.getElementById("resolution-card");
      const savedState = document.getElementById("resolve-saved-state");
      if (card) card.classList.remove("resolve-saving");
      if (card) card.classList.add("resolve-saved");
      if (savedState) savedState.hidden = false;
      showToast("Resolution saved. The agent will recognise this next time.", "success", 4000);
      const tryReworded = document.getElementById("try-reworded");
      if (tryReworded) tryReworded.hidden = false;
      return;
    }
    if (result.memory_sync === "failed") {
      stateElement.textContent = "Resolution saved; memory sync failed.";
      retryButton.hidden = false;
      resolveButton.disabled = false;
      resolveButton.textContent = "Save resolution";
      const card = document.getElementById("resolution-card");
      if (card) card.classList.remove("resolve-saving");
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
  }
  stateElement.textContent = "Memory sync is still running.";
  resolveButton.disabled = false;
  resolveButton.textContent = "Save resolution";
}

function setupResolutionForm() {
  const form = document.getElementById("resolve-form");
  if (!form) return;
  const incidentId = form.dataset.incidentId;
  const button = document.getElementById("resolve-submit");
  const retryButton = document.getElementById("retry-memory");
  const state = document.getElementById("memory-state");
  const error = document.getElementById("resolve-error");

  async function submitResolution(url, body) {
    error.hidden = true;
    button.disabled = true;
    button.textContent = "Saving to memory…";
    state.textContent = "Saving to memory…";
    const card = document.getElementById("resolution-card");
    const savedState = document.getElementById("resolve-saved-state");
    if (card) card.classList.add("resolve-saving");
    if (savedState) savedState.hidden = true;
    retryButton.hidden = true;
    try {
      await requestJson(url, body);
      await waitForMemorySync(incidentId, state, retryButton, button);
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
      button.disabled = false;
      button.textContent = "Save resolution";
      if (card) card.classList.remove("resolve-saving");
    }
}

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = new FormData(form);
    submitResolution(`/api/incidents/${incidentId}/resolve`, Object.fromEntries(values.entries()));
  });

  retryButton.addEventListener("click", () => {
    submitResolution(`/api/incidents/${incidentId}/retry-memory`, {});
  });
}

function setupCompareForm() {
  const form = document.getElementById("compare-form");
  if (!form) return;
  const incidentSelect = document.getElementById("compare-incident");
  const reportField = document.getElementById("compare-report");
  const submitButton = document.getElementById("compare-submit");
  const error = document.getElementById("compare-error");
  const results = document.getElementById("comparison-results");

  incidentSelect.addEventListener("change", () => {
    const option = incidentSelect.selectedOptions[0];
    if (incidentSelect.value) reportField.value = option.dataset.report || "";
  });
  reportField.addEventListener("input", () => {
    const option = incidentSelect.selectedOptions[0];
    if (incidentSelect.value && reportField.value !== (option.dataset.report || "")) {
      incidentSelect.value = "";
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    results.hidden = true;
    document.getElementById("comparison-input").hidden = true;
    submitButton.disabled = true;
    submitButton.textContent = "Recalling memories…";
    const payload = {
      incident_id: incidentSelect.value,
      report: reportField.value.trim()
    };
    try {
      const recall = await requestJson("/api/compare", {
        ...payload,
        phase: "recall",
      });
      renderComparisonRecall(recall.memories || [], recall.memory_sources || []);
      submitButton.textContent = "Preparing comparison…";
      const result = await requestJson("/api/compare", {
        ...payload,
        phase: "complete",
        memories: recall.memories || [],
      });
      lastCompareReport = payload.report;
      renderComparisonSide("without", result.without_memory);
      document.querySelector(".comparison-without").hidden = false;
      renderComparisonSide("with", result.with_memory);
      document.getElementById("comparison-explanation").textContent = result.explanation;
      document.getElementById("compare-no-memories").hidden = !!(
        result.with_memory.memories.length || result.with_memory.other_memories.length
      );
      document.getElementById("comparison-input").hidden = true;
      results.hidden = false;
      results.scrollIntoView({ block: "start" });
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Run comparison";
    }
  });
}

function setupCompareRewordButton() {
  const button = document.getElementById("compare-reword");
  if (!button) return;
  const error = document.getElementById("compare-reword-error");
  button.addEventListener("click", async () => {
    if (!lastCompareReport) return;
    button.disabled = true;
    button.textContent = "Rewording and comparing…";
    error.hidden = true;
    try {
      const recall = await requestJson("/api/compare/reworded", {
        report: lastCompareReport,
        phase: "recall",
      });
      lastCompareReport = recall.report;
      document.getElementById("compare-report").value = recall.report;
      document.getElementById("compare-incident").value = "";
      const input = document.getElementById("comparison-input");
      input.textContent = `Reworded report: ${recall.report}`;
      input.hidden = false;
      renderComparisonRecall(recall.memories || [], recall.memory_sources || []);
      button.textContent = "Preparing comparison…";
      const result = await requestJson("/api/compare/reworded", {
        report: recall.report,
        phase: "complete",
        memories: recall.memories || [],
      });
      renderComparisonSide("without", result.without_memory);
      document.querySelector(".comparison-without").hidden = false;
      renderComparisonSide("with", result.with_memory);
      document.getElementById("comparison-explanation").textContent = result.explanation;
      document.getElementById("compare-no-memories").hidden = !!(
        result.with_memory.memories.length || result.with_memory.other_memories.length
      );
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "Try a reworded version";
    }
  });
}

function renderComparisonRecall(memories, sources) {
  document.querySelector(".comparison-without").hidden = true;
  renderComparisonSide("with", {
    complete: false,
    likely_match: "Checking recalled memories…",
    root_cause: "",
    fix_steps: [],
    skip_these: [],
    match_confidence: 0,
    memories,
    memory_sources: sources,
  });
  document.getElementById("compare-no-memories").hidden = !!memories.length;
  document.getElementById("comparison-explanation").textContent =
    "Memories recalled; preparing the comparison.";
  const results = document.getElementById("comparison-results");
  results.hidden = false;
  results.scrollIntoView({ block: "start" });
}

function setupHandoffCopy() {
  const button = document.getElementById("copy-handoff");
  if (!button) return;
  const status = document.getElementById("handoff-copy-status");
  const error = document.getElementById("handoff-copy-error");
  button.addEventListener("click", async () => {
    const items = Array.from(document.querySelectorAll("[data-handoff-item]"));
    const text = items.length
      ? items.map((item) => item.innerText.trim()).join("\n\n")
      : "No incidents need an on-call handoff right now.";
    button.disabled = true;
    error.hidden = true;
    try {
      await navigator.clipboard.writeText(text);
      status.textContent = "Handoff copied to the clipboard.";
      status.hidden = false;
    } catch (problem) {
      error.textContent = "Clipboard access was unavailable. Select and copy the handoff text manually.";
      error.hidden = false;
    } finally {
      button.disabled = false;
    }
  });
}

function renderComparisonSide(prefix, briefing) {
  const sources = briefing.memory_sources || [];
  const complete = briefing.complete !== false;
  const claimSources = complete ? sources : [];
  const confidence = Math.max(0, Math.min(100, Number(briefing.match_confidence) || 0));
  const confidenceElement = document.getElementById(`${prefix}-confidence`);
  confidenceElement.dataset.countTarget = String(confidence);
  confidenceElement.dataset.countSuffix = "%";
  confidenceElement.textContent = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? `${confidence}%`
    : "0%";
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const started = performance.now();
    const duration = 480;
    const countFrame = (now) => {
      const progress = Math.min(1, (now - started) / duration);
      confidenceElement.textContent = `${Math.round(confidence * (1 - (1 - progress) ** 3))}%`;
      if (progress < 1) window.requestAnimationFrame(countFrame);
    };
    window.requestAnimationFrame(countFrame);
  }
  const likelyMatch = document.getElementById(`${prefix}-match`);
  const rootCause = document.getElementById(`${prefix}-root-cause`);
  likelyMatch.textContent =
    briefing.likely_match || (complete ? "" : "Checking recalled memories…");
  const matchNote = document.getElementById(`${prefix}-match-note`);
  if (matchNote) {
    matchNote.textContent = briefing.match_note || "";
    matchNote.hidden = !briefing.match_note;
  }
  rootCause.textContent = briefing.root_cause || "";
  addCitationButtons(likelyMatch.parentElement, claimSources);
  addCitationButtons(rootCause.parentElement, claimSources);
  appendListItems(document.getElementById(`${prefix}-fixes`), briefing.fix_steps || []);
  appendListItems(document.getElementById(`${prefix}-skips`), briefing.skip_these || []);
  const skipPanel = document.getElementById(`${prefix}-skip-panel`);
  if (skipPanel) skipPanel.hidden = !(briefing.skip_these || []).length;
  document.querySelectorAll(`#${prefix}-fixes li, #${prefix}-skips li`).forEach((item) => {
    addCitationButtons(item, sources);
  });
  if (prefix === "with") {
    appendMemoryQuotes(document.getElementById("with-memories"), briefing.memories || [], sources);
    appendMemoryQuotes(
      document.getElementById("with-other-memories"),
      briefing.other_memories || [],
    );
    document.getElementById("with-other-memory-section").hidden =
      !(briefing.other_memories || []).length;
    renderSuccessRecord("with-success-record", briefing.outcome_summary);
  }
  document.getElementById(`${prefix}-memory-heading`).textContent =
    `${complete ? "Memories used" : "Memories recalled"} · ${(briefing.memories || []).length}`;
}

function setupDeleteButtons() {
  document.querySelectorAll(".delete-incident").forEach((button) => {
    button.addEventListener("click", async () => {
      const incidentId = button.dataset.incidentId;
      if (!window.confirm(`Delete open incident #${incidentId}? This cannot be undone.`)) return;
      button.disabled = true;
      const error = document.getElementById("delete-error");
      error.hidden = true;
      try {
        const response = await fetch(`/api/incidents/${incidentId}`, { method: "DELETE" });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "The incident could not be deleted.");
        document.getElementById(`incident-row-${incidentId}`).remove();
      } catch (problem) {
        error.textContent = problem.message;
        error.hidden = false;
        button.disabled = false;
      }
    });
  });
}

function setupTryRewordedButton() {
  const button = document.getElementById("try-reworded");
  if (!button) return;
  button.addEventListener("click", async () => {
    const results = document.getElementById("reworded-result");
    const error = document.getElementById("reworded-error");
    button.disabled = true;
    button.textContent = "Rewording and asking…";
    error.hidden = true;
    try {
      const result = await requestJson(
        `/api/incidents/${button.dataset.incidentId}/try-reworded`,
        {}
      );
      document.getElementById("reworded-report").textContent = result.report;
      document.getElementById("reworded-seen-before").textContent =
        "Agent briefing";
      const incidentLink = document.getElementById("reworded-incident-link");
      incidentLink.href = result.url;
      renderAskBriefing("reworded", result.briefing);
      results.hidden = false;
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "Try a reworded version";
    }
  });
}

function showToast(message, type = "info", duration = 5000) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.append(container);
  }
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  const icon = document.createElement("span");
  icon.className = "toast-icon";
  toast.append(icon);
  const msg = document.createElement("span");
  msg.className = "toast-message";
  msg.textContent = message;
  toast.append(msg);
  const close = document.createElement("button");
  close.className = "toast-close";
  close.textContent = "×";
  close.setAttribute("aria-label", "Dismiss");
  close.addEventListener("click", () => { toast.remove(); });
  toast.append(close);
  container.append(toast);
  const timer = window.setTimeout(() => { toast.remove(); }, duration);
  toast.addEventListener("mouseenter", () => window.clearTimeout(timer));
  toast.addEventListener("mouseleave", () => { toast.remove(); });
}

function setupSlashShortcut() {
  document.addEventListener("keydown", (event) => {
    if (event.key !== "/") return;
    if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA" || event.target.isContentEditable) return;
    event.preventDefault();
    const askField = document.getElementById("ask-report") || document.getElementById("compare-report") || document.getElementById("change-description");
    if (askField) {
      askField.focus();
      askField.scrollIntoView({ block: "center" });
      showToast("Ask box focused", "info", 2000);
    }
  });
}

const DEMO_SCRIPT = [
  { title: "Ask a new problem", body: "Open Overview and describe a problem in the Ask box. The agent replies with general advice since no similar memory exists yet.", time: "0:05" },
  { title: "Save the fix", body: "Open the incident, run triage, then record the root cause and fix. Wait for \"Saved. The agent will recognise this next time.\"", time: "0:15" },
  { title: "Ask a reworded version", body: "Select \"Try a reworded version\". Groq paraphrases the report and re-runs triage.", time: "0:25" },
  { title: "See recall", body: "The reworded briefing now recalls the saved fix and shows source markers linked to the original incident.", time: "0:35" },
  { title: "Open the trail", body: "Open Memory trail to browse the resolved incident and its retention status.", time: "0:45" },
  { title: "Open replay", body: "Open Memory replay, choose the resolved incident, and run the checkpoint comparison.", time: "0:60" },
];

function setupPresenterMode() {
  const toggle = document.getElementById("presenter-toggle");
  const script = document.getElementById("presenter-script");
  if (!toggle || !script) return;
  let active = false;
  let activeIndex = -1;
  let timer = null;

  function render() {
    script.replaceChildren();
    DEMO_SCRIPT.forEach((step, index) => {
      const article = document.createElement("article");
      article.className = `presenter-step ${index === activeIndex ? "active" : ""}`;
      const header = document.createElement("div");
      header.style.display = "flex";
      header.style.alignItems = "center";
      header.style.gap = "10px";
      const num = document.createElement("span");
      num.className = "step-num";
      num.textContent = String(index + 1);
      const title = document.createElement("div");
      title.className = "step-title";
      title.textContent = step.title;
      header.append(num, title);
      article.append(header);
      const body = document.createElement("div");
      body.className = "step-body";
      body.textContent = step.body;
      article.append(body);
      const time = document.createElement("div");
      time.className = "step-time";
      time.textContent = step.time;
      article.append(time);
      script.append(article);
    });
  }

  function nextStep() {
    activeIndex += 1;
    if (activeIndex >= DEMO_SCRIPT.length) {
      activeIndex = -1;
      active = false;
      toggle.classList.remove("active");
      toggle.textContent = "Presenter";
      if (timer) { window.clearTimeout(timer); timer = null; }
      render();
      showToast("Demo script complete", "success", 3000);
      return;
    }
    render();
    const stepEl = script.children[activeIndex];
    if (stepEl) stepEl.scrollIntoView({ block: "nearest", inline: "start" });
    const ms = (activeIndex + 1) * 10000;
    timer = window.setTimeout(nextStep, ms);
  }

  toggle.addEventListener("click", () => {
    const banner = document.getElementById("presenter-banner");
    if (active) {
      active = false;
      toggle.classList.remove("active");
      toggle.textContent = "Presenter";
      if (timer) { window.clearTimeout(timer); timer = null; }
      activeIndex = -1;
      render();
      if (banner) banner.hidden = true;
      showToast("Presenter mode off", "info", 2000);
    } else {
      active = true;
      toggle.classList.add("active");
      toggle.textContent = "Stop demo";
      activeIndex = -1;
      render();
      if (banner) banner.hidden = false;
      showToast("Presenter mode — 60 second demo script", "info", 2500);
      nextStep();
    }
  });
  const closeButton = document.getElementById("presenter-close");
  if (closeButton) {
    closeButton.addEventListener("click", () => {
      toggle.click();
    });
  }
  render();
}

document.addEventListener("DOMContentLoaded", () => {
  setupLoginCounters();
  setupPasswordToggles();
  setupMemoryDrawer();
  setupOutcomeForm();
  setupOverviewFeed();
  setupAskForm();
  setupCharacterCounts();
  setupReportForm();
  setupStatusForm();
  setupResolutionForm();
  setupCompareForm();
  setupCompareRewordButton();
  setupHandoffCopy();
  setupDeleteButtons();
  setupTryRewordedButton();
  setupSlashShortcut();
  setupPresenterMode();

  const panel = document.getElementById("briefing-panel");
  if (!panel) return;
  document.getElementById("retry-triage").addEventListener("click", runTriage);
  if (panel.dataset.hasBriefing !== "true") runTriage();
});
