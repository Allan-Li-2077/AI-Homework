const messagesEl = document.getElementById("messages");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");

const MODE_LABEL = {
  rag: "知识库",
  llm: "通用回答",
  no_knowledge: "无相关知识",
};

function addMessage(role, content, extra = null) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;

  if (role === "bot" && extra) {
    const meta = document.createElement("div");
    meta.className = "meta";
    const badge = document.createElement("span");
    badge.className = `badge ${extra.mode || ""}`;
    badge.textContent = MODE_LABEL[extra.mode] || extra.mode || "";
    meta.appendChild(badge);
    if (extra.companies?.length) {
      const c = document.createElement("span");
      c.className = "badge llm";
      c.textContent = extra.companies.join("、");
      meta.appendChild(c);
    }
    div.appendChild(meta);
  }

  const body = document.createElement("div");
  body.textContent = content;
  div.appendChild(body);

  if (extra?.citations?.length) {
    const box = document.createElement("div");
    box.className = "citations";
    box.innerHTML = "<strong>引用</strong>";
    extra.citations.forEach((cite, idx) => {
      const d = document.createElement("details");
      const s = document.createElement("summary");
      s.textContent = `${idx + 1}. ${cite.company} ${cite.year}年 · 片段${cite.page} · 相似度 ${cite.score}`;
      const p = document.createElement("div");
      p.textContent = cite.snippet;
      d.appendChild(s);
      d.appendChild(p);
      box.appendChild(d);
    });
    div.appendChild(box);
  }

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

async function ask(question) {
  addMessage("user", question);
  const loading = addMessage("bot", "正在思考…");
  loading.classList.add("typing");
  sendBtn.disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question }),
    });
    const data = await res.json();
    loading.remove();
    if (!res.ok) {
      addMessage("bot", data.detail || "请求失败");
      return;
    }
    addMessage("bot", data.answer, data);
  } catch (err) {
    loading.remove();
    addMessage("bot", `网络错误：${err.message}`);
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  ask(q);
});

document.querySelectorAll(".chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    const q = btn.getAttribute("data-q");
    if (q) ask(q);
  });
});

addMessage(
  "bot",
  "你好，我是白酒年报智能客服。\n• 询问茅台/五粮液/泸州老窖/习酒年报 → 走本地 RAG\n• 其他公司年报 → 返回「暂无相关知识」\n• 非年报问题 → 直接调用大模型"
);
