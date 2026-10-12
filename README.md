# 文献翻译工作台 (pdf-translate)

本地 Web 应用:PDF 整篇翻译、双语对照阅读、划词翻译、接入 AI 命令行助手的论文问答与语义归档。

## 功能

- **整篇翻译**:上传 PDF,由 BabelDOC 调用远程 OpenAI 兼容翻译服务,输出"双语对照"与"纯译文"两份 PDF,保留原版面(公式/图表);
- **双语对照阅读**:左原文右译文并排,两栏**独立缩放**(Ctrl+滚轮,栏内横滚互不挤占)、可选纵向同步滚动;
- **划词翻译与干净复制**:选中文本即弹出翻译;按几何位置从 PDF 结构重组文本,Ctrl+C 拿到的是完整段落(自动修复断词连字符、过滤图表乱码);
- **AI 论文问答**:底部对话面板,可接入多种 AI 命令行助手(CLI)或 OpenAI 兼容 API;打开文献自动附上 PDF,**服务端真实会话**(上下文由 CLI 自己维护,不轮次截断);每篇论文独立对话,本地持久化;
- **语义归档**:每篇翻译完成后由 AI 自动生成类别与一句话摘要,列表按主题或上传日期分组;
- **服务状态灯**:绿=全部正常 / 黄=翻译服务离线 / 红=本机后端未启动。

## 架构

```
浏览器 (http://127.0.0.1:8900)
   │
   ▼
本机后端 server.py (FastAPI/uvicorn)
   ├─ 翻译/语义分析 ──► BabelDOC CLI ──► 远程翻译服务(OpenAI 兼容 API,自建)
   └─ AI 问答 ─────────► AI CLI 子进程(ZCode / Claude Code / Codex / Kimi CLI,各自维护会话)
                          或 OpenAI 兼容 API(可配置)
```

前端与后端都跑在本机;翻译模型服务需自行部署(任何 OpenAI 兼容的翻译后端均可)。

## 部署

### 依赖

- Python 3.12+(通过 [uv](https://docs.astral.sh/uv/) 自动创建 venv)
- [uv](https://docs.astral.sh/uv/)
- 一个 OpenAI 兼容的翻译服务(自部署,地址填入配置)
- AI 问答(可选):本机已登录任一支持的 AI CLI,或提供 OpenAI 兼容 API

### 构建并安装 deb

```bash
./build-deb.sh            # 构建 pdf-translate_<版本>_all.deb(__APP_USER__ 会替换为当前用户)
sudo dpkg -i ./pdf-translate_*_all.deb
```

安装脚本会:迁移/初始化数据目录、安装 systemd 服务并启动。

### 手动运行(不装 deb)

```bash
bash scripts/setup-venv.sh          # 创建 venv 并安装依赖
/opt/pdf-translate/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8900
```

## 配置(环境变量)

| 变量 | 默认 | 说明 |
|---|---|---|
| `PT_LLM_BASE` | `http://127.0.0.1:8910` | 远程翻译服务根地址(OpenAI 兼容) |
| `PT_TRANSLATE_MODEL` | `translate-model` | 翻译服务模型名 |
| `PT_BABELDOC` | `babeldoc` | BabelDOC 可执行文件 |
| `PT_ZCODE` | `zcode` | AI CLI 可执行文件 |
| `PT_HOST` / `PT_PORT` | `127.0.0.1` / `8900` | Web 监听(手动运行时) |

systemd 部署在 `pkg/etc/systemd/system/pdf-translate.service` 中以 `Environment=` 配置。

## 使用

- 上传 PDF → 自动翻译 → 列表按语义/日期分组;
- 打开文献:原文 / 双语对照 / 纯译文三种视图;Ctrl+滚轮缩放(双语两栏独立);
- 划词:自动弹出翻译,Ctrl+C 复制干净原文,浮层按钮复制原/译文;
- 🤖 AI 问答:底部面板,打开文献后直接就内容提问;🧹 清空当前对话;
- 命令行翻译:`translate-pdf 文件.pdf [输出目录]`。

## 目录结构

```
server.py            # FastAPI 后端(翻译任务队列、划词/对话 API、AI 接入)
static/              # 前端(原生 JS + PDF.js)
scripts/setup-venv.sh# venv 环境准备(幂等)
pkg/                 # deb 打包模板(control、systemd、desktop、图标、命令)
build-deb.sh         # 一键构建 deb
```

## 隐私与数据

- 所有数据(上传的 PDF、翻译结果、对话)仅存本机 `data/` 目录与浏览器 localStorage;
- 翻译与问答请求发往**你自己部署/配置**的服务端,本项目不含任何第三方 API 地址或密钥。
