import json
import os
import re
import uuid
from collections import OrderedDict
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
MASTER_PATH = BASE_DIR / "SKILL.md"
CHILD_PATH = BASE_DIR / "dingjia_skill.md"
load_dotenv(BASE_DIR / ".env")

app = FastAPI()
TOKENS = {}
PENDING = {}

SCHEMA = {
    "name": "dingjia_skill",
    "description": "电商定价策略子技能，处理售价、折扣、毛利、库存清理和价格底线问题",
    "input": "用户的定价问题",
    "load_when": "问题涉及价格、折扣、促销、毛利、成本或库存定价"
}

HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loop Agent Skill 自迭代演示</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;background:#f4f5f7;color:#171717}.wrap{max-width:1180px;margin:32px auto;padding:0 18px}.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:20px;margin-bottom:16px}.hidden{display:none}h1,h2,h3{margin-top:0}input,textarea,select,button{font:inherit}input,select,textarea{width:100%;padding:11px;border:1px solid #bbb;border-radius:8px;margin:6px 0 12px}textarea{min-height:420px;font-family:Consolas,monospace;line-height:1.5}button{border:0;border-radius:8px;padding:10px 16px;background:#111;color:#fff;cursor:pointer}button.secondary{background:#555}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.meta{display:flex;gap:10px;flex-wrap:wrap}.badge{background:#eee;border-radius:999px;padding:7px 11px}.answer{white-space:pre-wrap;background:#f7f7f7;border-left:4px solid #111;padding:14px;min-height:80px}.timeline{padding-left:20px}.timeline li{margin:9px 0}.ok{color:#087c37}.warn{color:#b25100}.error{color:#b00020}.small{font-size:13px;color:#666}.skill{white-space:pre-wrap;background:#f7f7f7;border:1px solid #ddd;border-radius:8px;padding:12px;max-height:330px;overflow:auto;font-family:Consolas,monospace}.top{display:flex;justify-content:space-between;align-items:center;gap:10px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
<div id="login" class="card">
<h1>Loop Agent</h1>
<p>登录后演示总 SKILL 与定价子 Skill 的延迟自迭代。</p>
<label>身份</label><select id="role"><option value="user">用户</option><option value="admin">管理员</option></select>
<label>用户名</label><input id="username" value="user">
<div id="passwordBox" class="hidden"><label>密码</label><input id="password" type="password"></div>
<button onclick="login()">登录</button>
<p id="loginMsg" class="error"></p>
</div>

<div id="admin" class="hidden">
<div class="top"><h1>管理员：总 SKILL 管理</h1><button class="secondary" onclick="logout()">退出</button></div>
<div class="card">
<div id="adminMeta" class="meta"></div>
<p class="small">保存时，系统比较各 CATEGORY 内容，只给发生变化的类别自动升版本。保存总 SKILL 后，dingjia_skill.md 暂时保持旧版本。</p>
<textarea id="masterEditor"></textarea>
<button onclick="saveMaster()">保存总 SKILL.md</button>
<p id="saveMsg"></p>
</div>
</div>

<div id="user" class="hidden">
<div class="top"><h1>用户：定价 Agent</h1><button class="secondary" onclick="logout()">退出</button></div>
<div class="grid">
<div>
<div class="card">
<h2>提问</h2>
<input id="question" value="成本100元、库存积压45天，应该卖多少钱？">
<button id="sendBtn" onclick="chat()">发送</button>
</div>
<div class="card"><h2>本次回答</h2><div id="answer" class="answer"></div></div>
<div class="card"><h2>事后 Loop 时间线</h2><ol id="timeline" class="timeline"></ol></div>
</div>
<div>
<div class="card"><h2>用户可访问的 dingjia_skill.md</h2><div id="childMeta" class="meta"></div><div id="childSkill" class="skill"></div></div>
<div class="card"><h2>渐进式披露 Schema</h2><div id="schema" class="skill"></div></div>
</div>
</div>
</div>
</div>
<script>
let token="";let role="";
const q=id=>document.getElementById(id);
q("role").onchange=()=>{const a=q("role").value==="admin";q("passwordBox").classList.toggle("hidden",!a);q("username").value=a?"admin":"user"};
async function api(path,options={}){options.headers={"Content-Type":"application/json",...(options.headers||{})};if(token)options.headers.Authorization=`Bearer ${token}`;const r=await fetch(path,options);const d=await r.json();if(!r.ok)throw new Error(d.detail||"请求失败");return d}
async function login(){try{role=q("role").value;const d=await api("/api/login",{method:"POST",body:JSON.stringify({role,username:q("username").value,password:q("password").value})});token=d.token;q("login").classList.add("hidden");q(role).classList.remove("hidden");role==="admin"?await loadAdmin():await loadChild()}catch(e){q("loginMsg").textContent=e.message}}
function logout(){location.reload()}
function badges(el,items){el.innerHTML=items.map(x=>`<span class="badge">${x}</span>`).join("")}
async function loadAdmin(){const d=await api("/api/admin/skill");q("masterEditor").value=d.content;badges(q("adminMeta"),[`总定价版本 v${d.pricing_version}`,`子 Skill v${d.child_version}`,`子 Skill 对齐源 v${d.child_source_version}`])}
async function saveMaster(){try{const d=await api("/api/admin/skill",{method:"POST",body:JSON.stringify({content:q("masterEditor").value})});q("masterEditor").value=d.content;q("saveMsg").className="warn";q("saveMsg").textContent=`已保存。总定价策略现在是 v${d.pricing_version}，dingjia_skill.md 仍对齐 v${d.child_source_version}，此刻不会同步。`;await loadAdmin()}catch(e){q("saveMsg").className="error";q("saveMsg").textContent=e.message}}
async function loadChild(){const d=await api("/api/child");q("childSkill").textContent=d.content;q("schema").textContent=JSON.stringify(d.schema,null,2);badges(q("childMeta"),[`子 Skill v${d.child_version}`,`对齐总定价 v${d.source_version}`])}
function addStep(text,cls=""){const li=document.createElement("li");li.textContent=text;if(cls)li.className=cls;q("timeline").appendChild(li)}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function chat(){q("sendBtn").disabled=true;q("timeline").innerHTML="";q("answer").textContent="";try{const d=await api("/api/chat",{method:"POST",body:JSON.stringify({question:q("question").value})});d.trace.forEach(x=>addStep(x));q("answer").textContent=d.answer;addStep(`回答已经展示给用户，使用的是 dingjia_skill.md v${d.child_version} / source v${d.child_source_version}`,"warn");await sleep(900);addStep("回答完成后，Loop Agent 才开始执行版本一致性检查");const c=await api("/api/post-check",{method:"POST",body:JSON.stringify({check_id:d.check_id})});if(c.correct){addStep(`版本一致：总定价 v${c.master_version} = 子 Skill source v${c.old_source_version}，本次回答判定正确`,"ok")}else{addStep(`版本不一致：总定价 v${c.master_version} ≠ 子 Skill source v${c.old_source_version}，刚才的回答判定错误`,"error");addStep(`Agent 已自行修订 dingjia_skill.md：子版本 v${c.old_child_version} → v${c.new_child_version}，source v${c.old_source_version} → v${c.new_source_version}`,"ok");addStep("已经发出的回答不重写；下一次提问才使用新策略","warn")}await loadChild()}catch(e){addStep(e.message,"error")}finally{q("sendBtn").disabled=false}}
</script>
</body>
</html>'''


class LoginBody(BaseModel):
    role: str
    username: str = ""
    password: str = ""


class SkillBody(BaseModel):
    content: str


class ChatBody(BaseModel):
    question: str


class CheckBody(BaseModel):
    check_id: str


def parse_master(text: str):
    pattern = re.compile(r"^## CATEGORY:\s*([^\n]+)\nversion:\s*(\d+)\n(.*?)(?=^## CATEGORY:|\Z)", re.M | re.S)
    sections = OrderedDict()
    for match in pattern.finditer(text.strip() + "\n"):
        name = match.group(1).strip()
        sections[name] = {"version": int(match.group(2)), "body": match.group(3).strip()}
    return sections


def build_master(sections):
    parts = ["# 电商总策略 SKILL"]
    for name, data in sections.items():
        parts.append(f"## CATEGORY: {name}\nversion: {data['version']}\n\n{data['body'].strip()}")
    return "\n\n".join(parts).strip() + "\n"


def parse_child(text: str):
    child_version = int(re.search(r"^child_version:\s*(\d+)", text, re.M).group(1))
    source_version = int(re.search(r"^source_version:\s*(\d+)", text, re.M).group(1))
    body_match = re.search(r"^## 策略\n(.*)\Z", text, re.M | re.S)
    return {"child_version": child_version, "source_version": source_version, "body": body_match.group(1).strip()}


def build_child(body: str, child_version: int, source_version: int):
    return f"# 定价子技能\n\nchild_version: {child_version}\nsource_category: pricing\nsource_version: {source_version}\n\n## 策略\n{body.strip()}\n"


def auth(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    token = authorization[7:]
    user_role = TOKENS.get(token)
    if not user_role:
        raise HTTPException(401, "登录已失效")
    return user_role


def require_admin(authorization: str | None):
    if auth(authorization) != "admin":
        raise HTTPException(403, "仅管理员可访问")


async def call_llm(messages, temperature=0):
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": temperature}
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"LLM 调用失败：{response.text[:300]}")
    return response.json()["choices"][0]["message"]["content"]


def parse_json_result(text):
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.post("/api/login")
async def login(body: LoginBody):
    if body.role == "admin":
        username = os.getenv("ADMIN_USERNAME", "admin")
        password = os.getenv("ADMIN_PASSWORD", "admin123")
        if body.username != username or body.password != password:
            raise HTTPException(401, "管理员账号或密码错误")
    elif body.role != "user":
        raise HTTPException(400, "身份无效")
    token = uuid.uuid4().hex
    TOKENS[token] = body.role
    return {"token": token, "role": body.role}


@app.get("/api/admin/skill")
async def get_master(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    master = parse_master(MASTER_PATH.read_text(encoding="utf-8"))
    child = parse_child(CHILD_PATH.read_text(encoding="utf-8"))
    return {
        "content": MASTER_PATH.read_text(encoding="utf-8"),
        "pricing_version": master["pricing"]["version"],
        "child_version": child["child_version"],
        "child_source_version": child["source_version"]
    }


@app.post("/api/admin/skill")
async def save_master(body: SkillBody, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    old = parse_master(MASTER_PATH.read_text(encoding="utf-8"))
    incoming = parse_master(body.content)
    if "pricing" not in incoming:
        raise HTTPException(400, "总 SKILL 必须包含 pricing 类别")
    updated = OrderedDict()
    for name, data in incoming.items():
        if name in old:
            changed = data["body"].strip() != old[name]["body"].strip()
            version = old[name]["version"] + 1 if changed else old[name]["version"]
        else:
            version = 1
        updated[name] = {"version": version, "body": data["body"]}
    content = build_master(updated)
    MASTER_PATH.write_text(content, encoding="utf-8")
    child = parse_child(CHILD_PATH.read_text(encoding="utf-8"))
    return {
        "content": content,
        "pricing_version": updated["pricing"]["version"],
        "child_source_version": child["source_version"]
    }


@app.get("/api/child")
async def get_child(authorization: str | None = Header(default=None)):
    auth(authorization)
    content = CHILD_PATH.read_text(encoding="utf-8")
    child = parse_child(content)
    return {"content": content, "schema": SCHEMA, **child}


@app.post("/api/chat")
async def chat(body: ChatBody, authorization: str | None = Header(default=None)):
    auth(authorization)
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "请输入问题")
    child_content = CHILD_PATH.read_text(encoding="utf-8")
    child = parse_child(child_content)
    route_text = await call_llm([
        {"role": "system", "content": "你是工具路由器。只根据给定 Skill Schema 判断是否需要加载该 Skill。只输出 JSON：{\"load\":true或false,\"reason\":\"一句话\"}"},
        {"role": "user", "content": f"Skill Schema:\n{json.dumps(SCHEMA, ensure_ascii=False)}\n\n用户问题：{question}"}
    ])
    route = parse_json_result(route_text)
    if not route:
        keywords = ["价格", "定价", "售价", "折扣", "促销", "毛利", "成本", "库存"]
        route = {"load": any(x in question for x in keywords), "reason": "本地路由规则命中定价语义"}
    trace = ["LLM 首先只收到 dingjia_skill 的 Schema，没有收到策略正文"]
    if route.get("load"):
        trace.append(f"路由器决定按需加载 dingjia_skill.md v{child['child_version']} / source v{child['source_version']}")
        answer = await call_llm([
            {"role": "system", "content": "你是电商定价 Agent。必须严格遵循已加载的定价 Skill 回答。用中文直接给出结论和计算依据。"},
            {"role": "user", "content": f"已加载的 dingjia_skill.md：\n{child_content}\n\n用户问题：{question}"}
        ], 0.2)
        if not answer:
            answer = f"根据当前定价子策略（source v{child['source_version']}）：\n\n{child['body']}\n\n针对你的问题：{question}"
    else:
        trace.append("路由器判断无需加载定价 Skill")
        answer = await call_llm([
            {"role": "system", "content": "你是电商助手。当前没有加载专用 Skill，请简洁回答。"},
            {"role": "user", "content": question}
        ], 0.2)
        answer = answer or "该问题未触发定价 Skill。"
    check_id = uuid.uuid4().hex
    PENDING[check_id] = {
        "answered_child_version": child["child_version"],
        "answered_source_version": child["source_version"],
        "loaded": bool(route.get("load"))
    }
    return {
        "answer": answer,
        "trace": trace,
        "check_id": check_id,
        "child_version": child["child_version"],
        "child_source_version": child["source_version"]
    }


@app.post("/api/post-check")
async def post_check(body: CheckBody, authorization: str | None = Header(default=None)):
    auth(authorization)
    pending = PENDING.pop(body.check_id, None)
    if not pending:
        raise HTTPException(404, "检查任务不存在或已完成")
    master = parse_master(MASTER_PATH.read_text(encoding="utf-8"))
    child = parse_child(CHILD_PATH.read_text(encoding="utf-8"))
    master_version = master["pricing"]["version"]
    old_child_version = child["child_version"]
    old_source_version = child["source_version"]
    correct = not pending["loaded"] or pending["answered_source_version"] == master_version
    if correct:
        return {
            "correct": True,
            "master_version": master_version,
            "old_child_version": old_child_version,
            "old_source_version": pending["answered_source_version"]
        }
    new_child_version = old_child_version + 1
    new_content = build_child(master["pricing"]["body"], new_child_version, master_version)
    CHILD_PATH.write_text(new_content, encoding="utf-8")
    return {
        "correct": False,
        "master_version": master_version,
        "old_child_version": old_child_version,
        "new_child_version": new_child_version,
        "old_source_version": pending["answered_source_version"],
        "new_source_version": master_version
    }
