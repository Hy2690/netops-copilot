# NetOps Copilot —— 基于本地大模型的网络智能运维 Agent

> **v2 已发布（WSL + RAG 知识库版）**：新增运维知识库语义检索（bge-m3 + ChromaDB，
> 覆盖 Runbook/历史工单/拓扑规划/变更规范），完整支持 WSL2 部署。
> 详见《WSL部署与RAG版复现教程.md》，以下为 v1 文档。

一个可以在简历上站得住的个人项目：用**完全本地运行**的开源大模型驱动一个运维 Agent，
它能像值班网工一样接收报障 → 自主登录设备采集证据 → 交叉验证 → 定位根因 →
在**人工审批**后执行修复，全程留痕可审计。

- 不依赖任何云端 API，数据不出本机（一张 RTX 5080 16G 即可运行）
- 内置 Spine-Leaf 仿真网络与故障注入，零硬件也能演示和评估
- 内置自动化评估脚本，用**量化指标**（根因定位准确率、工具调用次数）说话

---

## 1. 架构

```
        报障/告警（自然语言）
                 │
                 ▼
   ┌──────────────────────────┐
   │  LLM 大脑（Ollama 本地模型）│   ReAct 循环：推理 → 调工具 → 读结果 → 再推理
   │  qwen38-gsq / gpt-oss:20b │
   └───────────┬──────────────┘
               │ tool call
               ▼
   ┌──────────────────────────┐
   │   工具层（tools.py）       │   ★ 安全护栏三件套 ★
   │  · get_topology           │   1. 命令白名单（只读/变更分离）
   │  · run_network_command    │   2. 人工审批（变更需 APPROVE）
   │  · apply_remediation      │   3. 审计日志（audit.log）
   └───────────┬──────────────┘
               ▼
   ┌──────────────────────────┐
   │  网络后端                  │
   │  mock 仿真网络（默认）      │ ← mock_network.py：5 台设备 Spine-Leaf，支持故障注入
   │  Netmiko 真实设备（可选）   │ ← 环境变量一键切换
   └──────────────────────────┘
```

## 2. 硬件与模型选择（针对 RTX 5080 16G + 32G 内存）

**Agent 项目对模型有明确要求：工具调用可靠性 > 结构化输出 > 上下文长度 > 推理能力 > 速度。**
16G 显存下的实测推荐：

| 模型 | 量化/体积 | 5080 体验 | 定位 |
|---|---|---|---|
| `qwen38-gsq`（Qwen3.8-27B GSQ-RCO-IQ3_S，**默认**） | 非均匀量化 11.8 GB，全量入显存 | 任务无损、中文强；dense 27B 速度中等 | 主力工作模型 |
| `gpt-oss:20b` | 原生 MXFP4，约 13 GB，全量入显存 | 快（MoE 仅 3.6B 激活），工具调用稳定 | 速度优先备选 |
| `qwen3.5:9b` | Q6 约 7.4 GB | 飞快，但多步推理稳定性一般 | 轻量对照组 |

> GSQ-RCO 版说明：ISTA-DASLab 的非均匀量化（标准 GGUF，Ollama 直接可用），
> 解决了"27B 传统 Q4（约 18GB）塞不进 16G"的死结。下载 GGUF 后用
> `ollama create` 导入即可，详见《WSL部署与RAG版复现教程.md》补充说明。

切换模型只需设置环境变量，无需改代码：

```powershell
# Windows PowerShell
$env:OLLAMA_MODEL="qwen3.5:9b"; python agent.py
```

> 建议：用 `eval.py` 对 2~3 个模型各跑一遍，把"不同模型在运维诊断任务上的
> 准确率/调用次数/时延对比"做成表格——这本身就是简历上最有说服力的部分。

## 3. 快速开始（Windows，10 分钟跑通）

```powershell
# 1. 安装 Ollama：https://ollama.com/download （装完自动后台运行）

# 2. 下载主模型 Qwen3.8-27B-GSQ-RCO-IQ3_S（约 11.8 GB，标准 GGUF）并导入 Ollama
curl.exe -L -o Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf https://hf-mirror.com/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF/resolve/main/Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf
#    新建文本文件 Modelfile，写入两行内容：
#      FROM ./Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf
#      PARAMETER num_ctx 16384
ollama create qwen38-gsq -f Modelfile
ollama run qwen38-gsq "用一句话解释 BGP"   # 测试模型可用

# 3. 创建 Python 环境并安装依赖（需 Python 3.10+）
cd netops-copilot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 4. 运行！
python agent.py
```

选择菜单 `1) 故障注入演练` → 任选一个故障场景，即可看到 Agent 自动排查的完整过程：

```
[调用工具] get_topology({})
[调用工具] run_network_command({'device': 'leaf3', 'command': 'show ip interface brief'})
[调用工具] run_network_command({'device': 'spine1', 'command': 'show ip interface brief'})
[调用工具] run_network_command({'device': 'spine1', 'command': 'show bgp summary'})
...
===== 诊断结论 =====
根因：leaf3 与 spine1 之间链路中断（leaf3 Eth1/1 ↔ spine1 Eth1/3 均 down）...
影响面：leaf3 为单上联，10.1.3.0/24 完全失联...
修复建议：申请执行 interface Eth1/1 no shutdown ...
```

## 4. 三种玩法

| 命令 | 作用 |
|---|---|
| `python agent.py` → 1 | 故障注入演练：4 个预设场景（链路中断 / BGP 会话异常 / CPU 冲高 / 冗余降级） |
| `python agent.py` → 2 | 自由报障：用自然语言描述任意现象，Agent 自主排查 |
| `python eval.py` | 自动化评估：批量注入全部故障，输出根因定位准确率与平均工具调用次数 |

## 5. 工作原理详解

### 5.1 ReAct 循环（Agent 的"思考方式"）

`agent.py` 用 LangGraph 的 `create_react_agent` 实现经典 ReAct 模式：

1. **Thought**：LLM 根据报障现象和已有证据推理下一步该查什么
2. **Action**：输出结构化工具调用（如 `run_network_command("leaf3", "show ip interface brief")`）
3. **Observation**：工具执行并把设备输出喂回 LLM
4. 循环往复，直到 LLM 认为证据充分，输出最终结论

LLM 只负责"决策与解读"，**命令的实际执行全部在确定性的 Python 代码里**——
这是防止模型幻觉直接危害网络的关键设计。

### 5.2 安全护栏三件套（生产级 Agent 的门槛）

| 护栏 | 实现位置 | 作用 |
|---|---|---|
| 命令白名单 | `run_network_command` 拒绝一切非 `show/display` 命令 | Agent 物理上无法误配设备 |
| 人工审批 | `apply_remediation` 中必须输入 `APPROVE` | 变更权永远在人手里 |
| 审计日志 | 所有工具调用写入 `audit.log`（JSON Lines） | 事后可追溯每一步操作 |

### 5.3 评估方法论

`eval.py` 的做法借鉴了 AIOps 工程实践：把 4 类典型故障（物理层 / 协议层 /
控制平面 / 冗余降级）做成可重复注入的"考题"，用关键词分组命中给 Agent 的
最终结论打分。**改提示词、换模型之后跑一遍 eval，用数据判断是变好还是变坏**，
而不是凭感觉。

## 6. 接真实设备

```powershell
$env:NETOPS_MOCK="0"
$env:NETOPS_HOST="192.168.1.1"
$env:NETOPS_USERNAME="readonly"
$env:NETOPS_PASSWORD="******"
$env:NETOPS_DEVICE_TYPE="huawei"   # 或 cisco_nxos / arista_eos 等
python agent.py
```

没有真机的话，推荐用 Containerlab + FRR/CE 镜像在 Docker 里起一个虚拟 Fabric
（需要 WSL2），Netmiko 直接 SSH 上去即可，体验与真机一致。

## 7. v2 进阶路线

1. **MCP 化**：把三个工具封装成 MCP Server，让任意 Agent 客户端都能接入（当前行业标准做法）
2. **RAG 知识库**：接入历史工单、网络拓扑文档，让 Agent 排查时能引用"上周这条链路刚割接过"这类上下文
3. **Streamlit Web 界面**：把 CLI 升级成浏览器对话式运维台
4. **接真实告警源**：Prometheus / Zabbix Webhook 触发 Agent 自动开工
5. **多 Agent 协作**：诊断 Agent + 变更 Agent + 审核 Agent 分工（参考 CrewAI/LangGraph supervisor）


