"""mock_network.py — 模拟一个小型 Spine-Leaf 数据中心网络。

无需真实设备即可运行本项目的 Agent：
- 提供 Cisco 风格的只读命令输出（show 系列）
- 支持故障注入，用于诊断演练与自动化评估（eval.py）
- 支持少量修复类命令（供"人工审批后执行"演示）

拓扑:
            spine1              spine2
           /  |  \             /    \
       leaf1  leaf2  leaf3(单上联,仅接 spine1)
         |      |      |
      10.1.1  10.1.2  10.1.3   (.0/24 服务器网段)
"""

import copy
import re

TOPOLOGY = """数据中心 Spine-Leaf 拓扑（共 5 台设备）：

  spine1 (Lo0: 1.1.1.1) —— Eth1/1..3 分别下联 leaf1 / leaf2 / leaf3
  spine2 (Lo0: 2.2.2.2) —— Eth1/1..2 分别下联 leaf1 / leaf2
  leaf1 —— Eth1/1→spine1, Eth1/2→spine2, Eth1/48→服务器网段 10.1.1.0/24
  leaf2 —— Eth1/1→spine1, Eth1/2→spine2, Eth1/48→服务器网段 10.1.2.0/24
  leaf3 —— Eth1/1→spine1（单上联，无冗余）, Eth1/48→服务器网段 10.1.3.0/24

  互联链路均运行 eBGP；服务器网关位于各 leaf 的 Eth1/48。
"""


def _initial_state():
    """出厂状态：所有链路 up、BGP Established、CPU 正常。"""
    return {
        "spine1": {
            "interfaces": {
                "Eth1/1": {"status": "up", "ip": "10.0.11.0/31", "peer": "leaf1", "peer_intf": "Eth1/1"},
                "Eth1/2": {"status": "up", "ip": "10.0.12.0/31", "peer": "leaf2", "peer_intf": "Eth1/1"},
                "Eth1/3": {"status": "up", "ip": "10.0.13.0/31", "peer": "leaf3", "peer_intf": "Eth1/1"},
            },
            "bgp": {
                "leaf1": ("10.0.11.1", "Established"),
                "leaf2": ("10.0.12.1", "Established"),
                "leaf3": ("10.0.13.1", "Established"),
            },
            "cpu": 11,
            "logs": [],
        },
        "spine2": {
            "interfaces": {
                "Eth1/1": {"status": "up", "ip": "10.0.21.0/31", "peer": "leaf1", "peer_intf": "Eth1/2"},
                "Eth1/2": {"status": "up", "ip": "10.0.22.0/31", "peer": "leaf2", "peer_intf": "Eth1/2"},
            },
            "bgp": {
                "leaf1": ("10.0.21.1", "Established"),
                "leaf2": ("10.0.22.1", "Established"),
            },
            "cpu": 9,
            "logs": [],
        },
        "leaf1": {
            "interfaces": {
                "Eth1/1": {"status": "up", "ip": "10.0.11.1/31", "peer": "spine1", "peer_intf": "Eth1/1"},
                "Eth1/2": {"status": "up", "ip": "10.0.21.1/31", "peer": "spine2", "peer_intf": "Eth1/1"},
                "Eth1/48": {"status": "up", "ip": "10.1.1.1/24", "peer": "server", "peer_intf": None},
            },
            "bgp": {
                "spine1": ("10.0.11.0", "Established"),
                "spine2": ("10.0.21.0", "Established"),
            },
            "cpu": 15,
            "logs": [],
        },
        "leaf2": {
            "interfaces": {
                "Eth1/1": {"status": "up", "ip": "10.0.12.1/31", "peer": "spine1", "peer_intf": "Eth1/2"},
                "Eth1/2": {"status": "up", "ip": "10.0.22.1/31", "peer": "spine2", "peer_intf": "Eth1/2"},
                "Eth1/48": {"status": "up", "ip": "10.1.2.1/24", "peer": "server", "peer_intf": None},
            },
            "bgp": {
                "spine1": ("10.0.12.0", "Established"),
                "spine2": ("10.0.22.0", "Established"),
            },
            "cpu": 14,
            "logs": [],
        },
        "leaf3": {
            "interfaces": {
                "Eth1/1": {"status": "up", "ip": "10.0.13.1/31", "peer": "spine1", "peer_intf": "Eth1/3"},
                "Eth1/48": {"status": "up", "ip": "10.1.3.1/24", "peer": "server", "peer_intf": None},
            },
            "bgp": {
                "spine1": ("10.0.13.0", "Established"),
            },
            "cpu": 8,
            "logs": [],
        },
    }


_INITIAL = _initial_state()
CURRENT = copy.deepcopy(_INITIAL)


def reset():
    """恢复出厂状态（评估每个场景前调用）。"""
    global CURRENT
    CURRENT = copy.deepcopy(_INITIAL)


def device_names():
    return list(CURRENT.keys())


# ---------------------------------------------------------------- 命令渲染

def _show_version(device):
    return (f"{device} - Nexus9000 C93180YC-EX (mock)\n"
            f"  BIOS:  version 07.69\n"
            f"  NXOS:  version 9.3(12) (mock)\n"
            f"  uptime: 42 day(s), 7 hour(s), 13 minute(s)")


def _show_intf_brief(device):
    lines = ["Interface        IP-Address          Status      Peer"]
    for name, i in CURRENT[device]["interfaces"].items():
        lines.append(f"{name:<15}  {i['ip']:<18}  {i['status']:<11} to {i['peer']}")
    return "\n".join(lines)


def _show_bgp_summary(device):
    lines = ["Neighbor        Peer          State"]
    for peer, (ip, state) in CURRENT[device]["bgp"].items():
        lines.append(f"{ip:<15} {peer:<13} {state}")
    return "\n".join(lines)


def _show_cpu(device):
    c = CURRENT[device]["cpu"]
    return (f"CPU utilization for five seconds: {c}%; "
            f"one minute: {c}%; five minutes: {c}%")


def _show_logging(device):
    logs = CURRENT[device]["logs"]
    return "\n".join(logs) if logs else "No log messages buffered."


def run_command(device, command):
    """执行只读命令并返回仿真输出。不支持的命令返回设备风格报错。"""
    if device not in CURRENT:
        return f"% 设备不存在: {device}（可选: {', '.join(device_names())}）"
    cmd = " ".join(command.lower().split())
    if cmd.startswith("show version"):
        return _show_version(device)
    if cmd.startswith(("show ip interface brief", "show interface brief")):
        return _show_intf_brief(device)
    if cmd.startswith("show bgp summary"):
        return _show_bgp_summary(device)
    if cmd.startswith(("show processes cpu", "show cpu")):
        return _show_cpu(device)
    if cmd.startswith(("show logging", "show log")):
        return _show_logging(device)
    return (f"% Invalid command or unsupported by mock: {command}\n"
            f"  支持: show version / show ip interface brief / show bgp summary / "
            f"show processes cpu / show logging")


# ---------------------------------------------------------------- 内部状态修改

def _log(device, msg):
    CURRENT[device]["logs"].append(f"%{msg}")


def _set_link(device, intf, up):
    CURRENT[device]["interfaces"][intf]["status"] = "up" if up else "down"
    _log(device, f"LINK-3-UPDOWN: Interface {intf}, changed state to {'up' if up else 'down'}")


def _set_bgp(device, peer, established):
    ip, _ = CURRENT[device]["bgp"][peer]
    CURRENT[device]["bgp"][peer] = (ip, "Established" if established else "Idle")
    direction = "Up" if established else "Down (hold time expired)"
    _log(device, f"BGP-5-ADJCHANGE: neighbor {ip} {direction}")


def _restore_bgp_pair(a, b):
    if b in CURRENT[a]["bgp"]:
        _set_bgp(a, b, True)
    if a in CURRENT[b]["bgp"]:
        _set_bgp(b, a, True)


# ---------------------------------------------------------------- 故障注入

FAULTS = {
    "leaf3-uplink-down": {
        "desc": "leaf3 单上联链路中断（无冗余 → 网段全断）",
        "symptom": "监控告警：服务器网段 10.1.3.0/24 完全不可达，leaf3 管理面失联。请定位根因并给出修复建议。",
        "expected": [["leaf3"],
                     ["eth1/1", "eth1/3", "链路", "接口", "link"],
                     ["down", "中断", "故障", "断开"]],
    },
    "bgp-spine1-leaf2-down": {
        "desc": "spine1 与 leaf2 间 BGP 会话异常（物理链路正常）",
        "symptom": "监控告警：leaf2 与 spine1 之间 BGP 邻居中断，流量绕行 spine2 导致部分业务时延升高。请定位根因。",
        "expected": [["bgp"],
                     ["spine1", "leaf2"],
                     ["hold", "会话", "邻居", "session"]],
    },
    "high-cpu-leaf2": {
        "desc": "leaf2 CPU 异常冲高（控制平面故障）",
        "symptom": "值班同事反馈 leaf2 命令行响应极慢，监控显示其 CPU 持续高于 95%。请分析原因并给出处置建议。",
        "expected": [["cpu"],
                     ["leaf2"],
                     ["snmp", "控制面", "控制", "洪泛", "进程"]],
    },
    "leaf1-single-uplink-down": {
        "desc": "leaf1 冗余上联之一中断（有告警但业务无感）",
        "symptom": "收到 leaf1 上联接口 down 告警，但业务监控显示 10.1.1.0/24 访问正常。请定位故障点并评估影响与处置优先级。",
        "expected": [["leaf1"],
                     ["eth1/1", "eth1/2", "spine1"],
                     ["冗余", "单点", "无影响", "降级", "影响"]],
    },
}


def inject_fault(name):
    """注入预设故障（先恢复出厂状态再注入）。Agent 只能通过命令输出发现问题。"""
    reset()
    if name == "leaf3-uplink-down":
        _set_link("leaf3", "Eth1/1", False)
        _set_link("spine1", "Eth1/3", False)
        _set_bgp("leaf3", "spine1", False)
        _set_bgp("spine1", "leaf3", False)
    elif name == "bgp-spine1-leaf2-down":
        _set_bgp("spine1", "leaf2", False)
        _set_bgp("leaf2", "spine1", False)
        _log("spine1", "BGP-3-NOTIFICATION: received from neighbor 10.0.12.1 4/0 (hold time expired)")
    elif name == "high-cpu-leaf2":
        CURRENT["leaf2"]["cpu"] = 97
        _log("leaf2", "SYS-1-CPUHOG: process snmpd busy for 326 seconds")
        _log("leaf2", "SNMP-3-RESPONSE_DELAYED: response delayed by 4120 ms")
    elif name == "leaf1-single-uplink-down":
        _set_link("leaf1", "Eth1/1", False)
        _set_link("spine1", "Eth1/1", False)
        _set_bgp("leaf1", "spine1", False)
        _set_bgp("spine1", "leaf1", False)
    else:
        raise ValueError(f"未知故障: {name}（可选: {', '.join(FAULTS)}）")


# ---------------------------------------------------------------- 修复类命令（供审批后执行）

def _find_intf(device, query):
    q = query.lower().replace("ethernet", "eth")
    for name in CURRENT[device]["interfaces"]:
        if name.lower() == q:
            return name
    return None


def apply_config(device, command):
    """执行修复命令。仅支持白名单内的安全操作：接口 no shutdown / clear ip bgp。"""
    if device not in CURRENT:
        return f"% 设备不存在: {device}（可选: {', '.join(device_names())}）"
    cmd = " ".join(command.lower().split())

    m = re.search(r"interface\s+(\S+)\s+no shutdown", cmd)
    if m:
        intf = _find_intf(device, m.group(1))
        if not intf:
            return f"% 接口不存在: {m.group(1)}"
        _set_link(device, intf, True)
        info = CURRENT[device]["interfaces"][intf]
        peer, peer_intf = info.get("peer"), info.get("peer_intf")
        if peer in CURRENT and peer_intf:
            _set_link(peer, peer_intf, True)
            _restore_bgp_pair(device, peer)
        return (f"{device}(config-if)# no shutdown\n"
                f"% 接口 {intf} 已恢复 up，互联对端联动恢复，BGP 邻居已重建。")

    if "clear ip bgp" in cmd:
        for peer in list(CURRENT[device]["bgp"]):
            _restore_bgp_pair(device, peer)
        return f"{device}# clear ip bgp *\n% 所有 BGP 会话已重置并完成重建。"

    return f"% mock 暂不支持该配置命令: {command}"
