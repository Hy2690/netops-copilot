"""agent.py — NetOps Copilot 主入口。

架构：本地 Ollama 模型 + LangGraph ReAct Agent + 工具层（tools.py）
运行：python agent.py
模型切换：设置环境变量 OLLAMA_MODEL（默认 qwen38-gsq，即 Qwen3.8-27B-GSQ-RCO-IQ3_S）
"""

import os

from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

import mock_network
import tools
from tools import get_topology, run_network_command, apply_remediation, search_knowledge_base

MODEL = os.getenv("OLLAMA_MODEL", "qwen38-gsq")

# 推理后端：ollama（默认）| openai（llama.cpp llama-server / vLLM 等 OpenAI 兼容端点）
BACKEND = os.getenv("LLM_BACKEND", "ollama")
BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8080/v1")

SYSTEM_PROMPT = """你是一名资深数据中心网络运维专家，以 Agent 方式工作，通过工具与网络交互。

【工作纪律】
1. 先用 get_topology 了解网络环境，再开始排查。
2. 使用 run_network_command 执行只读命令收集证据：从报障点出发逐跳交叉验证
   （本端接口 → 对端接口 → 路由协议 → 日志）。
3. 每一步推理必须基于已采集的证据，禁止臆测；证据不足就继续采集。
4. 最终结论必须包含四部分：根因（设备+组件）、关键证据、影响面、修复建议。
5. 修复/变更操作只能通过 apply_remediation 发起，它会要求人工审批。
6. 排查过程中主动用 search_knowledge_base 检索相似历史工单与处理手册（SOP）；
   结论中引用了知识库内容时，必须注明来源文档名称。
"""


def _build_llm():
    """按后端创建模型客户端：ollama 走 ChatOllama；llama.cpp/vLLM 走 OpenAI 兼容 API。"""
    if BACKEND == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=MODEL, temperature=0, base_url=BASE_URL, api_key="none")
    return ChatOllama(model=MODEL, temperature=0)


def build_agent():
    """组装 Agent：本地模型 + 四个工具 + 系统提示词。"""
    return create_react_agent(
        _build_llm(),
        tools=[get_topology, run_network_command, apply_remediation, search_knowledge_base],
        prompt=SYSTEM_PROMPT,
    )


def diagnose(symptom: str, trace: bool = True) -> str:
    """对一条报障现象执行完整诊断，返回最终结论文本。trace=True 时打印工具调用轨迹。"""
    agent = build_agent()
    answer = ""
    for state in agent.stream({"messages": [("user", symptom)]}, stream_mode="values"):
        msg = state["messages"][-1]
        if msg.type == "ai" and msg.tool_calls:
            for tc in msg.tool_calls:
                if trace:
                    print(f"  [调用工具] {tc['name']}({tc['args']})")
        elif msg.type == "tool":
            if trace:
                preview = str(msg.content).replace("\n", " ")[:110]
                print(f"  [工具返回] {preview}...")
        elif msg.type == "ai" and msg.content:
            answer = msg.content if isinstance(msg.content, str) else str(msg.content)
    return answer


def main():
    mode = "mock 仿真" if tools.USE_MOCK else "真实设备"
    print(f"\n===== NetOps Copilot（模型: {MODEL} | 模式: {mode}）=====")
    while True:
        print("\n  1) 故障注入演练   2) 自由报障对话   3) 退出")
        choice = input("选择: ").strip()
        if choice == "1":
            names = list(mock_network.FAULTS)
            for i, n in enumerate(names, 1):
                print(f"    {i}. {mock_network.FAULTS[n]['desc']}")
            idx = input("选择故障场景: ").strip()
            if not idx.isdigit() or not 1 <= int(idx) <= len(names):
                continue
            name = names[int(idx) - 1]
            mock_network.inject_fault(name)
            print(f"\n[已注入故障] 报障现象：{mock_network.FAULTS[name]['symptom']}\n")
            answer = diagnose(mock_network.FAULTS[name]["symptom"])
            print("\n===== 诊断结论 =====\n" + answer)
        elif choice == "2":
            symptom = input("描述你观察到的故障现象: ").strip()
            if symptom:
                print("\n===== 诊断结论 =====\n" + diagnose(symptom))
        elif choice == "3":
            break


if __name__ == "__main__":
    main()
