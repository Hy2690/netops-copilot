"""tools.py — Agent 工具层。

本项目的核心设计之一：LLM 不直接碰设备，一切操作经由工具函数，
在工具层实现生产级三件套安全护栏：
  1) 命令白名单 —— 只读命令与变更命令分离，Agent 无法越权
  2) 人工审批   —— 变更类命令必须人工输入 APPROVE 才执行
  3) 审计留痕   —— 所有调用以 JSON Lines 写入 audit.log
"""

import json
import os
import time

from langchain_core.tools import tool

import mock_network

# NETOPS_MOCK=1（默认）→ 仿真网络；设为 0 并配置 NETOPS_HOST 等变量 → 真实设备
USE_MOCK = os.getenv("NETOPS_MOCK", "1") == "1"
AUDIT_FILE = os.getenv("NETOPS_AUDIT", "audit.log")

READONLY_PREFIXES = ("show", "display")          # 只读命令白名单前缀
REMEDIATION_KEYWORDS = ("no shutdown", "clear ip bgp")  # 变更命令白名单关键词


def _audit(action, device, command, result_summary):
    """审计日志：一行一条 JSON，记录谁在何时对哪台设备做了什么。"""
    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "device": device,
        "command": command,
        "result": str(result_summary)[:200],
    }
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@tool
def get_topology() -> str:
    """查看当前网络的拓扑结构、设备清单与网段规划。开始排查前应先调用本工具。"""
    _audit("read", "-", "get_topology", "ok")
    return mock_network.TOPOLOGY


@tool
def search_knowledge_base(query: str) -> str:
    """检索运维知识库：历史故障工单、故障处理手册（Runbook/SOP）、拓扑规划与变更规范文档。

    使用时机：
    - 排查开始时：检索是否存在相似历史故障及其根因
    - 给出修复建议前：检索对应的处理手册，确保操作符合 SOP

    Args:
        query: 自然语言检索词，如 "BGP 邻居中断 处理流程"、"leaf3 历史故障"
    """
    try:
        import rag
        result = rag.search(query)
    except FileNotFoundError as e:
        result = f"知识库不可用：{e}"
    except Exception as e:  # noqa: BLE001
        result = f"知识库检索失败：{e}（可继续基于设备证据排查）"
    _audit("read", "-", f"kb:{query}", result)
    return result


@tool
def run_network_command(device: str, command: str) -> str:
    """在指定网络设备上执行【只读】命令（show / display 系列），用于采集状态证据。

    变更类命令一律被本工具拒绝，只能走 apply_remediation（需人工审批）。

    Args:
        device: 设备名，如 spine1 / leaf1
        command: 只读命令，如 "show ip interface brief"
    """
    cmd = command.strip().lower()
    if not cmd.startswith(READONLY_PREFIXES):
        return ("拒绝执行：检测到非只读命令。变更操作请改用 apply_remediation 工具"
                "（该工具会要求人工审批）。")
    if USE_MOCK:
        result = mock_network.run_command(device, command)
    else:
        result = _run_on_real_device(device, command)
    _audit("readonly", device, command, result)
    return result


@tool
def apply_remediation(device: str, command: str, reason: str) -> str:
    """对设备执行【变更/修复】命令。内置护栏：命令白名单 + 人工审批 + 审计留痕。

    Args:
        device: 设备名
        command: 修复命令，目前白名单仅支持 "interface <接口> no shutdown" 与 "clear ip bgp *"
        reason: 执行该变更的理由（会展示给审批人并记入审计日志）
    """
    cmd = command.strip().lower()
    if not any(k in cmd for k in REMEDIATION_KEYWORDS):
        return f"拒绝：命令不在修复白名单 {REMEDIATION_KEYWORDS} 内，已拦截并记录。"

    print("\n" + "=" * 60)
    print("【人工审批】Agent 请求执行变更：")
    print(f"  设备：{device}")
    print(f"  命令：{command}")
    print(f"  理由：{reason}")
    choice = input("  输入 APPROVE 批准执行，其他任意键拒绝：").strip()
    _audit("remediate-request", device, command,
           f"approved={choice == 'APPROVE'} reason={reason}")
    if choice != "APPROVE":
        return "变更已被人工拒绝。请向用户说明情况并给出替代建议。"

    result = (mock_network.apply_config(device, command) if USE_MOCK
              else _config_on_real_device(device, command))
    _audit("remediate-result", device, command, result)
    return result


# ---------------------------------------------------------------- 真实设备后端（可选）

def _real_conn():
    """用环境变量构造 Netmiko 连接（真实模式）。多设备可扩展为读取 inventory 文件。"""
    from netmiko import ConnectHandler

    host = os.getenv("NETOPS_HOST")
    if not host:
        raise RuntimeError(
            "真实模式需设置环境变量：NETOPS_HOST / NETOPS_USERNAME / "
            "NETOPS_PASSWORD / NETOPS_DEVICE_TYPE（如 cisco_nxos、huawei）")
    return ConnectHandler(
        device_type=os.getenv("NETOPS_DEVICE_TYPE", "cisco_nxos"),
        host=host,
        username=os.getenv("NETOPS_USERNAME", ""),
        password=os.getenv("NETOPS_PASSWORD", ""),
    )


def _run_on_real_device(device, command):
    try:
        with _real_conn() as conn:
            return conn.send_command(command)
    except Exception as e:  # noqa: BLE001
        return f"% 真实设备执行失败: {e}"


def _config_on_real_device(device, command):
    try:
        with _real_conn() as conn:
            return conn.send_config_set([command])
    except Exception as e:  # noqa: BLE001
        return f"% 真实设备配置失败: {e}"
