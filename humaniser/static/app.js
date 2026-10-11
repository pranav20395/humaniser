"use strict";

const $ = (id) => document.getElementById(id);
const els = {
  draft: $("draft"), output: $("output"), go: $("go"), retry: $("retry"), highlight: $("highlight"),
  copy: $("copy"), clear: $("clear"), examples: $("examples"), draftCount: $("draft-count"),
  outCount: $("out-count"), progress: $("progress"), report: $("report"), checks: $("checks"),
  status: $("status"), statusText: $("status-text"), shortcut: $("shortcut"),
};

const EXAMPLES = {
  email: `Subject: Update on the Q3 Customer Onboarding Project

Hi team,

I hope this message finds you well. I wanted to take a moment to provide a comprehensive update on the progress of our Q3 customer onboarding initiative.

As of October 6, we have successfully onboarded 142 new accounts, representing a 23% increase compared to the same period last quarter. Additionally, the average time to first value has decreased from 9 days to 6.5 days, which is a significant improvement that reflects the hard work and dedication of everyone involved.

However, it is important to note that there are still a few challenges that we need to address. Specifically, 18 accounts are currently experiencing delays due to incomplete data migration, and the support team has reported a 12% rise in tickets related to SSO configuration.

Moving forward, I would recommend that we prioritize the data migration backlog and schedule a working session with the IT team before October 20. Please don't hesitate to reach out if you have any questions or concerns.

Best regards,
Priya`,
  essay: `In today's fast-paced digital landscape, remote work has emerged as a transformative force that is fundamentally reshaping the way organizations operate. According to a 2023 survey by Owl Labs, 62% of full-time employees in the United States reported working remotely at least part of the time. This shift offers numerous benefits, including increased flexibility, reduced commuting time, and access to a broader talent pool. However, it is essential to recognize that remote work also presents significant challenges, such as feelings of isolation and difficulties in maintaining clear communication. Ultimately, organizations that strike the right balance between flexibility and connection will be best positioned to thrive in this evolving environment.`,
  zh: `各位同事：

大家好！为了进一步提升团队的协作效率，经过综合考虑，公司决定自11月1日起正式启用新的项目管理系统。新系统将全面覆盖任务分配、进度跟踪以及文档管理等核心功能，预计可将跨部门沟通时间缩短约30%。

在此过程中，请各部门负责人于10月25日前完成成员账号的申请，并组织本部门员工参加为期2小时的线上培训。值得注意的是，旧系统中的数据将在10月31日统一迁移，迁移期间系统将暂停使用。

如有任何疑问，欢迎随时与信息技术部联系。感谢大家的理解与支持！`,
};

const CJK = "\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff";
const CJK_RE = new RegExp(`[${CJK}]`, "g");
// Same number pattern and normalization as humaniser/checks.py.
const NUMBER_SRC = "(?<![A-Za-z0-9.])(\\d{1,3}(?:,\\d{3})+|\\d+)(\\.\\d+)?([kK](?![A-Za-z])|万)?";
const TOKEN_RE = new RegExp(`${NUMBER_SRC}|([${CJK}]|[\\p{L}\\p{N}]+(?:['’]\\p{L}+)*)`, "gu");

let run = null;   // the rewrite in progress or last finished

function countWords(text) {
  const cjk = (text.match(CJK_RE) || []).length;
  const words = (text.replace(CJK_RE, " ").match(/[\p{L}\p{N}]+/gu) || []).length;
  if (!cjk) return `${words} word${words === 1 ? "" : "s"}`;
  return words ? `${cjk} characters, ${words} words` : `${cjk} characters`;
}

function normalizeNumber(whole, frac, suffix) {
  let value = whole.replace(/,/g, "") + (frac || "");
  if (suffix) {
    return String(Math.round(parseFloat(value) * (suffix === "万" ? 10000 : 1000) * 1e6) / 1e6);
  }
  if (value.includes(".")) value = value.replace(/0+$/, "").replace(/\.$/, "");
  return value.replace(/^0+/, "") || "0";
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* Mark words of the rewrite that are not in the draft, and numbers the draft doesn't have. */
function highlight(draft, text, addedNumbers) {
  const known = new Set();
  for (const m of draft.matchAll(TOKEN_RE)) known.add((m[4] || m[0]).toLowerCase());
  const added = new Set(addedNumbers);
  const parts = [];   // [string, class|null]
  let last = 0;
  for (const m of text.matchAll(TOKEN_RE)) {
    if (m.index > last) parts.push([text.slice(last, m.index), "gap"]);
    let cls = null;
    if (m[1] !== undefined) {
      if (added.has(normalizeNumber(m[1], m[2], m[3]))) cls = "num";
    } else if (!known.has(m[4].toLowerCase())) {
      cls = "new";
    }
    parts.push([m[0], cls]);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push([text.slice(last), "gap"]);
  // A gap between two new words joins them into one mark, unless it holds a line break.
  for (let i = 1; i < parts.length - 1; i++) {
    if (parts[i][1] === "gap") {
      parts[i][1] = parts[i - 1][1] === "new" && parts[i + 1][1] === "new" && !parts[i][0].includes("\n") ? "new" : null;
    }
  }
  let html = "";
  for (let i = 0; i < parts.length;) {
    const cls = parts[i][1] === "gap" ? null : parts[i][1];
    let chunk = "";
    while (i < parts.length && (parts[i][1] === "gap" ? null : parts[i][1]) === cls) chunk += parts[i++][0];
    html += cls ? `<mark class="${cls}">${escapeHtml(chunk)}</mark>` : escapeHtml(chunk);
  }
  return html;
}

function currentText() {
  if (!run) return "";
  if (run.final !== null) return run.final;
  return run.segments.map((s, i) => (i ? s.joiner : "") + (s.kind === "keep" ? s.text : run.outputs[i].trimStart())).join("");
}

let renderQueued = false;
function render() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    if (!run) return;
    const text = currentText();
    const out = els.output;
    out.classList.remove("error");
    if (run.final !== null) {
      out.classList.toggle("plain", !els.highlight.checked);
      out.innerHTML = highlight(run.draft, text, run.checks ? run.checks.added_numbers : []);
    } else {
      out.classList.add("plain");
      out.textContent = text;
      const caret = document.createElement("span");
      caret.className = "caret";
      out.appendChild(caret);
      const nearBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 80;
      if (nearBottom) out.scrollTop = out.scrollHeight;
    }
    els.outCount.textContent = text ? countWords(text) : "";
  });
}

function setRunning(running) {
  els.go.classList.toggle("running", running);
  els.go.querySelector(".label").textContent = running ? "Stop" : (run && run.final !== null ? "Rewrite again" : "Humanize");
  els.draft.readOnly = running;
  els.copy.disabled = running || !(run && run.final);
}

function showError(message) {
  els.output.classList.add("error");
  els.output.textContent = message;
  els.progress.textContent = "";
}

const REASONS = { language: "came back in the wrong language, sampling again", retry: "a check failed, sampling once more" };

function handle(ev) {
  switch (ev.type) {
    case "start":
      run.segments = ev.segments;
      run.outputs = ev.segments.map(() => "");
      run.pieces = ev.pieces;
      run.prose = ev.segments.map((s, i) => (s.kind === "prose" ? i : -1)).filter((i) => i >= 0);
      break;
    case "attempt": {
      run.outputs[ev.index] = "";
      const n = run.prose.indexOf(ev.index) + 1;
      const where = run.pieces > 1 ? `Piece ${n} of ${run.pieces}` : "Writing";
      els.progress.textContent = ev.reason === "first" ? `${where}…` : `${where}: ${REASONS[ev.reason]}…`;
      break;
    }
    case "token":
      run.outputs[ev.index] += ev.text;
      break;
    case "piece_done":
      run.outputs[ev.index] = ev.text;
      run.pieceReports.push(ev);
      break;
    case "done":
      run.final = ev.text;
      run.checks = ev.checks;
      run.seconds = ev.seconds;
      els.progress.textContent = `Done in ${ev.seconds}s`;
      showChecks();
      break;
    case "error":
      run.error = ev.message;
      break;
  }
  render();
}

async function humanize() {
  if (run && run.controller) {           // Stop
    run.controller.abort();
    return;
  }
  const draft = els.draft.value;
  if (!draft.trim()) {
    els.draft.focus();
    return;
  }
  run = { draft, controller: new AbortController(), segments: [], outputs: [], prose: [], pieces: 0,
          pieceReports: [], final: null, checks: null, error: null };
  els.report.hidden = true;
  els.progress.textContent = "Sending…";
  setRunning(true);
  render();
  try {
    const res = await fetch("/api/rewrite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: draft, retry: els.retry.checked }),
      signal: run.controller.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || (body.detail && JSON.stringify(body.detail)) || `Server returned ${res.status}`);
    }
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const line = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        if (line.startsWith("data:")) handle(JSON.parse(line.slice(5)));
      }
    }
    if (run.error) throw new Error(run.error);
    if (run.final === null) throw new Error("The connection closed before the rewrite finished.");
  } catch (err) {
    if (err.name === "AbortError") {
      els.progress.textContent = "Stopped";
      if (currentText()) {
        run.final = currentText();
      }
    } else {
      showError(`Could not rewrite: ${err.message}`);
      run.final = null;
      run.controller = null;
      setRunning(false);
      checkHealth();
      return;
    }
  }
  run.controller = null;
  setRunning(false);
  render();
}

function li(cls, html) {
  const item = document.createElement("li");
  item.className = cls;
  item.innerHTML = html;
  return item;
}

const code = (list) => list.map((x) => `<code>${escapeHtml(String(x))}</code>`).join(" ");

function showChecks() {
  const c = run.checks;
  const list = els.checks;
  list.replaceChildren();
  const draftNumbers = new Set([...run.draft.matchAll(new RegExp(NUMBER_SRC, "g"))].map((m) => normalizeNumber(m[1], m[2], m[3])));

  if (c.missing_numbers.length) {
    list.append(li("bad", `Not found in the rewrite: ${code(c.missing_numbers)}. Check whether these numbers were dropped or changed.`));
  } else if (draftNumbers.size) {
    list.append(li("ok", draftNumbers.size === 1 ? "The draft's one number appears in the rewrite."
      : `All ${draftNumbers.size} numbers from the draft appear in the rewrite.`));
  }
  if (c.added_numbers.length) {
    list.append(li("warn", `New numbers in the rewrite (highlighted): ${code(c.added_numbers)}. The model sometimes does arithmetic, and sometimes invents a figure.`));
  }
  if (c.missing_urls.length) list.append(li("bad", `Links missing from the rewrite: ${code(c.missing_urls)}`));
  if (c.wrong_language) list.append(li("bad", "Parts of the rewrite are in a different language from the draft. Try again."));

  const copy = Math.round(c.copy_rate * 100);
  const copyCls = c.copy_rate > 0.5 ? "bad" : c.copy_rate > 0.35 ? "warn" : "ok";
  list.append(li(copyCls, `${copy}% of the rewrite repeats 5-word runs from the draft${copyCls === "ok" ? "." : ". It stays close to the draft; rewriting again gives a fresh sample."}`));
  const ratio = c.length_ratio;
  list.append(li(ratio < 0.35 || ratio > 1.75 ? "warn" : "ok", `Length: ${ratio}× the draft.`));

  for (const p of run.pieceReports) {
    const n = run.prose.indexOf(p.index) + 1;
    const label = run.pieces > 1 ? `Piece ${n}` : "The rewrite";
    if (p.checks.truncated) list.append(li("bad", `${label} hit the length limit and may be cut off.`));
    if (p.attempts > 1) list.append(li("", `${label} was sampled ${p.attempts} times; try ${p.chosen} was kept.`));
  }
  if (run.pieces > 1) {
    const kept = run.segments.length - run.pieces;
    list.append(li("", `Long draft: rewritten in ${run.pieces} pieces${kept ? `, with ${kept} heading/code/table block${kept === 1 ? "" : "s"} kept as written` : ""}. Read it once top to bottom; tone can shift between pieces.`));
  }
  list.append(li("", "These checks cover numbers, links and copying only. Proofread names, dates and the direction of each claim before you send it."));
  els.report.hidden = false;
}

/* Model status */
let healthTimer = null;
async function checkHealth() {
  clearTimeout(healthTimer);
  let next = 15000;
  try {
    const res = await fetch("/api/health");
    const h = await res.json();
    els.status.dataset.state = h.status;
    const model = h.model ? h.model.split(/[\\/]/).pop().replace(/\.gguf$/, "") : null;
    els.statusText.textContent = {
      ready: model ? `Ready · ${model}` : "Model ready",
      loading: "Loading model…",
      offline: "Model server offline",
      error: "Model server error",
    }[h.status] || h.status;
    els.status.title = `${h.detail || ""} (${h.backend} at ${h.url})`;
    if (h.status !== "ready") next = 3000;
  } catch {
    els.status.dataset.state = "offline";
    els.statusText.textContent = "Interface offline";
    els.status.title = "The Humaniser web server is not responding.";
    next = 5000;
  }
  healthTimer = setTimeout(checkHealth, next);
}

/* Wiring */
function updateDraftCount() {
  els.draftCount.textContent = countWords(els.draft.value);
}

els.go.addEventListener("click", humanize);
els.draft.addEventListener("input", () => {
  updateDraftCount();
  if (!(run && run.controller)) els.go.querySelector(".label").textContent = "Humanize";
});
els.draft.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    humanize();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && run && run.controller) run.controller.abort();
});
els.highlight.addEventListener("change", render);
els.clear.addEventListener("click", () => {
  if (run && run.controller) return;
  els.draft.value = "";
  updateDraftCount();
  els.draft.focus();
});
els.examples.addEventListener("change", () => {
  const value = EXAMPLES[els.examples.value];
  els.examples.value = "";
  if (!value || (run && run.controller)) return;
  els.draft.value = value;
  updateDraftCount();
});
els.copy.addEventListener("click", async () => {
  const text = run && run.final;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  els.copy.textContent = "Copied";
  setTimeout(() => { els.copy.textContent = "Copy"; }, 1500);
});

if (/Mac|iPhone|iPad/.test(navigator.platform)) els.shortcut.textContent = "⌘ ↵";
updateDraftCount();
checkHealth();
