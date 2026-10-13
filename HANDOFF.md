# 项目交接说明(给接手的 AI / 开发者)

> 本文档是当前项目状态的权威快照。读这一份即可接手,源码就是本仓库。

## 一、这是什么

本地 Web 应用「文献翻译工作台」,运行在 `http://127.0.0.1:8900`(systemd 服务 `pdf-translate`,安装于 `/opt/pdf-translate`,数据在 `/opt/pdf-translate/data`)。

功能:
1. **整篇翻译**:上传 PDF → BabelDOC 调用远程 OpenAI 兼容翻译服务 → 生成"双语对照"和"纯译文"两份 PDF(保留原版面);
2. **PDF 阅读**:单页 / 双语对照(左右两栏并排,独立缩放,可选纵向同步滚动)/ 纯译文三种视图;
3. **划词翻译与干净复制**:选中文本弹翻译浮层;Ctrl+C 按 PDF 结构重组出完整段落(非浏览器选区碎片);
4. **AI 论文问答**:底部对话面板,打开文献自动附 PDF;每篇论文独立对话,持久化;
5. **语义归档**:翻译完成后 AI 自动生成类别+摘要,列表按主题或上传日期分组;
6. **状态灯**:右上角,绿=全正常 / 黄=翻译服务离线 / 红=本机后端未启动。

## 二、架构

```
浏览器 (127.0.0.1:8900)
   │
   ▼
server.py (FastAPI/uvicorn; systemd 服务 pdf-translate; 安装于 /opt/pdf-translate)
   ├─ 翻译/语义分析 ──► babeldoc CLI ──► 远程翻译服务(OpenAI 兼容 API,自部署)
   └─ AI 问答 /api/chat ──► spawn AI CLI 子进程(默认 zcode;配置支持 claude/codex/kimicode 或 OpenAI 兼容 API)
```

- 前端:`static/`,原生 JS + PDF.js 3.11,**无框架无构建**;
- 远程翻译服务 = 自部署的 Hy-MT2-7B(OpenAI 兼容),地址通过环境变量 `PT_LLM_BASE` 注入;
- **部署机的私密配置**(真实服务地址、模型名、CLI 路径)在 `/etc/systemd/system/pdf-translate.service.d/local.conf`(drop-in),**不在仓库里**——仓库中一律是占位/默认值。

## 三、仓库与部署形态

- 仓库:`~/pdf-translate-src`(= GitHub `xyw618/pdf-translate`,main 分支,private);
- 运行副本:`/opt/pdf-translate`(server.py + static + data);
- 改动流程:改 `~/pdf-translate-src` → `sudo cp` 同步到 `/opt/pdf-translate` → `sudo systemctl restart pdf-translate` → 浏览器硬刷新(已设 no-cache 头);
- 打包:`./build-deb.sh`(占位符 `__APP_USER__` 会替换为当前用户)。

## 四、⚠️ 当前已知 Bug(接手后优先处理)

**点击左侧文献条目,阅读区打不开(高概率复现,前台活跃标签页也复现)**:
- 症状:条目高亮、工具条出现"原文/双语对照/纯译文"切换(说明 `openTask` 已执行、`state.task` 已赋值),但 `#pages` 为 0、`#empty` 提示未消失、无任何 canvas;`window.onerror` 和 `unhandledrejection` 均无捕获;
- 定位线索:`openTask` → `await loadVariant()` 疑似**挂起**(非抛错)在 `pdfjsLib.getDocument("/api/files/<id>/original")` 附近;该接口 curl 返回 200 正常;
- 已排除:标签页冻结(60fps)、接口 404、语法错误;
- 期间相关变更(可能是诱因):静态资源 no-cache 中间件(`/api/*` 不受影响)、新增 `/api/ai/*` 端点、工具条控件移动;更早之前同样代码工作正常;
- 排查建议:浏览器 DevTools 的 Network 面板看 `getDocument` 的实际请求与 worker 加载;在 `loadVariant` 各 await 处加日志;检查 `pdfjsLib.GlobalWorkerOptions.workerSrc`。

## 五、⚠️ 改代码前必读的约束(都是踩过的坑)

1. **元素 ID 不能改名**(app.js 全靠它们):`app aside tasklist listmode sidebtn variant-switch syncbtn viewer dualwrap colL colR pages empty pageno zoomin zoomout zoomval prev next download hint aibtn chat chat-resize chat-ctx chat-clear chat-close chat-msgs chat-text chat-send pop pop-dir pop-copy-src pop-copy-t pop-close pop-src pop-out fileinput svc ai-provider ai-model ai-variant`。类 `hidden` = 强制隐藏,保留。
2. **`.textLayer` 是 PDF 文字层**(划词选择、按坐标提取文本都依赖):`.textLayer` absolute/`line-height:1`;`.textLayer span` `position:absolute; color:transparent; white-space:pre; transform-origin:0 0`。颜色透明度可调,定位规则不能动。
3. **flex 布局是修过"两栏互相挤占"bug 的**:`main{min-height:0}`、`#viewer{flex:1; min-height:0}`、`.col{flex:1 1 0; min-width:0; overflow:auto}`、`#app.collapsed aside{margin-left:-241px}`。别删。
4. **AI CLI 子进程必须用净室环境**(只有 HOME/PATH):systemd 会话变量(INVOCATION_ID 等)会让 zcode 走 Electron GUI 路径——轻则 stdout 被启动日志污染,重则段错误。见 `/api/chat` 的 `child_env`。
5. **`#chat` 高度由 JS 拖拽控制**(chat-resize),CSS 别写死 height。
6. 翻译模型名 **Hy-MT2-7B** 保留(默认值在 `TRANSLATE_MODEL`)。
7. `refreshTasks()` 每 3 秒重建 `#tasklist` 的 innerHTML——条目点击处理器是在重建时绑定的,这是设计;如果改造列表渲染,注意保持点击可用。

## 六、配置项(环境变量,均可在 systemd drop-in 覆盖)

| 变量 | 默认 | 说明 |
|---|---|---|
| `PT_LLM_BASE` | `http://127.0.0.1:8910` | 远程翻译服务根地址(OpenAI 兼容) |
| `PT_TRANSLATE_MODEL` | `Hy-MT2-7B` | 翻译模型名 |
| `PT_BABELDOC` | `babeldoc` | BabelDOC 路径 |
| `PT_ZCODE` | `zcode` | AI CLI 路径 |

AI harness 清单与命令模板在 `server.py` 的 `DEFAULT_AI_PROVIDERS`(zcode/claude/codex/kimicode/opencode/openai),当前选择持久化在 `data/ai-config.json`。

## 七、常用命令

```bash
systemctl status|restart|stop pdf-translate   # 服务管理
journalctl -u pdf-translate -f                # 后端日志
./build-deb.sh                                # 构建 deb(输出到源码树根)
translate-pdf 文件.pdf [输出目录]              # 命令行翻译
curl -s http://127.0.0.1:8900/api/health      # 健康检查 {"backend":true,"llm":true}
curl -s -X POST http://127.0.0.1:8900/api/chat/reset -H 'Content-Type: application/json' -d '{"key":"<taskId或global>"}'  # 重置某论文的 AI 会话
```

## 八、待办

1. 修第四节的核心 bug(点击文献打不开);
2. 修完后 `./build-deb.sh` 重打包升级;
3. (可选)AI provider 的 key/地址外置为配置文件(目前写死在 DEFAULT_AI_PROVIDERS 与环境变量)。
