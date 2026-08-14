import asyncio, json, os, re, uuid
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import httpx

load_dotenv()

app = FastAPI()
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
API_URL = "https://api.deepseek.com/chat/completions"

TASKS = [
    {
        "id": "simple",
        "level": "简单任务",
        "title": "解释 RAG",
        "prompt": "用简洁中文解释 RAG 是什么，并给出 3 个实际价值。",
    },
    {
        "id": "complex",
        "level": "复杂任务",
        "title": "设计电商新品上线方案",
        "prompt": "为一家跨境电商设计一个新品上线方案，覆盖市场判断、定价、内容与投放，并给出可执行的最终方案。",
    },
]

runs = {}

async def llm(system, user):
    if not API_KEY:
        raise RuntimeError("请先在 .env 中填写 DEEPSEEK_API_KEY")
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            API_URL,
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=payload,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

def node(name, task, status="pending", role="worker"):
    return {"id": uuid.uuid4().hex[:8], "name": name, "task": task, "status": status, "role": role, "output": ""}

def parse_subtasks(text):
    match = re.search(r"\[[\s\S]*\]", text)
    data = json.loads(match.group(0) if match else text)
    return [str(x) for x in data][:4]

async def run_simple(run_id, task):
    state = runs[run_id]
    n = state["nodes"][0]
    n["status"] = "running"
    try:
        n["output"] = await llm("你是主 Agent，直接完成简单任务。", task["prompt"])
        n["status"] = "done"
        state["result"] = n["output"]
        state["status"] = "done"
    except Exception as e:
        n["status"] = "error"
        n["output"] = str(e)
        state["status"] = "error"

async def run_complex(run_id, task):
    state = runs[run_id]
    planner = state["nodes"][0]
    planner["status"] = "running"
    try:
        raw = await llm(
            "你是主 Agent。把复杂任务拆成 3 个互不依赖、可并行执行的子任务。只返回 JSON 字符串数组。",
            task["prompt"],
        )
        subtasks = parse_subtasks(raw)
        planner["output"] = "\n".join(subtasks)
        planner["status"] = "done"

        workers = [node(f"SubAgent {i+1}", subtask, "running", "worker") for i, subtask in enumerate(subtasks)]
        state["nodes"].extend(workers)

        async def work(n):
            try:
                n["output"] = await llm(
                    "你是子 Agent。只完成分配给你的子任务，输出清晰、可用于主 Agent 汇总的结果。",
                    n["task"],
                )
                n["status"] = "done"
            except Exception as e:
                n["status"] = "error"
                n["output"] = str(e)

        await asyncio.gather(*(work(n) for n in workers))

        synth = node("Main Agent", "汇总所有 SubAgent 结果并给出最终答案", "running", "synth")
        state["nodes"].append(synth)
        context = "\n\n".join(f"{n['task']}\n{n['output']}" for n in workers)
        synth["output"] = await llm(
            "你是主 Agent。基于所有子 Agent 结果，合并去重并输出最终可执行方案。",
            f"原任务：{task['prompt']}\n\n子任务结果：\n{context}",
        )
        synth["status"] = "done"
        state["result"] = synth["output"]
        state["status"] = "done"
    except Exception as e:
        planner["status"] = "error"
        planner["output"] = str(e)
        state["status"] = "error"

@app.get("/tasks")
def get_tasks():
    return TASKS

@app.post("/run/{task_id}")
async def start(task_id: str):
    task = next(x for x in TASKS if x["id"] == task_id)
    run_id = uuid.uuid4().hex
    first = node("Main Agent", task["prompt"], role="planner" if task_id == "complex" else "single")
    runs[run_id] = {"status": "running", "nodes": [first], "result": ""}
    asyncio.create_task(run_complex(run_id, task) if task_id == "complex" else run_simple(run_id, task))
    return {"run_id": run_id}

@app.get("/status/{run_id}")
def status(run_id: str):
    return runs[run_id]

HTML = r'''
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Multi-Agent Demo</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f6f7fb;color:#17181c;font:14px/1.5 system-ui}
main{max-width:1120px;margin:42px auto;padding:0 20px}h1{font-size:28px;margin:0 0 8px}.sub{color:#6b7280;margin-bottom:28px}
.tasks{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card,.panel{background:white;border:1px solid #e5e7eb;border-radius:14px;padding:18px}
.card h3{margin:8px 0}.tag{font-size:12px;color:#6b7280}.card button{margin-top:14px;border:0;border-radius:9px;padding:9px 14px;background:#17181c;color:white;cursor:pointer}
.panel{margin-top:18px}.panel h2{font-size:17px}.graph{display:flex;gap:14px;align-items:center;overflow:auto;padding:8px 0 4px}.parallel{display:flex;gap:10px;align-items:stretch;padding:10px;border:1px dashed #cbd5e1;border-radius:14px}.agent{min-width:210px;max-width:260px;border:2px solid #d1d5db;border-radius:12px;padding:14px;background:#f9fafb;transition:.25s}.agent.running{border-color:#f59e0b;background:#fffbeb}.agent.done{border-color:#22c55e;background:#f0fdf4}.agent.error{border-color:#ef4444;background:#fef2f2}.agent b{display:block;margin-bottom:6px}.status{font-size:12px;color:#6b7280;margin-bottom:8px}.task{font-size:13px}.arrow{color:#9ca3af;font-size:22px}.result{white-space:pre-wrap;margin-top:14px;padding:14px;background:#111827;color:#f9fafb;border-radius:10px;min-height:80px}.hidden{display:none}
@media(max-width:700px){.tasks{grid-template-columns:1fr}}
</style>
</head>
<body>
<main>
<h1>Multi-Agent Task Runner</h1>
<div class="sub">简单任务由 Main Agent 直接执行；复杂任务会拆分并并行启动 SubAgent。</div>
<div id="tasks" class="tasks"></div>
<section id="panel" class="panel hidden">
<h2>执行进度</h2>
<div id="graph" class="graph"></div>
<div id="result" class="result">等待执行结果...</div>
</section>
</main>
<script>
const tasksEl=document.querySelector('#tasks'),panel=document.querySelector('#panel'),graph=document.querySelector('#graph'),result=document.querySelector('#result')
fetch('/tasks').then(r=>r.json()).then(tasks=>tasks.forEach(t=>{
  const el=document.createElement('div');el.className='card'
  el.innerHTML=`<div class="tag">${t.level}</div><h3>${t.title}</h3><div>${t.prompt}</div><button>运行任务</button>`
  el.querySelector('button').onclick=()=>run(t.id);tasksEl.appendChild(el)
}))
async function run(id){
  panel.classList.remove('hidden');graph.innerHTML='';result.textContent='等待执行结果...'
  const {run_id}=await fetch('/run/'+id,{method:'POST'}).then(r=>r.json())
  const timer=setInterval(async()=>{
    const s=await fetch('/status/'+run_id).then(r=>r.json());render(s)
    if(s.status!=='running')clearInterval(timer)
  },500)
}
function card(n){return `<div class="agent ${n.status}"><b>${n.name}</b><div class="status">${n.status}</div><div class="task">${escapeHtml(n.task)}</div></div>`}
function render(s){
  const planner=s.nodes.find(n=>n.role==='planner'||n.role==='single')
  const workers=s.nodes.filter(n=>n.role==='worker')
  const synth=s.nodes.find(n=>n.role==='synth')
  let html=planner?card(planner):''
  if(workers.length)html+=`<div class="arrow">→</div><div class="parallel">${workers.map(card).join('')}</div>`
  if(synth)html+=`<div class="arrow">→</div>${card(synth)}`
  graph.innerHTML=html
  if(s.result)result.textContent=s.result
  if(s.status==='error')result.textContent='执行失败，请检查 .env、API Key 或接口返回。'
}
function escapeHtml(x){const d=document.createElement('div');d.textContent=x;return d.innerHTML}
</script>
</body>
</html>
'''

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML
