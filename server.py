import asyncio
import json as jsonlib
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
OUTPUTS = DATA / "outputs"
META_DIR = DATA / "meta"
for p in (UPLOADS, OUTPUTS, META_DIR):
    p.mkdir(parents=True, exist_ok=True)

# ---------- 配置(全部可用环境变量覆盖,见 README) ----------
LLM_BASE = os.environ.get("PT_LLM_BASE", "http://127.0.0.1:8910").rstrip("/")
LLAMA_URL = f"{LLM_BASE}/v1/chat/completions"
HEALTH_URL = f"{LLM_BASE}/health"
BABELDOC = os.environ.get("PT_BABELDOC", "babeldoc")
ZCODE = os.environ.get("PT_ZCODE", "zcode")
TRANSLATE_MODEL = os.environ.get("PT_TRANSLATE_MODEL", "translate-model")
TRANSLATE_TIMEOUT = 180
TASK_TIMEOUT = 3600
CHAT_TIMEOUT = 240

app = FastAPI()
tasks = {}
q = queue.Queue()


def worker():
    while True:
        tid = q.get()
        t = tasks[tid]
        try:
            out = OUTPUTS / tid
            out.mkdir(exist_ok=True)
            t["status"] = "running"
            cmd = [
                BABELDOC, "--files", str(t["upload_path"]),
                "--openai", "--openai-model", TRANSLATE_MODEL,
                "--openai-base-url", f"{LLM_BASE}/v1",
                "--openai-api-key", "none",
                "--lang-in", "en", "--lang-out", "zh",
                "--output", str(out),
                "--watermark-output-mode", "no_watermark",
                "--no-watermark",
                "--use-alternating-pages-dual",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=TASK_TIMEOUT)
            if r.returncode != 0:
                t["status"] = "failed"
                t["error"] = (r.stderr or r.stdout)[-800:]
            else:
                pdfs = list(out.glob("*.pdf"))
                dual = next((p for p in pdfs if p.name.endswith("dual.pdf")), None)
                mono = next((p for p in pdfs if p.name.endswith("mono.pdf")), None)
                if dual:
                    t["dual"] = dual.name
                if mono:
                    t["mono"] = mono.name
                t["status"] = "done" if (dual or mono) else "failed"
                if t["status"] == "failed":
                    t["error"] = "翻译完成但未生成输出文件"
                else:
                    analyze_q.put(tid)
        except Exception as e:
            t["status"] = "failed"
            t["error"] = str(e)[:800]


threading.Thread(target=worker, daemon=True).start()

# ---------- AI 语义分析(归类 + 一句话摘要) ----------
analyze_q = queue.Queue()

ANALYZE_PROMPT = (
    '阅读这篇学术论文,严格只输出一个JSON对象,禁止输出任何其他文字或代码块标记。'
    '格式:{"category": "论文研究类别,中文2-8个字", "summary": "一句话中文摘要,30字以内,概括方法核心"}'
)

def analyze_one(tid):
    t = tasks.get(tid)
    if not t:
        return
    if t.get("meta", {}).get("category"):
        return
    t["analyzing"] = True
    try:
        cmd = [ZCODE, "-p", ANALYZE_PROMPT, "--attach", t["upload_path"], "--mode", "plan", "--cwd", "/tmp"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out = r.stdout or ""
        blob = out[out.find("{"): out.rfind("}") + 1]
        data = jsonlib.loads(blob)
        t["meta"] = {
            "category": str(data.get("category", "未分类"))[:20],
            "summary": str(data.get("summary", ""))[:80],
        }
        (META_DIR / f"{tid}.json").write_text(jsonlib.dumps(t["meta"], ensure_ascii=False))
    except Exception as e:
        t["meta"] = {"error": str(e)[:120]}
    finally:
        t["analyzing"] = False

def analyze_worker():
    while True:
        tid = analyze_q.get()
        try:
            analyze_one(tid)
        except Exception:
            pass

threading.Thread(target=analyze_worker, daemon=True).start()


def restore_tasks():
    """重启后从磁盘恢复历史任务(输出文件还在的任务标记为完成)。"""
    for out in sorted(OUTPUTS.iterdir()):
        if not out.is_dir():
            continue
        tid = out.name
        up = UPLOADS / f"{tid}.pdf"
        if not up.is_file():
            continue
        name_file = UPLOADS / f"{tid}.name"
        name = name_file.read_text().strip() if name_file.is_file() else tid
        meta_file = META_DIR / f"{tid}.json"
        meta = {}
        if meta_file.is_file():
            try:
                meta = jsonlib.loads(meta_file.read_text())
            except Exception:
                meta = {}
        dual = next((p.name for p in out.glob("*.dual.pdf")), None)
        mono = next((p.name for p in out.glob("*.mono.pdf")), None)
        if not (dual or mono):
            continue
        tasks[tid] = {
            "id": tid,
            "name": name,
            "status": "done",
            "upload_path": str(up),
            "dual": dual,
            "mono": mono,
            "error": None,
            "meta": meta,
            "createdAt": int(up.stat().st_mtime * 1000),
        }


restore_tasks()
for t in list(tasks.values()):
    if t["status"] == "done" and not t.get("meta", {}).get("category"):
        analyze_q.put(t["id"])


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    tid = uuid.uuid4().hex[:12]
    dest = UPLOADS / f"{tid}.pdf"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    stem = Path(file.filename or dest.name).stem
    (UPLOADS / f"{tid}.name").write_text(stem)
    tasks[tid] = {
        "id": tid,
        "name": stem,
        "status": "queued",
        "upload_path": str(dest),
        "dual": None,
        "mono": None,
        "error": None,
        "meta": {},
        "createdAt": int(time.time() * 1000),
    }
    q.put(tid)
    return tasks[tid]


@app.post("/api/analyze/{tid}")
async def reanalyze(tid: str):
    t = tasks.get(tid)
    if not t:
        raise HTTPException(404, "no such task")
    if t["status"] != "done":
        raise HTTPException(400, "task not done")
    analyze_q.put(tid)
    return {"ok": True}


@app.get("/api/tasks")
def list_tasks():
    return sorted(tasks.values(), key=lambda t: t["id"], reverse=True)


@app.get("/api/files/{tid}/{variant}")
def get_file(tid: str, variant: str):
    t = tasks.get(tid)
    if not t:
        raise HTTPException(404, "no such task")
    if variant == "original":
        return FileResponse(t["upload_path"], media_type="application/pdf")
    name = t.get("dual") if variant == "dual" else t.get("mono")
    if not name:
        raise HTTPException(404, "not ready")
    return FileResponse(OUTPUTS / tid / name, media_type="application/pdf")


@app.post("/api/translate")
async def translate(body: dict):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "empty text")
    if len(text) > 6000:
        text = text[:6000]
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    direction = "en2zh" if cjk / max(len(text), 1) < 0.15 else "zh2en"
    target = "中文" if direction == "en2zh" else "英语"
    prompt = (
        f"将以下学术文本翻译成{target},注意只需要输出翻译后的结果,不要额外解释:\n\n{text}"
    )
    req = jsonlib.dumps({
        "model": TRANSLATE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0,
    }).encode()
    r = urllib.request.Request(LLAMA_URL, data=req, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=TRANSLATE_TIMEOUT) as resp:
            d = jsonlib.loads(resp.read())
    except Exception as e:
        raise HTTPException(502, f"翻译服务不可达: {e}")
    return {
        "translation": d["choices"][0]["message"]["content"].strip(),
        "direction": direction,
    }


@app.get("/api/health")
def health():
    llm = False
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as r:
            llm = r.status == 200
    except Exception:
        pass
    return {"backend": True, "llm": llm}


@app.post("/api/chat")
async def chat(body: dict):
    question = (body.get("message") or "").strip()
    if not question:
        raise HTTPException(400, "empty message")
    tid = body.get("taskId") or ""
    cont = bool(body.get("continue"))
    if len(question) > 8000:
        question = question[:8000]

    # ZCode 会话链:每个对话 key 一个专属目录,首轮建会话,后续 -c 恢复上下文
    key = tid or "global"
    chat_dir = Path.home() / ".cache" / "pdf-translate-chat" / f"chat-{key}"
    chat_dir.mkdir(parents=True, exist_ok=True)
    prompt = question

    cmd = [ZCODE, "-p", prompt, "--mode", "plan", "--cwd", str(chat_dir)]
    if cont:
        cmd.append("-c")
    attach = UPLOADS / f"{tid}.pdf" if tid else None
    if tid and attach.is_file() and not cont:
        cmd += ["--attach", str(attach)]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CHAT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(504, "AI 回答超时")
    except Exception as e:
        raise HTTPException(502, f"无法启动 AI CLI: {e}")
    if proc.returncode != 0:
        raise HTTPException(502, (stderr or b"").decode(errors="replace")[-500:] or "ZCode 运行失败")
    answer = stdout.decode(errors="replace").strip()
    if not answer:
        raise HTTPException(502, "AI 未返回内容")
    return {"answer": answer, "attached": bool(attach and attach.is_file()), "continued": cont}


@app.post("/api/chat/reset")
def chat_reset(body: dict):
    """清空某篇论文(或通用)对话:删除其 ZCode 会话目录,下次提问重新开始。"""
    key = (body or {}).get("key") or "global"
    d = Path.home() / ".cache" / "pdf-translate-chat" / f"chat-{key}"
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
