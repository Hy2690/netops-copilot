# NetOps Copilot v2（WSL + RAG 知识库版）复现教程与技术讲解

> 本文档是 v2 版本的完整指南：把项目迁移到 WSL2 运行，并为 Agent 装上"长期记忆"——
> 基于 RAG 的运维知识库（Runbook / 历史工单 / 拓扑规划 / 变更规范）。
> 前置阅读：《详细复现教程与技术讲解.md》（v1，包含 ReAct、护栏等基础原理，本文不再重复）。

---

# 第 0 部分：v2 更新了什么

```javascript
                      v1                          v2
        ┌───────────────────────┐     ┌───────────────────────────┐
        │        LLM 大脑        │     │          LLM 大脑          │
        └───────────┬───────────┘     └──────────┬────────────────┘
                    │ tool call                  │ tool call
        ┌───────────┴───────────┐     ┌──────────┴─────────────────┐
        │ 工具层（3 个工具）      │     │ 工具层（4 个工具）            │
        │ · 拓扑/只读命令/变更    │     │ · 拓扑/只读命令/变更          │
        │ · 白名单+审批+审计     │ ──> │ · search_knowledge_base ★新  │
        └───────────┬───────────┘     │ · 白名单+审批+审计           │
                    │                 └──────┬──────────────┬───────┘
        ┌───────────┴───────────┐            │              │
        │ mock 网络 / Netmiko    │     ┌──────┴──────┐  ┌────┴─────────┐
        └───────────────────────┘     │ mock/Netmiko │  │ RAG 知识库 ★新│
                                      └──────────────┘  │ bge-m3 嵌入   │
        运行环境：Windows 原生          ───────────────> │ ChromaDB 向量库│
                                                         └──────────────┘
                                      运行环境：WSL2（Ubuntu）★新
```

**RAG 给 Agent 带来的变化**：v1 的 Agent 只懂"通用网络知识"（模型参数里的）；
v2 的 Agent 还懂"你这个网络的历史"——哪条链路上周割接过、哪个设备是已知风险单点、
这类故障的 SOP 是什么。这正是企业里 Agent 真正值钱的地方。

---

# 第一部分：WSL 环境搭建

## 1.1 为什么迁到 WSL

| 维度 | Windows 原生 | WSL2（Ubuntu） |
| --- | --- | --- |
| 与生产环境一致性 | 服务器几乎都是 Linux | ✅ 一致 |
| 运维工具链 | 很多工具（Containerlab、FRR、gNMI 工具）只有 Linux 版 | ✅ 原生支持 |
| Docker 支持 | 需 Docker Desktop 中转 | ✅ 原生/可选 Docker Engine |
| 简历叙事 | "在本机跑的" | ✅ "在 Linux 环境部署的" |

## 1.2 安装 WSL2 + Ubuntu

管理员 PowerShell 执行：

```powershell
wsl --install          # 自动安装 WSL2 + 默认 Ubuntu，完成后重启电脑
wsl -l -v              # 重启后验证：VERSION 列应为 2
wsl --set-default-version 2
```

重启后从开始菜单打开 "Ubuntu"，首次启动会让你创建 Linux 用户名和密码（与 Windows 无关，自己记住即可）。

> 若 `wsl --install` 报错，检查：BIOS 开启虚拟化（VT-x/AMD-V）；
> Windows 功能里勾选"适用于 Linux 的 Windows 子系统"和"虚拟机平台"。

## 1.3 GPU 直通验证（关键一步）

WSL2 通过 **GPU 半虚拟化**共享 Windows 的显卡，**不需要也不应该**在 WSL 里安装 NVIDIA Linux 驱动。

1. 在 **Windows 侧**把 NVIDIA 驱动更新到最新版（GeForce Experience / 官网）
2. 在 WSL 的 Ubuntu 终端里执行：

```bash
nvidia-smi
# 能看到 RTX 5080 和驱动版本号，说明 GPU 直通成功
```

> 原理：Windows 驱动里自带了对 WSL 的支持（libcuda 经由 /usr/lib/wsl 注入）。
> **千万别在 WSL 里 apt 安装 nvidia-driver**，会把直通驱动覆盖掉导致 GPU 不可用。

## 1.4 在 WSL 安装 Ollama 并拉取模型

```bash
# 一条命令安装（官方脚本）
curl -fsSL https://ollama.com/install.sh | sh

# 验证（新版 Ubuntu 的 systemd 已默认启用，Ollama 会作为服务自启）
ollama -v
curl localhost:11434        # 返回 "Ollama is running"

# 拉取嵌入模型（RAG 需要）
ollama pull bge-m3          # ~1.2GB，中文友好的嵌入模型（RAG 专用）

# 主模型：Qwen3.8-27B-GSQ-RCO-IQ3_S（标准 GGUF，11.8GB，基准近乎无损）
mkdir -p ~/models && cd ~/models
wget -c https://hf-mirror.com/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF/resolve/main/Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf
cat > Modelfile <<'EOF'
FROM /home/你的用户名/models/Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf
PARAMETER temperature 0
PARAMETER num_ctx 16384
EOF
ollama create qwen38-gsq -f Modelfile
ollama run qwen38-gsq "用一句话解释 BGP"   # 测试模型可用
ollama ps                                  # 确认 100% GPU
cd ~

# 可选：速度优先备选（MoE 架构，仅 3.6B 激活，快很多）
ollama pull gpt-oss:20b
ollama list
```

> **备选方案**：也可以复用 Windows 上已经装好的 Ollama——Windows 侧设置环境变量
> `OLLAMA_HOST=0.0.0.0` 并重启 Ollama，然后在 WSL 里
> `export OLLAMA_HOST=http://$(ip route show | grep default | awk '{print $3}'):11434`。
> 但既然迁了 WSL，建议直接在 WSL 里装，链路更干净。

## 1.5 Python 环境与项目文件

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git

# 把项目从 Windows 盘拷进 WSL  home 目录（⚠️ 不要直接在 /mnt/d 下跑，
# 跨文件系统 IO 极慢，ChromaDB 读写索引会卡）
cp -r /mnt/d/dev/netops-copilot ~/netops-copilot
cd ~/netops-copilot

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

# 第二部分：v2 复现步骤

## 2.1 构建知识库索引

```bash
python rag.py rebuild
# 预期输出：索引构建完成：XX 个 chunk → .../chroma_db（嵌入模型: bge-m3）
```

这一步做的事：读取 `knowledge/` 下 6 份 Markdown → 按标题/段落切成 chunk →
逐块调用本地 bge-m3 转成向量 → 写入 ChromaDB（持久化在 `chroma_db/` 目录）。
**只有文档变更后才需要重建**，平时启动直接读索引。

## 2.2 验证检索效果（很重要，先玩这个）

```bash
python rag.py query "BGP 邻居中断了怎么处理"
python rag.py query "leaf3 这台设备有什么风险"
python rag.py query "监控采集频率有什么规定"
```

你会看到返回的片段带着【来源文件 | 相关度】标注——这就是 Agent 将来"看到"的知识。
如果这几条查询都能命中正确文档，说明索引质量 OK。

## 2.3 运行 RAG 增强版 Agent

```bash
python agent.py
```

**重点演示：选场景 2（spine1 与 leaf2 间 BGP 会话异常）**。
v2 的排查轨迹里会多出知识库调用：

```javascript
[调用工具] get_topology({})
[调用工具] search_knowledge_base({'query': 'leaf2 spine1 BGP 邻居中断 历史故障'})
  [工具返回] 【来源: 历史工单.md | 相关度: 0.89】INC-2026-0918：spine1 与 leaf2 间
             BGP 会话中断…根因：割接调整 BGP timer 配置，hold timer 双端不匹配…
[调用工具] run_network_command({'device': 'spine1', 'command': 'show ip interface brief'})
  [工具返回] ... Eth1/2 up ...          ← 链路正常！
[调用工具] run_network_command({'device': 'spine1', 'command': 'show bgp summary'})
  [工具返回] ... leaf2  Idle ...
[调用工具] search_knowledge_base({'query': 'BGP Idle hold time expired 处理流程'})
  [工具返回] 【来源: runbook-BGP故障处理.md】核心原则：先链路，后协议…

===== 诊断结论 =====
根因：spine1 与 leaf2 之间 BGP 会话异常（协议层，非链路层）……
关键证据：互联链路 up 但邻居 Idle，日志显示 hold time expired……
关联历史：9 月 18 日 INC-2026-0918 曾发生同类故障，根因为割接导致 timer
不匹配（来源：历史工单.md），建议优先核对近期变更记录……
修复建议：按 RB-BGP-001（来源：runbook-BGP故障处理.md），审批后执行
clear ip bgp * 重建会话……
```

对比 v1：同样的症状，v2 多了**"和历史工单对上了暗号"**和**"修复建议引用了 SOP 编号"**——
这就是 RAG 的肉眼可见的价值。

## 2.4 纯知识问答玩法

自由对话模式下也可以不碰设备，只查知识库：

```javascript
描述你观察到的故障现象: 我们网络里哪台设备是已知的风险单点？有什么改造计划？
# Agent 会调用 search_knowledge_base，找到 RISK-001 并回答：
# leaf3 单上联无冗余，改造从 2026-Q3 延期至 Q4，期间上联故障按 P1 处理
```

## 2.5 复跑评估

```bash
python eval.py   # 4 个场景全部支持 RAG 增强排查，审计日志里能看到 kb: 开头的检索记录
```

## 2.6 RAG 挂载详解：知识库是怎么"长"在 Agent 上的

前面三步你看到了 RAG 的**效果**，这一节拆开看**接线**。RAG 在本项目中不是一条独立流水线，
而是作为一个**新工具**挂载到既有 Agent 上——总共三个挂载点，改动不到 60 行代码：

```javascript
【挂载点 1：检索引擎】 rag.py（新建，独立可测试）
   knowledge/*.md ──> 切分/嵌入/向量库 ──> search(query) 返回文本
            │
【挂载点 2：工具适配】 tools.py 的 search_knowledge_base()（新增约 20 行）
   把 rag.search 包装成 LangChain 工具，并挂上护栏（审计留痕、异常兜底）
            │
【挂载点 3：Agent 注册】 agent.py（改 2 行 + 提示词加 1 条纪律）
   tools=[..., search_knowledge_base]  +  提示词纪律⑥（何时查、注明来源）
```

这种分层是刻意的：**rag.py 不依赖 Agent 可以单独测试，tools.py 负责护栏，
agent.py 只做注册**——任何一层出问题都能独立定位（见 2.6.5）。

### 2.6.1 挂载点 1：检索引擎 rag.py

`python rag.py rebuild` 执行时，每一步在做什么：

| 步骤 | 代码 | 发生了什么 |
| --- | --- | --- |
| 读文档 | `KNOWLEDGE_DIR.glob("**/*.md")` | 扫描 knowledge/ 下全部 Markdown，每份读成一个 Document，metadata 记录来源文件名 |
| 切分 | `_SPLITTER.split_documents(docs)` | 按 标题→段落→句号 的优先级切成约 400 字的块，块间重叠 60 字 |
| 嵌入 | `OllamaEmbeddings(model="bge-m3")` | 逐块发 HTTP 请求给本地 Ollama（127.0.0.1:11434），bge-m3 返回 1024 维向量 |
| 入库 | `Chroma.from_documents(...)` | 向量+原文+来源写入 chroma_db/ 目录，持久化落盘 |

检索时（`rag.search(query, k=3)`）是镜像过程：查询文本 → 用同一个 bge-m3 嵌入成向量 →
在 ChromaDB 里找距离最近的 3 块 → 拼上【来源|相关度】标注 → 返回纯文本。

**设计要点**：嵌入和推理用的是两个不同模型——嵌入永远走 bge-m3（约 1.2GB 常驻显存），
不受你切换主模型（OLLAMA_MODEL）影响。这叫"检索与推理解耦"：换主模型不用重建索引，
换嵌入模型才需要 `rebuild`。

### 2.6.2 挂载点 2：工具适配（tools.py）

rag.py 返回的是"裸文本"，要变成 Agent 可用的工具还需包一层
（tools.py 中的 `search_knowledge_base`），这一层做了三件事：

1. **`@tool` 装饰器 + docstring**：docstring 会被自动转成工具的 JSON Schema 说明书注入模型
上下文。里面写的两个"使用时机"（排查开始时查相似历史 / 给修复建议前查 SOP）
直接决定模型什么时候想起调用它——**工具描述是写给模型看的提示词**。
2. **异常兜底**：知识库索引不存在或检索失败时，返回提示文本而不是抛异常让 Agent 崩溃——
工具挂了，Agent 还能继续基于设备证据排查（优雅降级）。
3. **护栏复用**：`_audit("read", "-", f"kb:{query}", result)` 把每次检索也写进审计日志，
与命令执行共用同一套留痕体系（audit.log 里 `kb:` 开头的记录就是它）。

### 2.6.3 挂载点 3：Agent 注册（agent.py）

只有两处改动，但缺一不可：

1. `tools=[get_topology, run_network_command, apply_remediation, search_knowledge_base]`
——注册后，模型上下文里的"工具说明书"才多出这一项；
2. 提示词纪律⑥："排查过程中主动用 search_knowledge_base 检索相似历史工单与处理手册；
结论中引用了知识库内容时，必须注明来源文档。"

**经验之谈：只注册工具、不写提示词纪律，模型大概率想不起来用它。**
工具注册解决"能不能"，提示词纪律解决"用不用"。

### 2.6.4 一次 RAG 调用的完整数据流

把 2.3 节场景 2 的轨迹展开到代码层：

```javascript
1. 模型决策：看到"BGP 邻居中断"现象 → 按纪律⑥决定先查知识库
   → 输出结构化调用 search_knowledge_base({"query": "leaf2 spine1 BGP 邻居中断 历史故障"})
2. LangGraph 解析 tool_calls → 定位到 tools.py 中的函数 → 真正执行 Python 代码
3. 函数内：rag.search() 将查询发给 bge-m3 嵌入 → ChromaDB 检索
   → 命中《历史工单.md》的 INC-2026-0918 片段
4. 返回格式化文本 → _audit 落一条 kb: 日志 → 文本作为 ToolMessage 回填进对话历史
5. 模型带着工单上下文继续推理 → 决定再用 run_network_command 验证链路状态
6. 最终结论引用工单编号并注明来源 → 循环结束
```

注意第 5 步：**RAG 的检索结果不是终点，而是 Agent 下一轮决策的输入**——
这正是"Agentic RAG"中 Agent 二字的含义（对比分析见 3.6 节）。

### 2.6.5 每层怎么独立验证（排错定位指南）

| 层 | 验证方法 | 正常表现 |
| --- | --- | --- |
| 检索引擎（rag.py） | `python rag.py query "BGP 中断"` | 命中正确文档，来源标注清晰 |
| 嵌入模型 | rebuild/query 时执行 `ollama ps` | bge-m3 在列表中，100% GPU |
| 工具适配（tools.py） | 查 audit.log | 有 `"command": "kb:..."` 的记录 |
| Agent 决策（agent.py） | 看运行时 trace 轨迹 | 轨迹中出现 search_knowledge_base 调用 |

排错时自下而上逐层验证：`rag.py query` 结果就不对 → 问题在索引/文档质量；
query 正确但 Agent 从不调用 → 问题在提示词纪律或模型的工具调用能力。

### 2.6.6 调参旋钮速查表

| 旋钮 | 位置 | 影响 |
| --- | --- | --- |
| chunk_size / overlap | rag.py `_SPLITTER` | 检索精度：块大噪声多，块小语义碎 |
| k（返回块数） | rag.py `search(query, k=3)` | 召回率与上下文噪声的权衡 |
| EMBED_MODEL | 环境变量 | 换嵌入模型（改完必须 rebuild 重建索引） |
| 文档本身 | knowledge/*.md | 质量上限：垃圾进垃圾出 |
| 提示词纪律⑥ | agent.py SYSTEM_PROMPT | Agent 何时、是否主动查知识库 |

---

# 第三部分：RAG 技术讲解

## 3.1 RAG 解决什么问题

LLM 的知识有两个死穴：

1. **有截止日期**：模型训练完那一刻之后的知识它一概不知
2. **没有你的私有知识**：你网络的拓扑、历史工单、内部 SOP，它从来没见过

微调（Fine-tuning）可以解决一部分，但成本高、更新慢、容易灾难性遗忘。
**RAG（检索增强生成）的思路是"开卷考试"**：不让模型背书，而是在回答问题前，
先从知识库里把相关资料检索出来塞进上下文，让模型"看着资料作答"。

模型负责理解与推理，知识库负责记忆与事实——各司其职。

## 3.2 完整流水线

```javascript
【离线索引阶段】（python rag.py rebuild）
knowledge/*.md ──> ① 切分(chunk) ──> ② 嵌入(embed) ──> ③ 存入向量库
   6 份文档           几十个小块         每块一个向量      ChromaDB 持久化

【在线检索阶段】（Agent 调用 search_knowledge_base）
用户查询 ──> ④ 同样用 bge-m3 嵌入成向量 ──> ⑤ 在向量库找最相似的 k 块
──> ⑥ 把片段连同【来源】标注一起返回给 Agent ──> ⑦ 模型基于这些资料推理
```

## 3.3 Embedding：把语义变成可以计算的距离

嵌入模型把一段文字映射成一个高维向量（bge-m3 是 1024 维）。
**语义相近的文字，向量在空间中的距离就近**：

```javascript
"BGP 邻居中断"  → [0.12, -0.45, ..., 0.33]
"BGP 会话 down" → [0.11, -0.44, ..., 0.35]   ← 距离很近（措辞不同，语义相同）
"服务器 CPU 高" → [0.87, 0.21, ..., -0.61]   ← 距离很远
```

这就是为什么查询"BGP 会话 down"能命中写着"BGP 邻居中断"的文档——
关键词完全不同，但语义向量几乎重叠。**这是 RAG 区别于 Ctrl+F 关键词搜索的本质。**

**为什么选 bge-m3**：

- 中文质量第一梯队（智源 BAAI 出品，C-MTEB 中文榜前列）
- 最长支持 8192 token，长文档 chunk 不会被截断
- Ollama 一行命令本地跑，数据不出本机，零成本
- 与主模型（Qwen3.8-27B）完全解耦：嵌入模型只负责检索质量，推理模型只负责聪明

## 3.4 切分策略：被低估的质量决定因素

rag.py 里的切分参数，每一个都有讲究：

```python
RecursiveCharacterTextSplitter(
    chunk_size=400,        # 块太大 → 噪声多、检索不精准；太小 → 语义不完整
    chunk_overlap=60,      # 相邻块重叠，防止关键句被从中间切断
    separators=["\n## ", "\n### ", "\n\n", "\n", "。", "；"],
                           # 优先在标题/段落边界切，保持知识片段的完整性
)
```

工程经验：**RAG 系统 70% 的质量问题出在文档质量和切分，而不是模型。**
我们的知识库按"一份 Runbook 一个文件、结构化小节"组织，就是为了切出语义完整的块。

## 3.5 向量检索与 ChromaDB

- 相似度：余弦相似度（Chroma 默认返回距离，rag.py 里近似换算成相关度展示）
- top-k：rag.py 默认 k=3，返回最相关的 3 个片段。k 太小可能漏，太大塞爆上下文
- 持久化：`persist_directory=chroma_db`，索引落盘，不用每次启动重新嵌入
- 规模感：几百份文档这个量级，Chroma 绰绰有余；到十万级再考虑 Milvus/Qdrant

## 3.6 ★ Agentic RAG：本项目架构上最重要的认知

传统 RAG 是一条**固定流水线**：每个用户问题都强制先检索、再回答。
而本项目的做法是 **Agentic RAG——把检索做成一个工具，由 Agent 自主决定何时查、查什么、查几次**：

```javascript
传统 RAG：  问题 → 必检索一次 → 生成      （无脑检索，常与需求错位）
Agentic RAG：问题 → Agent 判断需要背景知识 → 构造检索词 → 看结果
                    → 觉得不够 → 换个角度再检索一轮
                    → 结合设备证据 → 交叉验证 → 结论注明来源
```

注意 2.3 节的轨迹：Agent 第一轮查"历史故障"，拿到工单后又第二轮查"处理流程"——
**检索词是根据排查进展动态构造的**，这是固定流水线做不到的。
这也是为什么工具 docstring 里写明了"使用时机"——那是在教模型什么时候该查知识库。

## 3.7 RAG 的失败模式

1. **垃圾进垃圾出**：文档过期/错误，Agent 会一本正经地引用错误 SOP → 知识库需要 owner 和验证日期（我们的 Runbook 头部都有）
2. **检索缺失**：该命中的没命中 → 调 chunk 策略、增大 k、查询改写
3. **切分边界**：关键句被拦腰切断 → overlap + 按结构切分
4. **时效性混乱**：旧工单覆盖新规范 → 元数据标注日期，检索结果里保留
5. **盲目信任**：模型把检索结果当圣旨 → 提示词要求"与设备证据交叉验证"

---

# 第四部分：知识库建设指南 + 真实开源运维文档

## 4.1 内置知识库的设计意图

`knowledge/` 下 6 份文档覆盖了运维知识库的四种基本类型，且每份都和故障场景有联动：

| 文档 | 类型 | 与故障场景的联动 |
| --- | --- | --- |
| runbook-链路故障处理.md | SOP | 场景 1（leaf3 链路）恢复步骤对齐 |
| runbook-BGP故障处理.md | SOP | 场景 2（BGP）"先链路后协议"原则 |
| runbook-CPU高处理.md | SOP | 场景 3（CPU 高）定位 SNMP 风暴 |
| 历史工单.md | 机构记忆 | 4 个场景各有对应工单/RISK 条目 |
| 拓扑与网段规划.md | 环境事实 | 冗余判断（P1/P3 定级依据） |
| 变更与审批规范.md | 流程约束 | Agent 发起审批时的行为准则 |

## 4.2 可以接入的真实开源运维文档（扩充知识库用）

把文档转成 Markdown 丢进 `knowledge/`，跑 `python rag.py rebuild` 即可接入：

1. **PagerDuty 事故响应文档**（Apache 2.0）
`git clone https://github.com/PagerDuty/incident-response-docs`
PagerDuty 把自己内部完整的事故响应流程开源了，含值班、分级、复盘、沟通模板，
是业界事实标准，中英双语社区翻译都有。
2. **Scoutflo SRE Playbooks**（MIT）——`github.com/Scoutflo/Scoutflo-SRE-Playbooks`
414 份现成的事故响应 playbook（K8s 232 份 + AWS 157 份 + Sentry 25 份），
全部是结构化 Markdown，**简直是现成的 RAG 语料**。
3. **Google SRE 丛书**（免费在线，sre.google）
《Site Reliability Engineering》与《The Site Reliability Workbook》，
其中 "Effective Troubleshooting" 一章堪称排障方法论圣经，可摘录进知识库。

> 建议：先用内置 6 份把流程跑通，再挑 10~20 份 Scoutflo playbook 接入，
> 观察知识库变大后检索质量的变化（这是很好的 eval 扩展实验）。

## 4.3 写好一份 Runbook 的要点

- **每一步都是命令，不是故事**：高压故障时没人读得动散文
- **带元数据头**：负责人、最近验证日期——过期文档比没有文档更危险
- **像代码一样管起来**：放 Git 仓库，改动走 PR，和项目一起版本化
- **写清"什么时候用它"**：开头一句适用场景，检索时这段话最影响命中

---

# 第五部分：WSL 常见问题（FAQ）

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| `nvidia-smi` 在 WSL 里找不到 | Windows 驱动太旧 | Windows 侧更新 NVIDIA 驱动 |
| 装了 nvidia-driver 后 GPU 消失 | 覆盖了 WSL 直通驱动 | `sudo apt purge '*nvidia*'` 后重启 WSL |
| Ollama 没自启 / 开机后连不上 | systemd 未启用 | 检查 `/etc/wsl.conf` 有 `[boot]\nsystemd=true`；或手动 `sudo service ollama start` |
| 项目跑得很慢 | 项目放在 /mnt/d 下 | 拷到 `~/` 目录再运行 |
| Chroma 报错/索引损坏 | 重建中断 | 删除 `chroma_db/` 目录后 `python rag.py rebuild` |
| 模型不调知识库工具 | 模型工具调用能力弱或 chat template 未识别 | 确认主模型为 qwen38-gsq（自定义 GGUF 导入时检查 Modelfile 的 TEMPLATE）；升级 Ollama；或在报障文本里明确"请查知识库" |
| bge-m3 嵌入很慢 | 首次加载模型进显存 | 正常现象，之后有缓存；`ollama ps` 确认在 GPU 上 |

---

