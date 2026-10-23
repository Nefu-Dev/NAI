# NAI — 本地 AI 助手

`NAI` 是把仓库里原有占位集群 `AI_Cluster`（`cluster.py`）扩展成的**真实微调小模型助手**：
用一个小型双语基座做 LoRA 微调，量化成 GGUF，配一个 **Claude 风格的 CLI 终端**（桌面应用，无 HTML），
支持**实时观看推理**、模型**读写文件 / 执行命令（可视化确认）**、**中/英双语**、**低资源占用**，并**一键打包成单个 EXE**。

```
NAI/
├─ build.bat              一键构建（fast = 只重新打包 EXE；build.bat full = 全流程重训）
├─ start.bat              开发模式直接运行（源码）
├─ requirements.txt
├─ train.py               LoRA 微调 Qwen2.5-1.5B -> models/NAI-finetuned-1.5B
├─ make_gguf.py           合并模型 -> 量化 GGUF（Q4_0，离线转换，无需联网）-> models/nai.gguf
├─ build_exe.py           PyInstaller 打包（只打包 nai.gguf + 运行库）
├─ dataset/
│   └─ make_dataset.py    生成双语/工具调用/安全拒答/超控/YOLO数据集（856 条）
├─ nai/                   应用本体（CLI 终端、推理引擎、工具、安全）
│   ├─ gui.py             Claude 风格终端（Tkinter，流式推理 + 监控面板）
│   ├─ agent.py           对话 + 工具调用循环
│   ├─ worker.py          llama.cpp GGUF 推理引擎（流式）
│   ├─ tools.py           安全文件/命令执行（58 个工具，含 MCP/工具/超控/视觉/联网/批量/子智能体）
│   ├─ isolation.py       隔离模式：full/partial/ai/none（可切换、持久化）
│   ├─ subagent.py        子智能体编排：并行完成多个子任务
│   ├─ batch.py           批量操作：并行读/写/搜索 + 超大项目分块读
│   ├─ selfheal.py        出错自愈：纠错提示 + 有界重试
│   ├─ autostart.py       开机自启/持久化（任务计划 + 注册表）
│   ├─ webutil.py         联网查询：web_search / web_fetch（纯标准库）
│   ├─ supervisor.py      超控能力：截屏 OCR + 点击/滚动/输入/按键（ctypes）
│   ├─ vision.py          YOLO 目标检测 -> 文字（onnxruntime + yolov8n.onnx）
│   ├─ selftest.py        无界面自测
│   └─ ...
├─ models/nai.gguf        量化后的模型（EXE 唯一捆绑的模型）
└─ dist/NAI.exe           最终产物
```

---

## 项目总结（能力总览）

NAI 是一个**真实微调、离线运行、可一键打包 EXE** 的本地 AI 助手（Qwen2.5-1.5B-Instruct 做 LoRA 微调 → Q4_0 量化）。像 Claude 的本地终端：你看着它"边想边做"——读你的项目、写/追加代码、执行命令、在确认后控制电脑，全部本机完成、不上传任何数据。

| 维度 | 内容 |
|---|---|
| 模型 | Qwen2.5-1.5B-Instruct（LoRA 微调）→ Q4_0 GGUF（models/nai.gguf ≈ 1006MB） |
| 形态 | 窗口终端 `dist\NAI.exe` + Rich 命令行终端 `NAI_cli.bat` / `python run_nai_cli.py` |
| 语言 | 中/英双语自动跟随；行为像正常 AI（已移除院校身份文案） |
| 观看推理 | 逐 token 流式生成（思考）、工具调用面板、tok/s 状态行、代码块配色高亮 |
| 环境感知 | 系统提示自动注入本机环境（OS/Python/CPU/内存/工作目录/时间）；`/env` 查看、`system_info` 工具 |
| 长代码 | 请求代码/长文时自动放宽输出上限（最长 4096）；`/maxtokens <n>` 手动设置 |
| 文件 / 代码 | 读/写/追加代码、整读项目 `read_project`、列目录、搜索、grep、shell（黑名单+确认） |
| 规则 | `/rule <文本>` 持久化自定义规则并注入系统提示（`/rules` 查看、`/rule clear` 清空） |
| 目录自动识别 | 用户提到或模型访问到的真实路径目录**自动放行**并持久化（`工作目录/nai_allowed.txt`），不再因 "path outside allowed directories" 卡住；写入沙盒外的操作仍逐条确认；`/dirs` 查看、删文件即可撤销 |
| 项目上下文 | 自动读取工作目录 `README.md` / `nai_context.txt` 等注入系统提示，让 NAI 一进来就懂这个项目；`/context` 查看 / `auto` 重扫 / `clear` 关闭 / 指定文件 |
| 对话记录 | CLI 与窗口版每轮对话自动保存到 `工作目录/nai_history/<时间戳>.jsonl`（本地）；`/sessions` 列表、`/resume [索引|片段]` 随时切入载入继续聊、`/history [n]` 查看、`/new` 开新会话（旧会话保留） |
| 目标系统 | `/goal <目标>` 设置目标：达成前 NAI 持续用工具推进、跨轮次不结束对话（`/goal status` 查看、`clear/done` 结束） |
| 工具调用 | **无限次**（无固定上限，模型继续调工具就继续执行；仅保留 500 步极高安全阀防死机，`tool_guard` 可调） |
| MCP | 内置 MCP 客户端桥（stdio + HTTP）：`/mcp list|reload`、`mcp_call("server.tool", …)` 对接浏览器/文件等 MCP server |
| 超控 | 截屏 OCR 识屏、点击/滚动/输入/按键、YOLO 物体识别（均需确认） |
| 安全 | 沙盒隔离（allowed_roots）、危险命令硬拦截、calc AST 白名单、逐条确认 |
| 隔离模式 | `/isolation full|partial|ai|none` 四种可切换：全部隔离 / 仅危险指令隔离 / AI判断隔离（模型逐条判断 安全=自动·有风险=询问·危险=拦截）/ 无隔离；持久化到 `nai_isolation.txt` |
| 子智能体 | NAI 可派生子智能体并行完成多个子任务（`subagent` / `subagents` 工具、`/subagents` 命令），各自独立上下文与工具权限 |
| 批量操作 | 多线程/异步并行：`batch_read`（批量读）、`batch_write`（批量写代码）、`batch_search`（批量上网查询）、`read_big`（分块读超大项目，返回清单+首批文件） |
| 出错自愈 | 工具调用出错时把错误回喂模型做纠正性重试（自愈提示 + 有界重试），连续失败到上限后如实汇报阻塞点 |
| 开机自启 | `/autostart on|off|status` 注册/注销开机自启（任务计划/注册表，存进系统），关机后重启自动恢复 |
| 联网查询 | `web_search`（文本结果）、`web_fetch`（抓取网页文字）、`web_open`（浏览器打开）；纯标准库、带超时 |
| 占用 | 运行内存 ~2.5–3.1GB，纯 CPU，无需联网 |
| 工具 | 内置 58 个工具/命令（文件、代码、shell、MCP、网络/剪贴板/哈希/随机、超控、视觉） |
| 产物 | `dist\NAI.exe`（约 1.2GB，单文件自包含） |

---

## 快速开始

**直接运行（已打好包）**
```
dist\NAI.exe                # 打开终端（窗口版）
dist\NAI.exe --selftest     # 无界面自测，结果写入 selftest_result.json
```

**命令行终端版（Rich 精美 CLI，实时观看 AI 思考/工具调用/回答）**
```
NAI_cli.bat                 # 一键命令行启动（或 python run_nai_cli.py）
```
CLI 与窗口版共享同一套模型/工具/沙盒：流式显示 AI 生成（思考）、每个工具调用的面板与结果、
tok/s 状态行；命令 `/help /workspace /allow /dirs /supervisor on|off /autoshell /model /stats /exit` 全部可用。

**一键构建 EXE**
```
build.bat full             # 全流程：数据集 -> 微调 -> GGUF -> EXE（首次/想重训时）
build.bat                  # 快速：已有 models\nai.gguf 时只重新打包
```

**开发模式（源码跑，免打包）**
```
start.bat
```

---

## 使用

- 直接在底部 `❯` 输入即可与 NAI 对话（自动识别中文/英文回复），**回复逐 token 流式显示**（可实时看到生成过程）。
- 让它管理文件/目录/命令，例如：
  - `看看 D:/AI_Cluster/todo.txt`（read_file）
  - `把 hello 写入 D:/AI_Cluster/NAI/demo.txt`（write_file）
  - `列出 D:/AI_Cluster 的文件夹`（list_dir）
  - `运行 python --version`（shell）
- 内置 **58 个工具/命令**：文件（`read_file / read_project / list_dir / write_file / append_file / mkdir / move_file / copy_file / delete_file / file_info / search_files / grep_file / head / tail / count_lines / hash_file / touch / disk_usage`）、shell、MCP（`mcp_call / mcp_list / mcp_reload`）、实用（`web_open / screenshot_save / clipboard_get / clipboard_set / env / process_list / json_pretty / base64_encode/decode / url_encode/decode / random_uuid / random_int`）、超控/视觉（`screenshot / detect_image / click / double_click / right_click / move / scroll / type_text / press / find_text / click_text`）、联网（`web_search / web_fetch`）、批量（`batch_read / batch_write / batch_search / read_big`）、子智能体（`subagent / subagents`）
- 命令 `/help  /clear  /lang zh|en  /workspace <dir>  /allow <dir>  /context [auto|clear|<文件>]  /resume [索引|片段]  /sessions  /history [n]  /new  /autoshell on|off  /stats  /model  /exit`

### 安全模型
- 模型**只能读写“工作目录 + 已允许目录”内**的文件；工作目录外的写入/移动/删除会请求你确认。
- **自动识别目录**：对话里提到或模型访问到的真实路径目录会自动加入允许列表（持久化到 `工作目录/nai_allowed.txt`，重启保持），所以 NAI 可以直接读 `D:/AI_Cluster/notes` 这类目录而不再报 "path outside allowed directories"；写入沙盒外的操作依然逐条确认，`/dirs` 可随时查看当前范围。
- 执行命令默认**逐条请求确认**（输入 `y` 允许 / `n` 拒绝）；危险命令（删除、格式化、改系统等）被硬拦截。
- `calc` 用 AST 白名单校验，只允许数字与四则/幂运算，杜绝注入。
- `/autoshell off` 可关闭命令确认（有风险，慎用）。

### 观看推理
- 右侧“推理监控”面板实时显示：生成 token、速度(tok/s)、上下文占用、内存、运行时长，并绘制 tok/s 曲线。
- 模型调用工具时会在终端里以彩色块展示调用与结果。

---

## 关于模型（为什么从 0.5B 升到 1.5B）

初始按“0.25B”需求采用 **Qwen2.5-0.5B-Instruct**（约 0.49B，同时较好支持双语的最小基座）做了第一版：聊天流畅、
但实测**不会自主调用工具**——让它写文件只说“我将写入”、却不发 `⟪TOOL:write_file⟫`；让它跑命令甚至**编造输出**
（伪造 “Python 3.8.5”）。0.5B 是模型容量的硬限制，提示优化唤不醒工具协议。

应需求升级为 **Qwen2.5-1.5B-Instruct** 后重新微调：现在**能真实调用工具**——写文件真正落到磁盘、
跑命令返回真实输出（如 `python --version` → Python 3.14.7），且不会死循环。聊天、中英双语、观看推理能力同步保留。

### 为什么是 Q4_0 而不是 Q4_K_M
Qwen2.5 的嵌入维度是 151936×1536；1536 与 151936 都不是 256 的倍数，K 量化会逐张量回退到
q8_0/q5_0，体积几乎没有下降。改用 block=32 的 **Q4_0** 可全量量化到 ~1006MB，实测质量良好（中英、工具调用都正常）。

### 资源占用（本机实测）
| 项目 | 数值 |
|---|---|
| 模型 | Qwen2.5-1.5B-Instruct（LoRA 微调） |
| 量化 | Q4_0（GGUF，models/nai.gguf ≈ 1006MB） |
| EXE 体积 | 约 1.1 GB（dist/NAI.exe，单文件） |
| 运行内存 | 约 2.5–2.9 GB（上下文 6144） |
| 推理速度 | 约 16–29 tok/s（本机 CPU） |
| 硬件 | 任意 CPU（无需 GPU） |

---

## 超控能力（屏幕识别 + 电脑控制）

> 触发方式为**按需调用**，非后台循环，占用可控。

- **开启**：终端输入 `/supervisor on` 并按提示确认（开启需用户确认，即“确认后即可超控”）。
- **关闭**：`/supervisor off`。
- 能力（工具，均需逐条确认）：
  - `screenshot`：截屏 → **Windows 内置 OCR**（中文引擎）识别屏幕文字 → 返回文字+屏幕坐标 `(x,y)`。截图**仅在内存中处理、从不写入磁盘**（天然满足“识别完立即删除”）。
  - `click / double_click / right_click / move`：按坐标点击/移动鼠标（ctypes）。
  - `scroll`：滚动（负值向下）。
  - `type_text`：模拟键盘输入（支持中文等任意字符，SendInput UNICODE）。
  - `press`：按键 / 组合键（如 `enter`、`ctrl+c`、`alt+f4`）。
  - `detect_image("screen"|"文件路径")`：**YOLO 目标检测**（onnxruntime + yolov8n.onnx，纯 CPU），把图片/屏幕里的物体（人/笔记本/手机/车等）识别成文字描述，让纯文本的 NAI 能"看懂画面里的东西"。
- **安全**：总开关（`/supervisor`）+ 每条控制动作弹确认；点击/输入/滚动/按键都要你 `y` 才执行。
- **沙盒隔离**：文件工具被严格限制在 `allowed_roots`（工作目录 + `/allow` 允许的目录），越界路径直接拒绝；shell 以工作目录为 cwd 运行并过黑名单 + 确认。可用 `/dirs` 或 `/sandbox` 查看当前沙盒范围。
- **切换目录**：`/workspace <目录>` 切换工作目录（沙盒根随之切换）；`/allow <目录>` 额外放行目录。
- **说明**：NAI 的 1.5B 是纯文本模型，无法“看见”图片——屏幕/图片内容通过 **OCR（文字）+ YOLO（物体）** 两条通道转成文字喂给模型，模型据此理解场景。工具层已实测可用（EXE 内 OCR/YOLO 自测通过）；但旧微调权重对超控工具的**自主编排还不够稳定**，可靠让模型自动“看屏→点击”需带超控样例重训（数据集已补样例，重训需腾出约 12GB 空闲内存）。

---

## 规则 / MCP / 浏览器

- **自定义规则**：`/rule 回答尽量简短` 添加一条规则（持久化到工作目录 `nai_rules.txt`，注入系统提示，NAI 会遵守）；`/rules` 查看，`/rule clear` 清空。CLI 与窗口版都有。
- **项目上下文**：启动或 `/workspace` 切换目录时，NAI 自动读取工作目录的 `README.md` / `nai_context.txt` / `CONTEXT.md`（按优先级），把项目介绍注入系统提示，让它一进来就懂这个项目；`/context` 查看当前上下文，`/context auto` 重新扫描，`/context clear` 关闭，`/context <文件>` 指定用某个文件。
- **对话记录（本地）**：CLI 与窗口版每轮对话自动追加保存到 `工作目录/nai_history/<时间戳>.jsonl`，全程本机、不上传；`/sessions` 列出历史会话，`/resume`（或 `/load`）随时载入任意会话继续对话，`/history [n]` 回看最近 n 轮，`/new` 开新会话（旧会话仍保留在本地）。
- **MCP 支持**：NAI 内置 MCP 客户端桥（stdio + HTTP 两种传输）。在 `mcp.json`（参考 `mcp.json.example`）里配置 MCP server（如 Playwright 浏览器 MCP、filesystem MCP 等），然后 `/mcp list` 查看可用工具、`/mcp reload` 重载。模型可用 `⟪TOOL:mcp_call("server.tool", "{\"arg\": value}")⟫` 调用它们，等于把任意外部工具能力挂进 NAI。
- **浏览器（真实操控 + 可视化）**：`mcp.json` 已配置 Playwright 浏览器 MCP（`browser.*` 工具：`browser_navigate / browser_click / browser_type / browser_take_screenshot / browser_snapshot` 等），NAI 通过 `mcp_call("browser.browser_navigate", …)` 真实控制 Chromium 窗口。**可视化**：浏览器返回的截图（base64）会被 NAI 自动保存到 `工作目录/nai_shots/*.png` 并在 GUI 展示/提示路径。若本机缺浏览器，在项目目录运行 `npx -y @playwright/mcp@latest install` 对应的浏览器安装命令即可。
- **输出限制已解除**：已移除系统提示里的院校身份与"我不能联网/不能看屏幕"等自我设限，NAI 像正常 AI 一样作答；单次回复上限也提高到 1024 tokens（`/stats` 可看）。

---

## 新增能力（隔离模式 / 子智能体 / 批量 / 自愈 / 开机自启 / 联网）

### 1. 隔离模式（四种，用户可随时切换）
`/isolation full|partial|ai|none`（CLI 与窗口版都有；`/isolation` 或 `/isolation status` 查看当前）。
选择持久化到工作目录 `nai_isolation.txt`，重启后保持。

| 模式 | 含义 | 生效行为 |
|---|---|---|
| `full`（全部隔离，默认） | 严格沙盒 + 逐条确认 | 只能读写工作目录/已允许目录；命令、越界写文件、电脑控制、MCP、联网都询问 |
| `partial`（部分危险指令隔离） | 只隔离危险指令 | 危险命令/电脑控制/毁机级操作仍拦截或确认；普通命令、文件操作自动执行 |
| `ai`（AI判断隔离） | 模型逐条判断风险 | 判为安全→自动执行；有风险→询问；危险→拦截。电脑控制始终询问 |
| `none`（无隔离） | 无沙盒、无确认、无拦截 | 所有操作直接执行；但毁机级底线（格式化/删系统/清注册表等）永不放开 |

> 切换后新工具/命令立即按新模式生效；越权时用 `/allow <目录>` 或换模式即可放行。

### 2. 子智能体（并行完成多个子任务）
NAI 可把任务拆给多个子智能体并行完成，每个子智能体有独立上下文与工具权限：
- 命令：`/subagents 任务1 | 任务2 | 任务3`（并行跑，各自返回结果）。
- 工具：`⟪TOOL:subagents("任务1\n任务2", "4", "1024")⟫` 并行多个；`⟪TOOL:subagent("任务")⟫` 跑单个。
- 说明：子智能体共享同一个本地 GGUF 模型，**推理串行**（模型线程锁），但它们的文件/联网等 I/O 并行——这是本机单模型的真实上限，文档如实说明。

### 3. 批量操作（多线程/异步）
- `⟪TOOL:batch_read("a.py\nb.py", "24000")⟫`：并行读多个文件。
- `⟪TOOL:batch_write("{\"a.py\":\"代码\",\"b.py\":\"代码\"}")⟫`：一次写多个文件。
- `⟪TOOL:batch_search("q1\nq2", "5")⟫`：并行跑多个联网查询。
- `⟪TOOL:read_big("大项目目录", "30", "yes", "24000")⟫`：读超大项目——先并行出**全部文本文件清单**（路径/大小/行数），再并行读首批文件到预算；文件太多时分步用 `read_file/batch_read` 继续读，不会撑爆上下文。

### 4. 出错自愈
工具调用出错时，NAI 不再直接放弃：把错误回喂模型 + 给出针对性纠错提示（如"路径不存在→先 list_dir"），
做有界重试；连续失败到上限（默认 8 次）后停止调工具、如实汇报阻塞点。逻辑见 `nai/selfheal.py`。

### 5. 开机自启 / 持久化（存进系统）
`/autostart on|off|status`：注册/注销 Windows 开机自启（优先任务计划 `NAI_Agent`，失败回退注册表 Run 键），
存进系统，关机重启后 NAI 自动恢复运行。`/autostart status` 查看是否已注册。可随时 `/autostart off` 移除。

### 6. 联网查询
- `⟪TOOL:web_search("关键词", "6")⟫`：返回纯文本搜索结果（标题+链接+摘要）。
- `⟪TOOL:web_fetch("url")⟫`：抓取网页并转成可读文字。
- 纯标准库实现、带超时；无外网时友好报错，不影响其它能力。

> 所有新命令/工具已接入 CLI 与窗口版；`run_nai_cli.py` 启动时会自动把控制台切到 UTF-8（`chcp 65001`），
> 保证中文显示正常。运行 `python nai_feature_test.py` 可对以上新模块做无模型功能自测。

### 7. 输出不截断 / 直接截屏识图
- **read_file 无硬性上限**：默认不再限制 200KB、也不截断，读多大返回多大；用 `/readlimit <字节|0>` 设置上限（0=不限，默认不限）。shell 输出上限也放开为可配置（`tools.shell_output_limit`）。
- **回复不截断**：模型上下文默认调大到 **16384** token（可用环境变量 NAI_CTX 调整，如 8192/12288/16384；实测约 4GB），代码/长文输出预算上限提高到 12000（`/maxtokens`）。
  > 说明：模型一次能"看到"的内容仍受上下文窗口限制——工具结果再长，超过上下文的部分会由提示构造器优雅截断以保稳定，这是所有本地模型的共同物理上限。
- **截屏 / 识图无需先开超控**：只读的 `screenshot`（OCR 识屏）和 `detect_image`（YOLO 识图）现在可直接调用（full 模式仍逐条确认）；`click / type / press` 等**控制类**动作仍要求 `/supervisor on` + 逐条确认，安全边界不变。

## 数据集可自定义
`dataset/data/naifinetune.jsonl`（每行一条 `{"messages":[...]}`，856 条）：
- 中英双语问答、语言跟随
- 工具调用（read_project / read_file / list_dir / write_file / shell / 超控 / YOLO 等）及结果续接
- 安全拒答、能力边界

> 若想要更小体积、能忍受工具调用变弱：把 `train.py` 里的 `NAI_BASE` 改回 `Qwen/Qwen2.5-0.5B-Instruct` 重训即可。

---

## 扩展说明（相对原 AI_Cluster）
- 保留原 `cluster.py / start.bat / README.txt` 未动。
- 新的 master/worker 概念落到 `nai/agent.py`（任务循环）与 `nai/worker.py`（推理引擎）：
  占位的 `run_job()` 被真实 GGUF 推理 + 工具执行取代。
- **移除了 HTML 状态页**，改为桌面 CLI 终端（Tkinter），全流程仅本机运行、不上传任何数据。
