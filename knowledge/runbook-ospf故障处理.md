# Runbook：OSPF 邻居故障处理手册（RB-OSPF-001）
> 适用场景：OSPF 邻居状态异常（Down/Init/ExStart/Loading）、路由缺失、邻居频繁抖动（flapping）、区域认证失败、LSA 泛滥
> 最近验证日期：2026-09-28 | 负责人：网络组
> 适配拓扑：本数据中心 Spine-Leaf 架构 Underlay 可启用 OSPF 作为 IGP，互联接口、Loopback 接口均纳入 OSPF 进程

## 一、核心原则：先链路，后协议；先本端，后对端
OSPF 运行在 IP 层之上，排查优先级：物理层/链路层状态 → 直连 IP 互通性 → OSPF 接口配置 → 邻居状态机 → 数据库同步 → 路由计算。
**链路 down 导致的 OSPF 邻居 Down 是连带结果，不属于协议故障；只有链路 up 但邻居无法建立，才是 OSPF 协议层问题。**

## 二、定位步骤（按顺序执行）
1. `show ip interface brief` 确认互联接口物理/协议状态
   - 接口 down → 先按《链路故障处理手册》排查物理层
   - 接口 up → 进入协议层排查

2. `show ip ospf neighbor` 确认邻居当前状态
   - Full：正常邻接关系
   - Down：未收到任何 Hello 包，常见于链路中断、对端未启用 OSPF
   - Init：本端收到对端 Hello，但对端没收到本端 Hello，常见于单向不通、ACL 拦截
   - ExStart/Exchange：数据库同步阶段卡住，常见于 MTU 不匹配、RID 冲突
   - Loading：LSA 加载失败，常见于链路拥塞、报文丢失

3. `show ip ospf interface <接口名>` 核对接口参数
   - 确认接口已加入对应 OSPF 区域
   - 核对 Hello/Dead 定时器、认证类型、区域类型（普通区域/Stub/NSSA）
   - 确认接口网络类型（点到点/广播型，Spine-Leaf 互联推荐点到点）

4. `show logging` 查看 OSPF 日志
   - `%OSPF-5-ADJCHG`：邻居状态变更记录，可定位抖动时间点
   - `%OSPF-4-BADLSATYPE` / `%OSPF-4-CONFLICT`：LSA 异常、RID 冲突
   - `%OSPF-3-NOAUTH`：认证失败

5. `show ip ospf database` 检查链路状态数据库
   - 确认对应网段 LSA 是否正常生成
   - 排查 RID 重复、LSA 老化异常

## 三、常见根因
1. **接口未加入 OSPF 进程 / 区域号不匹配**：两端区域号不一致，邻居无法建立
2. **认证不匹配**：明文/MD5 认证密码不一致、认证类型不统一
3. **MTU 不匹配**：接口 MTU 差异导致 ExStart 阶段卡住，无法进入 Full
4. **Hello/Dead 定时器不一致**：两端参数不匹配导致邻居超时重置
5. **Router ID 冲突**：两台设备 RID 相同，导致 LSA 振荡、邻居不稳定
6. **ACL 拦截**：接口入方向 ACL 拒绝了 OSPF 组播报文（224.0.0.5/224.0.0.6）
7. **网络类型不匹配**：一端广播型、一端点到点，导致 DR 选举异常、邻居无法建立

## 四、恢复与验证
1. **配置修正**：核对并同步两端区域、认证、定时器、MTU、网络类型配置（需走变更审批）
2. **邻居重置**：`clear ip ospf process` 重置 OSPF 进程（注意：会引发路由重新收敛，需在变更窗口执行）
3. **恢复后验证标准**：
   - 邻居状态稳定为 Full，持续 5 分钟无抖动
   - `show ip route ospf` 对应路由条目正常出现
   - 业务网段可达性、时延无异常
4. 若为本季度第二次同类故障，必须在周会提出根因整改，并更新配置基线。

## 五、升级路径
- 单条邻居中断但有冗余路径 → P3 级，值班工程师处理
- 核心 Spine 间 OSPF 中断导致路由黑洞 → P2 级，升级至网络组组长
- 整区域 OSPF 振荡影响业务超过 10 分钟 → P1 级，启动变更冻结并同步通报
