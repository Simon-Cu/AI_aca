const STAGE_LABELS = {
  intent_router: "意图识别",
  chart_react_agent: "图表解析",
  search_planner_agent: "检索规划",
  literature_react_agent: "文献检索",
  evidence_review_agent: "证据整理",
  report_agent: "结果汇总",
  orchestrator: "编排器",
  system: "系统",
};

const THREAD_STATUS_LABELS = {
  idle: "准备就绪",
  running: "执行中",
  completed: "已完成",
  needs_input: "等待补充",
  error: "执行异常",
  empty: "已清空",
};

const TRACE_FILTERS = {
  key: new Set([
    "intent_decision",
    "route_decision",
    "reasoning_summary",
    "branch_decision",
    "user_notice",
    "user_action_required",
    "error",
  ]),
  error: new Set(["user_notice", "user_action_required", "error"]),
};

const state = {
  threadId: createThreadId(),
  threadTitle: "新任务",
  threads: [],
  sharedState: null,
  traceEvents: [],
  traceFilter: "key",
  uploadedImageUrl: null,
  uploadedFileName: "",
  isRunning: false,
  currentRun: createRunState(),
};

const elements = {
  threadId: document.querySelector("#thread-id"),
  activeThreadTitle: document.querySelector("#active-thread-title"),
  threadStatusText: document.querySelector("#thread-status-text"),
  newThreadButton: document.querySelector("#new-thread-button"),
  renameThreadButton: document.querySelector("#rename-thread-button"),
  clearThreadButton: document.querySelector("#clear-thread-button"),
  threadSearch: document.querySelector("#thread-search"),
  threadList: document.querySelector("#thread-list"),
  uploadStrip: document.querySelector("#upload-strip"),
  uploadName: document.querySelector("#upload-name"),
  uploadStatus: document.querySelector("#upload-status"),
  fileInput: document.querySelector("#file-input"),
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#message-input"),
  topKInput: document.querySelector("#top-k-input"),
  maxStepsInput: document.querySelector("#max-steps-input"),
  sendButton: document.querySelector("#send-button"),
  progressSummary: document.querySelector("#progress-summary"),
  lightProgress: document.querySelector("#light-progress"),
  pipelineView: document.querySelector("#pipeline-view"),
  traceGroups: document.querySelector("#trace-groups"),
  traceFilters: Array.from(document.querySelectorAll(".trace-filter")),
  stateView: document.querySelector("#state-view"),
};

function createRunState() {
  return {
    assistantNode: null,
    assistantBuffer: "",
    progressNode: null,
    processNodes: {},
    noticeKeys: new Set(),
    chartBubbleShown: false,
  };
}

function createThreadId() {
  if (window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `thread-${Date.now()}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatInlineMarkdown(text) {
  let value = escapeHtml(text);
  value = value.replace(/`([^`]+)`/g, "<code>$1</code>");
  value = value.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return value;
}

function renderMarkdown(text) {
  const lines = String(text || "").split("\n");
  let html = "";
  let listItems = [];
  let paragraph = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html += `<p>${formatInlineMarkdown(paragraph.join(" "))}</p>`;
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length) return;
    html += `<ul>${listItems.map((item) => `<li>${formatInlineMarkdown(item)}</li>`).join("")}</ul>`;
    listItems = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }
    if (trimmed.startsWith("## ")) {
      flushParagraph();
      flushList();
      html += `<h2>${formatInlineMarkdown(trimmed.slice(3))}</h2>`;
      continue;
    }
    if (trimmed.startsWith("### ")) {
      flushParagraph();
      flushList();
      html += `<h3>${formatInlineMarkdown(trimmed.slice(4))}</h3>`;
      continue;
    }
    if (trimmed.startsWith("- ")) {
      flushParagraph();
      listItems.push(trimmed.slice(2));
      continue;
    }
    paragraph.push(trimmed);
  }

  flushParagraph();
  flushList();
  return html || `<p>${formatInlineMarkdown(text || "")}</p>`;
}

function getAgentLabel(agent) {
  return STAGE_LABELS[agent] || agent || "系统";
}

function getThreadStatusClass(status) {
  if (status === "completed") return "completed";
  if (status === "needs_input") return "needs_input";
  if (status === "error") return "error";
  if (status === "running") return "running";
  return "neutral";
}

function setThreadContext({ threadId, title, status }) {
  state.threadId = threadId;
  state.threadTitle = title || "新任务";
  elements.threadId.textContent = threadId;
  elements.activeThreadTitle.textContent = state.threadTitle;
  const label = THREAD_STATUS_LABELS[status] || THREAD_STATUS_LABELS.idle;
  elements.threadStatusText.textContent = label;
  elements.threadStatusText.className = `status-chip ${getThreadStatusClass(status)}`;
}

function setRunning(isRunning) {
  state.isRunning = isRunning;
  elements.sendButton.disabled = isRunning;
  elements.newThreadButton.disabled = isRunning;
  elements.renameThreadButton.disabled = isRunning;
  elements.clearThreadButton.disabled = isRunning;
  elements.fileInput.disabled = isRunning;
}

function createBaseMessage(role, title, tone = role) {
  const article = document.createElement("article");
  article.className = `message ${tone}`;

  if (title) {
    const head = document.createElement("div");
    head.className = "message-head";
    head.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(getTimeLabel())}</span>`;
    article.appendChild(head);
  }

  const body = document.createElement("div");
  body.className = "message-body";
  article.appendChild(body);
  elements.messages.appendChild(article);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return { article, body };
}

function getTimeLabel() {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function addTextMessage(role, content, options = {}) {
  const { article, body } = createBaseMessage(role, options.title, options.tone || role);
  body.textContent = content;
  return { article, body };
}

function addMarkdownMessage(role, content, options = {}) {
  const { article, body } = createBaseMessage(role, options.title, options.tone || role);
  body.classList.add("md");
  body.innerHTML = renderMarkdown(content);
  return { article, body };
}

function ensureProgressBubble() {
  if (state.currentRun.progressNode) {
    return state.currentRun.progressNode;
  }
  const details = document.createElement("details");
  details.className = "process-bubble";
  details.open = true;
  details.innerHTML = `
    <summary class="process-summary">
      <strong>执行进度</strong>
      <span>${escapeHtml(getTimeLabel())}</span>
    </summary>
    <div class="process-log">
      <div class="progress-bubble-summary">准备接收任务。</div>
      <div class="light-progress light-progress-inline"></div>
    </div>
  `;
  elements.messages.appendChild(details);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  state.currentRun.progressNode = details;
  return details;
}

function updateProgressBubble(sharedState) {
  const bubble = ensureProgressBubble();
  bubble.querySelector(".progress-bubble-summary").textContent = sharedState?.status_summary || "准备接收任务。";
  bubble.querySelector(".light-progress-inline").innerHTML = renderMiniStages(sharedState?.pipeline || []);
}

function createProcessBubble(agent) {
  if (state.currentRun.processNodes[agent]) {
    return state.currentRun.processNodes[agent];
  }
  const details = document.createElement("details");
  details.className = "process-bubble";
  details.open = true;
  details.innerHTML = `
    <summary class="process-summary">
      <strong>${escapeHtml(getAgentLabel(agent))}</strong>
      <span>执行中</span>
    </summary>
    <ul class="process-log"></ul>
  `;
  elements.messages.appendChild(details);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  state.currentRun.processNodes[agent] = {
    details,
    list: details.querySelector(".process-log"),
    summaryStatus: details.querySelector(".process-summary span"),
  };
  return state.currentRun.processNodes[agent];
}

function appendProcessLine(agent, text) {
  if (!agent || agent === "system") {
    return;
  }
  const bubble = createProcessBubble(agent);
  const item = document.createElement("li");
  item.textContent = text;
  bubble.list.appendChild(item);
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function completeProcessBubble(agent) {
  const bubble = state.currentRun.processNodes[agent];
  if (!bubble) {
    return;
  }
  bubble.summaryStatus.textContent = "已完成";
  bubble.details.open = false;
}

function updateSharedState(sharedState) {
  state.sharedState = sharedState;
  const threadStatus = sharedState?.pending_user_action
    ? "needs_input"
    : sharedState?.errors?.length
      ? "error"
      : sharedState?.final_answer
        ? "completed"
        : "running";
  setThreadContext({ threadId: state.threadId, title: state.threadTitle, status: threadStatus });
  elements.progressSummary.textContent = sharedState?.status_summary || "准备接收任务。";
  elements.lightProgress.innerHTML = renderMiniStages(sharedState?.pipeline || []);
  elements.pipelineView.innerHTML = renderPipeline(sharedState?.pipeline || []);
  renderStateCards(sharedState);
  renderTraceGroups();
  updateProgressBubble(sharedState);

  if (sharedState?.pending_user_action?.suggestions?.length) {
    elements.messageInput.placeholder = `补充关键词后继续，例如：${sharedState.pending_user_action.suggestions[0]}`;
  } else {
    elements.messageInput.placeholder = "输入你的任务，例如：解读这张图；或请帮我找和这张图相关的论文。";
  }
}

function renderMiniStages(pipeline) {
  return pipeline
    .map(
      (stage) =>
        `<span class="mini-stage ${escapeHtml(stage.status)}">${escapeHtml(stage.icon)} ${escapeHtml(stage.label)}</span>`
    )
    .join("");
}

function renderPipeline(pipeline) {
  if (!pipeline.length) {
    return `<p class="thread-item-preview">等待任务开始后生成流水线。</p>`;
  }

  const nodes = pipeline
    .map((stage, index) => {
      const connector = index < pipeline.length - 1 ? `<span class="pipeline-connector"></span>` : "";
      return `
        <div class="pipeline-track">
          <article class="pipeline-node ${escapeHtml(stage.status)}">
            <div class="pipeline-node-header">
              <span>${escapeHtml(stage.icon)}</span>
              <strong>${escapeHtml(stage.label)}</strong>
            </div>
            <p>${escapeHtml(stage.description)}</p>
          </article>
          ${connector}
        </div>
      `;
    })
    .join("");

  return nodes;
}

function renderStateCards(sharedState) {
  if (!sharedState) {
    elements.stateView.innerHTML = "";
    return;
  }

  const sections = [
    {
      key: "task",
      title: "任务摘要",
      open: true,
      count: sharedState.intent ? 1 : 0,
      body: `
        <p><strong>任务类型：</strong>${escapeHtml(sharedState.task_type || "未识别")}</p>
        <p><strong>状态：</strong>${escapeHtml(sharedState.status_summary || "准备接收任务")}</p>
        <p><strong>图表摘要：</strong>${escapeHtml(sharedState.chart_summary || "暂无")}</p>
      `,
    },
    {
      key: "queries",
      title: "检索词",
      open: true,
      count: sharedState.search_queries?.length || 0,
      body: renderList(sharedState.search_queries || [], "暂无检索词"),
    },
    {
      key: "papers",
      title: "文献候选",
      open: true,
      count: sharedState.papers?.length || 0,
      body: renderPaperSection(sharedState),
    },
    {
      key: "evidence",
      title: "证据说明",
      open: false,
      count: sharedState.evidence_notes?.length || 0,
      body: renderList(
        (sharedState.evidence_notes || []).map((note) => `${note.title || "未命名"}：${note.reason || note.risk || ""}`),
        "暂无证据说明"
      ),
    },
    {
      key: "notice",
      title: "提示与人工介入",
      open: Boolean(sharedState.pending_user_action),
      count: (sharedState.notices?.length || 0) + (sharedState.pending_user_action ? 1 : 0),
      body: renderNoticeSection(sharedState),
    },
    {
      key: "errors",
      title: "异常信息",
      open: Boolean(sharedState.errors?.length),
      count: sharedState.errors?.length || 0,
      body: renderList(sharedState.errors || [], "暂无异常", true),
    },
  ];

  elements.stateView.innerHTML = sections
    .map(
      (section) => `
        <details class="state-card" ${section.open ? "open" : ""}>
          <summary>
            <strong>${escapeHtml(section.title)}</strong>
            <span class="counter">${escapeHtml(String(section.count))}</span>
          </summary>
          <div class="state-card-body">${section.body}</div>
        </details>
      `
    )
    .join("");
}

function renderList(items, emptyText, isDanger = false) {
  if (!items.length) {
    return `<p${isDanger ? ' class="status-danger"' : ""}>${escapeHtml(emptyText)}</p>`;
  }
  return `<ul>${items.map((item) => `<li${isDanger ? ' class="status-danger"' : ""}>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderPaperSection(sharedState) {
  const papers = sharedState.papers || [];
  if (!papers.length) {
    return "<p>暂无文献候选</p>";
  }

  const list = papers
    .map(
      (paper) => `
        <li>
          ${
            sharedState.pending_user_action
              ? `<label><input type="checkbox" class="paper-select" value="${escapeHtml(paper.title || "")}" checked /> ${escapeHtml(
                  `${paper.title || "未命名"} (${paper.year || "n/a"})`
                )}</label>`
              : escapeHtml(`${paper.title || "未命名"} (${paper.year || "n/a"})`)
          }
        </li>
      `
    )
    .join("");

  const action = sharedState.pending_user_action
    ? `<button type="button" class="trace-filter is-active" id="manual-continue-button">使用选中文献继续</button>`
    : "";

  return `<ul>${list}</ul>${action}`;
}

function renderNoticeSection(sharedState) {
  const fragments = [];
  if (sharedState.pending_user_action) {
    fragments.push(
      `<p><strong>${escapeHtml(sharedState.pending_user_action.title)}</strong></p><p>${escapeHtml(sharedState.pending_user_action.message)}</p>`
    );
    fragments.push(
      renderList(sharedState.pending_user_action.suggestions || [], "暂无建议")
    );
  }
  if (sharedState.notices?.length) {
    fragments.push(
      `<ul>${sharedState.notices
        .map(
          (notice) =>
            `<li><strong>${escapeHtml(notice.title || "提示")}</strong>：${escapeHtml(notice.message || "")}</li>`
        )
        .join("")}</ul>`
    );
  }
  return fragments.join("") || "<p>暂无提示。</p>";
}

function matchesTraceFilter(event) {
  if (state.traceFilter === "all") {
    return true;
  }
  const filterSet = TRACE_FILTERS[state.traceFilter];
  if (!filterSet) {
    return true;
  }
  return filterSet.has(event.type);
}

function traceEventText(event) {
  if (event.type === "route_decision") {
    return `路由到 ${getAgentLabel(event.next_agent)}：${event.reason || ""}`;
  }
  if (event.type === "action_start") {
    return `${event.tool || "动作"}：${event.input || ""}`;
  }
  if (event.type === "user_notice" || event.type === "user_action_required") {
    return `${event.title || "提示"}：${event.message || ""}`;
  }
  return event.message || event.reason || "";
}

function renderTraceGroups() {
  const grouped = new Map();
  for (const event of state.traceEvents.filter(matchesTraceFilter)) {
    const agent = event.agent || "system";
    if (!grouped.has(agent)) {
      grouped.set(agent, []);
    }
    grouped.get(agent).push(event);
  }

  const currentAgent = state.sharedState?.current_agent;
  const html = Array.from(grouped.entries())
    .reverse()
    .map(([agent, events]) => {
      const hasAlert = events.some((event) => ["error", "user_notice", "user_action_required"].includes(event.type));
      const isOpen = agent === currentAgent || hasAlert;
      return `
        <details class="trace-group" ${isOpen ? "open" : ""}>
          <summary>
            <strong>${escapeHtml(getAgentLabel(agent))}</strong>
            <span class="trace-group-meta">
              <span>${escapeHtml(String(events.length))} 条事件</span>
              <span>${escapeHtml(events[events.length - 1]?.type || "")}</span>
            </span>
          </summary>
          <div class="trace-event-list">
            ${events
              .map(
                (event) => `
                  <article class="trace-event ${escapeHtml(event.level || event.type)}">
                    <strong>${escapeHtml(event.type)}</strong>
                    <p>${escapeHtml(traceEventText(event))}</p>
                  </article>
                `
              )
              .join("")}
          </div>
        </details>
      `;
    })
    .join("");

  elements.traceGroups.innerHTML = html || `<p class="thread-item-preview">暂无 Trace 事件。</p>`;
}

function recordTraceEvent(event) {
  state.traceEvents.push(event);
  renderTraceGroups();
}

function statusFromSharedState(sharedState) {
  if (!sharedState) return "idle";
  if (sharedState.pending_user_action) return "needs_input";
  if (sharedState.errors?.length) return "error";
  if (sharedState.final_answer) return "completed";
  return "running";
}

function buildThreadItemHtml(thread) {
  const statusLabel = THREAD_STATUS_LABELS[thread.status] || THREAD_STATUS_LABELS.idle;
  return `
    <article class="thread-item ${thread.thread_id === state.threadId ? "is-active" : ""}" data-thread-id="${escapeHtml(
      thread.thread_id
    )}">
      <div class="thread-item-header">
        <div class="thread-item-title" data-action="select">${escapeHtml(thread.title)}</div>
        <span class="status-chip ${escapeHtml(getThreadStatusClass(thread.status))}">${escapeHtml(statusLabel)}</span>
      </div>
      <div class="thread-item-preview" data-action="select">${escapeHtml(thread.last_preview || "暂无摘要")}</div>
      <div class="thread-item-actions">
        <button type="button" data-action="rename">重命名</button>
        <button type="button" class="danger" data-action="delete">删除</button>
      </div>
    </article>
  `;
}

function renderThreadList() {
  const keyword = (elements.threadSearch.value || "").trim().toLowerCase();
  const filtered = state.threads.filter((thread) => {
    if (!keyword) return true;
    return `${thread.title} ${thread.last_preview}`.toLowerCase().includes(keyword);
  });
  elements.threadList.innerHTML = filtered.map(buildThreadItemHtml).join("") || "<p class=\"thread-item-preview\">暂无历史线程。</p>";
}

async function fetchThreads() {
  const response = await fetch("/api/v1/threads");
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  state.threads = payload.threads || [];
  const currentThread = state.threads.find((thread) => thread.thread_id === state.threadId);
  if (currentThread) {
    state.threadTitle = currentThread.title;
    setThreadContext({ threadId: state.threadId, title: currentThread.title, status: currentThread.status });
  }
  renderThreadList();
}

function resetComposerUpload() {
  state.uploadedImageUrl = null;
  state.uploadedFileName = "";
  elements.uploadStrip.hidden = true;
  elements.uploadName.textContent = "";
  elements.uploadStatus.textContent = "";
  elements.fileInput.value = "";
}

function resetThreadView() {
  elements.messages.innerHTML = "";
  elements.pipelineView.innerHTML = "";
  elements.traceGroups.innerHTML = "";
  elements.stateView.innerHTML = "";
  elements.lightProgress.innerHTML = "";
  elements.progressSummary.textContent = "准备接收任务。";
  state.sharedState = null;
  state.traceEvents = [];
  state.currentRun = createRunState();
  resetComposerUpload();
}

function startNewThread() {
  resetThreadView();
  setThreadContext({ threadId: createThreadId(), title: "新任务", status: "idle" });
  addTextMessage("system", "新线程已创建。发送第一条消息后，它会出现在左侧历史列表中。", {
    tone: "system",
  });
  renderThreadList();
}

function hydrateConversation(messages) {
  elements.messages.innerHTML = "";
  for (const message of messages) {
    if (message.role === "assistant") {
      addMarkdownMessage("assistant", message.content, { title: "最终报告", tone: "assistant" });
    } else if (message.role === "user") {
      addTextMessage("user", message.content, { title: "用户输入" });
    }
  }
}

async function loadThread(threadId) {
  const response = await fetch(`/api/v1/threads/${encodeURIComponent(threadId)}`);
  if (!response.ok) {
    return;
  }
  const detail = await response.json();
  resetThreadView();
  setThreadContext({
    threadId: detail.thread.thread_id,
    title: detail.thread.title,
    status: detail.thread.status,
  });
  hydrateConversation(detail.messages || []);
  state.traceEvents = detail.trace || [];
  if (detail.state) {
    updateSharedState(detail.state);
  } else {
    renderTraceGroups();
  }
}

async function renameCurrentThread() {
  const currentTitle = state.threadTitle || "新任务";
  const nextTitle = window.prompt("输入新的线程标题：", currentTitle);
  if (!nextTitle || !nextTitle.trim()) {
    return;
  }
  const response = await fetch(`/api/v1/threads/${encodeURIComponent(state.threadId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: nextTitle.trim() }),
  });
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  if (payload.thread) {
    setThreadContext({
      threadId: payload.thread.thread_id,
      title: payload.thread.title,
      status: payload.thread.status,
    });
  }
  await fetchThreads();
}

async function deleteThreadById(threadId) {
  const confirmed = window.confirm("删除后将移除该线程的历史消息、流程状态和 Trace 记录，是否继续？");
  if (!confirmed) {
    return;
  }
  await fetch(`/api/v1/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
  if (threadId === state.threadId) {
    startNewThread();
  }
  await fetchThreads();
}

async function continueWithSelectedPapers() {
  const selected = Array.from(document.querySelectorAll(".paper-select:checked"))
    .map((input) => input.value)
    .filter(Boolean);

  if (!selected.length) {
    showNoticeBubble({
      type: "user_notice",
      title: "未选择文献",
      message: "请至少保留一篇候选文献，再继续执行后续总结。",
      suggestions: [],
    });
    return;
  }

  const response = await fetch(`/api/v1/threads/${encodeURIComponent(state.threadId)}/manual-continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selected_papers: selected }),
  });
  if (!response.ok) {
    showNoticeBubble({
      type: "error",
      title: "人工继续失败",
      message: "无法根据手动筛选结果继续执行，请稍后重试。",
      suggestions: [],
    });
    return;
  }

  const detail = await response.json();
  resetThreadView();
  setThreadContext({
    threadId: detail.thread.thread_id,
    title: detail.thread.title,
    status: detail.thread.status,
  });
  hydrateConversation(detail.messages || []);
  state.traceEvents = detail.trace || [];
  if (detail.state) {
    updateSharedState(detail.state);
  }
  await fetchThreads();
}

async function clearCurrentThread() {
  await fetch(`/api/v1/chat/messages?thread_id=${encodeURIComponent(state.threadId)}`, { method: "DELETE" });
  resetThreadView();
  setThreadContext({ threadId: state.threadId, title: state.threadTitle, status: "empty" });
  addTextMessage("system", "当前线程已清空。你可以继续在同一线程里开始新的任务。", { tone: "system" });
  await fetchThreads();
}

async function uploadImage(file) {
  const presignResponse = await fetch(`/api/v1/oss/presign?filename=${encodeURIComponent(file.name)}`);
  if (!presignResponse.ok) {
    throw new Error("无法获取上传地址，请检查 OSS 配置。");
  }

  const payload = await presignResponse.json();
  const uploadResponse = await fetch(payload.uploadUrl, {
    method: "PUT",
    headers: {
      "Content-Type": payload.contentType,
    },
    body: file,
  });

  if (!uploadResponse.ok) {
    throw new Error("图片上传到 OSS 失败。");
  }

  return payload.accessUrl;
}

async function handleFileSelection(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) {
    return;
  }

  elements.uploadStrip.hidden = false;
  elements.uploadName.textContent = file.name;
  elements.uploadStatus.textContent = "上传中...";

  try {
    const accessUrl = await uploadImage(file);
    state.uploadedImageUrl = accessUrl;
    state.uploadedFileName = file.name;
    elements.uploadStatus.textContent = "已上传";
    addTextMessage("system", `图表图片已上传：${file.name}`, { tone: "system" });
  } catch (error) {
    state.uploadedImageUrl = null;
    elements.uploadStatus.textContent = "上传失败";
    addTextMessage("warning", error.message || "图片上传失败。", {
      title: "上传失败",
      tone: "warning",
    });
  } finally {
    event.target.value = "";
  }
}

async function streamWorkflow(payload, onEvent) {
  const response = await fetch("/api/v1/chat/react-stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    throw new Error(`工作流请求失败，状态码 ${response.status}。`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    while (buffer.includes("\n\n")) {
      const boundary = buffer.indexOf("\n\n");
      const rawChunk = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (!rawChunk) continue;

      const jsonPayload = rawChunk
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");

      if (!jsonPayload) continue;
      onEvent(JSON.parse(jsonPayload));
    }
  }
}

function showNoticeBubble(event) {
  const key = `${event.type}:${event.title || ""}:${event.message || ""}`;
  if (state.currentRun.noticeKeys.has(key)) {
    return;
  }
  state.currentRun.noticeKeys.add(key);
  const suggestions = event.suggestions?.length
    ? `\n\n建议：\n${event.suggestions.map((item) => `- ${item}`).join("\n")}`
    : "";
  addMarkdownMessage("warning", `## ${event.title || "提示"}\n${event.message || ""}${suggestions}`, {
    title: "执行提示",
    tone: "warning",
  });
}

function updateAssistantPreview() {
  if (!state.currentRun.assistantNode) {
    return;
  }
  state.currentRun.assistantNode.body.textContent = state.currentRun.assistantBuffer || "正在整理最终结论...";
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function finalizeAssistantMessage() {
  if (!state.currentRun.assistantNode) {
    return;
  }
  state.currentRun.assistantNode.body.classList.add("md");
  state.currentRun.assistantNode.body.innerHTML = renderMarkdown(state.currentRun.assistantBuffer || "本轮没有返回结果。");
}

function maybeShowChartSummaryBubble(event) {
  if (state.currentRun.chartBubbleShown) {
    return;
  }
  const summary = event.changes?.chart_summary;
  if (!summary) {
    return;
  }
  const extractedCount = event.changes?.extracted_elements?.length || 0;
  addMarkdownMessage("note", `## 图表解析结论\n${summary}\n\n- 抽取到 ${extractedCount} 个关键元素`, {
    title: "图表解析",
    tone: "note",
  });
  state.currentRun.chartBubbleShown = true;
}

function eventToProcessText(event) {
  if (event.type === "action_start") {
    return `动作：${event.tool || "unknown"}。`;
  }
  if (event.type === "route_decision") {
    return `路由结果：转到 ${getAgentLabel(event.next_agent)}。`;
  }
  if (event.type === "branch_decision") {
    return event.message || "触发条件分支。";
  }
  if (event.type === "observation" || event.type === "reasoning_summary") {
    return event.message || "";
  }
  if (event.type === "user_notice" || event.type === "user_action_required") {
    return `${event.title || "提示"}：${event.message || ""}`;
  }
  if (event.type === "error") {
    return event.message || "执行失败。";
  }
  return traceEventText(event);
}

function handleWorkflowEvent(event) {
  if (event.state) {
    updateSharedState(event.state);
  }

  switch (event.type) {
    case "session_ready":
      if (event.thread) {
        setThreadContext({
          threadId: event.thread.thread_id,
          title: event.thread.title,
          status: event.thread.status,
        });
      }
      break;
    case "progress_update":
      if (event.state) {
        updateSharedState(event.state);
      }
      break;
    case "agent_start":
      recordTraceEvent(event);
      appendProcessLine(event.agent, `开始执行 ${getAgentLabel(event.agent)}。`);
      break;
    case "agent_end":
      recordTraceEvent(event);
      appendProcessLine(event.agent, `${getAgentLabel(event.agent)} 已完成。`);
      completeProcessBubble(event.agent);
      break;
    case "route_decision":
    case "intent_decision":
    case "reasoning_summary":
    case "action_start":
    case "observation":
    case "branch_decision":
      recordTraceEvent(event);
      appendProcessLine(event.agent, eventToProcessText(event));
      break;
    case "state_update":
      recordTraceEvent(event);
      maybeShowChartSummaryBubble(event);
      break;
    case "user_notice":
    case "user_action_required":
      recordTraceEvent(event);
      appendProcessLine(event.agent, eventToProcessText(event));
      showNoticeBubble(event);
      break;
    case "error":
      recordTraceEvent(event);
      appendProcessLine(event.agent, eventToProcessText(event));
      showNoticeBubble({
        ...event,
        title: "执行失败",
        message: event.message || "工作流执行失败。",
      });
      break;
    case "final_token":
      state.currentRun.assistantBuffer += event.content || "";
      updateAssistantPreview();
      break;
    case "done":
      finalizeAssistantMessage();
      recordTraceEvent({ ...event, message: "本轮执行结束。" });
      break;
    default:
      break;
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  if (state.isRunning) {
    return;
  }

  const message = elements.messageInput.value.trim();
  if (!message) {
    return;
  }

  state.currentRun = createRunState();
  addTextMessage("user", message, { title: "用户输入" });
  ensureProgressBubble();
  state.currentRun.assistantNode = addTextMessage("assistant", "正在整理最终结论...", {
    title: "最终报告",
    tone: "assistant",
  });
  elements.messageInput.value = "";
  setRunning(true);

  try {
    await streamWorkflow(
      {
        message,
        image_url: state.uploadedImageUrl,
        thread_id: state.threadId,
        top_k: Number(elements.topKInput.value || 5),
        max_react_steps: Number(elements.maxStepsInput.value || 8),
      },
      handleWorkflowEvent
    );
    await fetchThreads();
  } catch (error) {
    state.currentRun.assistantBuffer = "";
    if (state.currentRun.assistantNode) {
      state.currentRun.assistantNode.body.textContent = error.message || "工作流请求失败。";
    }
    showNoticeBubble({
      type: "error",
      title: "请求失败",
      message: error.message || "工作流请求失败。",
      suggestions: ["确认服务仍在运行", "检查网络或 API 配置"],
    });
  } finally {
    setRunning(false);
  }
}

elements.fileInput.addEventListener("change", handleFileSelection);
elements.composer.addEventListener("submit", handleSubmit);
elements.newThreadButton.addEventListener("click", startNewThread);
elements.renameThreadButton.addEventListener("click", renameCurrentThread);
elements.clearThreadButton.addEventListener("click", clearCurrentThread);
elements.threadSearch.addEventListener("input", renderThreadList);
elements.threadList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  const item = event.target.closest("[data-thread-id]");
  if (!button || !item) {
    return;
  }
  const threadId = item.dataset.threadId;
  const action = button.dataset.action;
  if (action === "select") {
    await loadThread(threadId);
    renderThreadList();
  } else if (action === "rename") {
    const current = state.threads.find((thread) => thread.thread_id === threadId);
    const nextTitle = window.prompt("输入新的线程标题：", current?.title || "");
    if (!nextTitle || !nextTitle.trim()) {
      return;
    }
    await fetch(`/api/v1/threads/${encodeURIComponent(threadId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: nextTitle.trim() }),
    });
    if (threadId === state.threadId) {
      setThreadContext({ threadId, title: nextTitle.trim(), status: statusFromSharedState(state.sharedState) });
    }
    await fetchThreads();
  } else if (action === "delete") {
    await deleteThreadById(threadId);
  }
});

elements.stateView.addEventListener("click", async (event) => {
  const button = event.target.closest("#manual-continue-button");
  if (!button) {
    return;
  }
  await continueWithSelectedPapers();
});

elements.traceFilters.forEach((button) => {
  button.addEventListener("click", () => {
    state.traceFilter = button.dataset.filter;
    elements.traceFilters.forEach((item) => item.classList.toggle("is-active", item === button));
    renderTraceGroups();
  });
});

(async function bootstrap() {
  setThreadContext({ threadId: state.threadId, title: "新任务", status: "idle" });
  addTextMessage("system", "这里会以中文展示多智能体执行过程、历史线程与人工介入提示。", {
    tone: "system",
  });
  await fetchThreads();
})();
