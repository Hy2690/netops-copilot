# Runbook：BGP 邻居故障处理手册（RB-BGP-001）

> 适用场景：BGP 邻居状态异常（Idle/Active）、路由丢失、BGP 会话频繁抖动
> 最近验证日期：2026-09-05 | 负责人：网络组

## 一、核心原则：先链路，后协议
BGP 是建立在 TCP（179 端口）之上的协议，排查顺序永远是：物理层/链路层 → IP 可达性 → TCP 179 → BGP 配置与状态。**链路 up 但 BGP Idle/Active，才是真正的 BGP 协议层问题；链路 down 时的 BGP down 只是连带结果。**

## 二、定位步骤
1. `show ip interface brief` 确认互联链路状态（先排除物理层）。
2. `show bgp summary` 确认邻居状态：
   - Established：正常
   - Idle：会话未建立，常见于对端关闭会话、hold timer 超时、配置变更
   - Active：正在尝试建立，常见于 TCP 不通（ACL 拦截或中间链路问题）
3. `show logging` 查 BGP-5-ADJCHANGE / BGP-3-NOTIFICATION：
   - "hold time expired" → 对端无响应（对端 CPU 高、链路单向故障、会话被重置）
   - "notification received 4/0" → 对端主动报告保持时间超时

## 三、常见根因
- 割接/配置变更导致会话参数不匹配（AS 号、认证密码、timer）
- 对端控制平面异常（CPU 高导致 keepalive 发送不及时）
- 互联链路单向故障（收光正常、发光异常）

## 四、恢复与验证
- 会话重置：`clear ip bgp *`（需走变更审批，注意会引发路由重新收敛）。
- 恢复后验证：邻居 Established、路由条目恢复、业务时延回落。
- 若为本季度第二次同类故障，必须在周会提出根因整改（参考历史工单 INC-2026-0918）。

## 五、升级路径
- 影响生产路由超过 15 分钟 → 升级至网络组组长并启动变更冻结。
