const $ = selector => document.querySelector(selector);
const token = location.hash.slice(1);
let queueVersion = "";
let queueItems = [];
let reviewSupported = false;

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "X-Desktop-Token": token,
      ...(body === undefined ? {} : { "Content-Type": "application/json" })
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function message(text, isError = false) {
  $("#notice").textContent = text;
  $("#notice").className = isError ? "warning" : "muted";
}

function showWorkspace(status) {
  $("#workspace-setup").classList.toggle("hidden", !!status.workspace);
  $("#dashboard").classList.toggle("hidden", !status.workspace);
  $("#workspace-name").textContent = status.workspace || "Choose an existing workspace";
  if (status.suggested && !$("#workspace-path").value) {
    $("#workspace-path").value = status.suggested;
  }
}

async function selectWorkspace() {
  try {
    const status = await api("/api/workspace", { path: $("#workspace-path").value });
    $("#workspace-error").textContent = "";
    showWorkspace(status);
    await loadStats();
  } catch (error) {
    $("#workspace-error").textContent = error.message;
  }
}

$("#select-workspace").onclick = selectWorkspace;
$("#browse").onclick = async () => {
  if (!window.pywebview?.api) {
    $("#workspace-error").textContent = "Enter the folder path, then choose Use folder.";
    return;
  }
  const path = await window.pywebview.api.choose_workspace();
  if (path) {
    $("#workspace-path").value = path;
    await selectWorkspace();
  }
};
$("#change-workspace").onclick = () => {
  $("#workspace-path").value = $("#workspace-name").textContent;
  $("#workspace-setup").classList.remove("hidden");
};

async function loadStats() {
  try {
    const stats = await api("/api/stats");
    const metrics = [["Researchers", stats.counts.total], ["With email", stats.counts.with_email],
      ["Drafted", stats.counts.drafted], ["Sent", stats.sent], ["Review copies", stats.review_sent]];
    $("#metrics").replaceChildren(...metrics.map(([label, count]) => {
      const card = document.createElement("div");
      card.className = "metric";
      const value = document.createElement("b");
      value.textContent = count;
      card.append(value, document.createTextNode(label));
      return card;
    }));
    $("#stats-updated").textContent = `Workbook updated ${new Date(stats.modified * 1000).toLocaleString()}.`;
    message("");
  } catch (error) { message(error.message, true); }
}

async function loadConversations() {
  try {
    const data = await api("/api/conversations");
    $("#conversations-frame").srcdoc = data.html;
    $("#conversations-updated").textContent =
      `Showing saved file from ${new Date(data.modified * 1000).toLocaleString()}.`;
    message("");
  } catch (error) { message(error.message, true); }
}

function element(tag, text, className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}

function renderQueue() {
  $("#queue-count").textContent = `${queueItems.length} items · ${queueItems.filter(x => !x.sent_at).length} unsent`;
  const drafts = $("#drafts");
  drafts.replaceChildren();
  queueItems.forEach((item, index) => {
    const sent = !!item.sent_at;
    const card = element("article", "", "draft" + (sent ? " sent" : ""));
    const title = element("h3", `${item.name || "Unknown"} · ${item.email || "No email"}`);
    const detail = element("p", `${item.action || "No action"} · ${item.subject || "No subject"} · ${sent ? "Sent " + item.sent_at : "Not sent"}`, "muted");
    const incoming = element("pre", item.their_message || "(No incoming text)");
    const summary = element("p", item.summary || "", "muted");
    const body = document.createElement("textarea");
    body.value = item.body || "";
    body.setAttribute("aria-label", `Draft for ${item.name || index}`);
    body.readOnly = sent;
    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = !!item.approved;
    check.disabled = sent || !reviewSupported || !item.body || item.action === "none";
    const label = element("label", " Approved for the separate scheduled CLI");
    label.prepend(check);
    const status = element("span", sent ? "Sent; read-only" : "", "status");
    const save = element("button", "Save this draft");
    save.disabled = sent || !reviewSupported;
    body.oninput = () => {
      if (body.value !== item.body) check.checked = false;
      check.disabled = sent || !reviewSupported || !body.value.trim() || item.action === "none";
    };
    save.onclick = async () => {
      if (check.checked && !confirm("Approve this draft? Your separate scheduled v2 CLI may send it later. This app does not send.")) return;
      try {
        const result = await api(`/api/queue/${index}`, {
          version: queueVersion, body: body.value, approved: check.checked
        });
        queueVersion = result.version;
        status.textContent = "Saved; reload to see disk state.";
        await loadQueue();
      } catch (error) {
        status.textContent = error.message + " (reload queue before retrying)";
      }
    };
    const actions = document.createElement("div");
    actions.className = "row";
    actions.append(label, save, status);
    card.append(title, detail, summary, incoming, body, actions);
    drafts.append(card);
  });
}

async function loadQueue() {
  try {
    const data = await api("/api/queue");
    queueVersion = data.version;
    queueItems = data.items;
    reviewSupported = data.review_supported;
    renderQueue();
    message(reviewSupported ? "" : "Update the selected v2 CLI to enable coordinated reply editing.",
            !reviewSupported);
  } catch (error) { message(error.message, true); }
}

$("#refresh-stats").onclick = loadStats;
$("#refresh-conversations").onclick = loadConversations;
$("#refresh-queue").onclick = loadQueue;
document.querySelectorAll("nav [data-tab]").forEach(button => button.onclick = () => {
  document.querySelectorAll("nav [data-tab]").forEach(item => item.classList.toggle("active", item === button));
  document.querySelectorAll(".tab").forEach(panel =>
    panel.classList.toggle("hidden", panel.id !== button.dataset.tab));
  if (button.dataset.tab === "overview") loadStats();
  if (button.dataset.tab === "conversations") loadConversations();
  if (button.dataset.tab === "queue") loadQueue();
});

api("/api/status").then(status => {
  showWorkspace(status);
  if (status.workspace) loadStats();
}).catch(error => message(error.message, true));
