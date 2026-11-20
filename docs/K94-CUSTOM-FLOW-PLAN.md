# 自研 K94 跨屏输入方案：架构设计与实施 Runbook

> 状态：待接手模型实施。本文只规划，不代表任何新固件已经刷入，也不代表现有键鼠服务已经修改。
> 更新日期：2026-11-18
> 当前用户目标：完全脱离 Logitech Options+ / Flow，并摆脱 Deskflow 当前的不稳定体验，实现 Mac mini 与 3090 Windows 之间的鼠标、K94 键盘、焦点与剪贴板协同。

## 0. 接手模型先做什么

1. 阅读 `/Users/lazy/AGENTS.md` 与本目录 `AGENTS.md`，遵守其中关于协商、配置备份、日志和危险操作的规则。
2. 阅读本文全文和 `2026-11-mini-setup-log.md` 第十三节，不要重新翻历史聊天来推断现状。
3. 先执行只读侦察，不刷固件、不拆机、不改 Windows 网络、不停现有 Deskflow。
4. 建立一个独立的实施状态文件 `docs/custom-flow-status.md`（若目录不存在可创建），每个阶段记录：实际执行的命令、产物、证据、未决问题、回退点。
5. 本文的 `已验证`、`源码事实`、`推断`、`未知` 不得混用。任何“鼠标可软件切通道”“K94 可以收到主机命令”的说法，未经实测都只能标为未知。

## 1. 最终目标与验收条件

### 1.1 目标体验

- 两台物理显示器保持：Windows 在左，Mac mini 在右。
- 用户在 Mac 上将鼠标移到左边缘，进入 Windows；在 Windows 上移到右边缘，回到 Mac。
- KEMOVE K94 的输入焦点随活动电脑切换。
- 鼠标的输入焦点随活动电脑切换。
- 文本、图片、文件剪贴板可在两台电脑之间同步。
- 鼠标或键盘通道切换时，不能让 Mac 上的本地残留光标继续移动，也不能让输入焦点停错电脑。
- 提供明确的热键、GUI 状态和恢复操作。发生异常时可以回到 Mac，且能看日志。

### 1.2 非目标

- 不实现显示器视频传输，不是硬件 KVM。
- 不改变 Windows 的 Public 网络配置，不改变 WOL、SSH、RDP。
- 不在未经用户确认时购买新鼠标、转发器、开发板或其他硬件。
- 不以逆向 Logitech 私有软件或恢复 Logitech 私有协议为目标。
- 不把 Deskflow 改名后继续沿用其 macOS 1.27.0 跨屏状态管理，并把它称为新系统。

### 1.3 完成的最低验收标准

全部实测通过才算完成，不能只凭编译成功或网络连接成功：

1. 连续双向切换至少 50 次，鼠标、K94 和实际输入焦点一致。
2. Mac 本地点击/输入在离开 Mac 后不再被错误响应。
3. Windows UAC 弹框可点击；Windows 登录界面单独验证，不据此自动宣称通过。
4. 中文/英文输入、常见修饰键、按住 Shift/Ctrl、拖拽、滚轮、复制粘贴正常。
5. Mac 换 Wi-Fi 再换回、Windows 睡眠再唤醒后，能自动恢复或给出明确的可恢复提示。
6. Windows 未开机/不可达时不会自动把输入设备切走并卡死。
7. 所有日志可见，存在一键停用自研方案和恢复现有配置的路径。

## 2. 当前硬件与软件状态

| 项目 | 当前事实 |
| --- | --- |
| Mac mini | `lazydeMac-Mini.local`，常用内网 `192.168.1.4`，Tailscale `100.113.186.86` |
| Windows | hostname `lazy-windows`，常用内网 `192.168.1.8` |
| 新键盘 | KEMOVE K94，Mac 当前蓝牙名为 `KEMOVE K94-1`，支持 BT1/2/3、2.4G、USB-C |
| 罗技键盘 | K380，Flow 自动跟随曾经实测成功 |
| 鼠标 | Logitech M585/M590，蓝牙 PID `0xB01B`，VID `0x046D`，Mac 连接名 `M585/M590` |
| Logi Options+ | 两台机器均已安装；Flow 为避免与 Deskflow 抢边界而停用，软件未卸载 |
| Deskflow | 1.27.0，Mac 为 server，Windows 为 client，剪贴板开启，TLS 关闭 |
| Mac Deskflow | LaunchAgent `org.deskflow.deskflow.server`；配置 `~/Library/Deskflow/Deskflow.conf`；拓扑 `~/Library/Deskflow/server-links.conf` |
| Windows Deskflow | 托盘 GUI `C:\Program Files\Deskflow\Deskflow.exe`；登录计划任务 `Deskflow Client` |
| Windows 输入权限 | `processMode=0`，core 由 Deskflow daemon 提升运行，UAC 已由用户实测可点击 |
| 文件传输 | LocalSend 保留；它是独立备用路径，不应让本项目的输入切换依赖它 |

### 2.1 当前 Deskflow 的网络与已知问题

- Mac 端配置曾固定 `interface=192.168.1.4`。Mac 临时换到另一 Wi-Fi 后失去该地址，恢复时 Deskflow 报 `cannot bind address`，导致 Windows 无法连接。后来已删除该固定绑定，改为监听所有接口。
- Mac 1.27.0 服务端出现活动屏停在 Windows、Mac 仍有残留光标的异常；重启 Mac Deskflow 后恢复。
- 上游 issue #10225 与 #10231 与 macOS 双光标问题有关；不要在未验证升级的情况下假设这些问题已经修复。
- 当前热键是 `Ctrl+Alt+Shift+←/→`，但它无法解决所有卡屏。

## 3. 架构原则：分开两类控制问题

### A. 软件输入转发

Mac 或 Windows 采集输入，通过网络把事件发到另一台电脑，由客户端注入。这是 Deskflow 等软件 KVM 的模式。

### B. 物理设备通道切换

K94 或鼠标直接通过蓝牙/2.4G 连接某台电脑，切换时必须让设备本身换通道、换配对目标或换输出端。这是 Flow 类体验中的硬件控制部分。

**不能混为一谈。** 当 K94 蓝牙直连 Mac 时，切换 K94 到 Windows 需要键盘真的切换 BT 通道。当鼠标蓝牙直连 Mac 时，鼠标要控制 Windows 也需要鼠标换通道，或者改用 USB HID 转发硬件。纯网络软件不能让一条蓝牙链路凭空变成两台电脑的输入。

## 4. 首选架构

先验证纯软件可控通道，暂不考虑新增硬件：

```text
Mac 输入事件 + 鼠标位置 + K94 状态 + Windows 在线状态
                         |
                  本机控制状态机
                         |
          唯一 activeTarget: mac / windows
                         |
       +-----------------+------------------+
       |                                    |
  K94 通道控制器                       鼠标通道控制器
       |                                    |
   BT1: Mac                              通道切换/输入转发
   BT2: Windows                               |
       |                              Windows 输入注入
       +-----------------+------------------+
                         |
                日志、GUI、热键、回退
                         |
                 剪贴板同步（独立子系统）
```

设计约束：

- `activeTarget` 是唯一事实来源。边缘检测、热键、自动重连、通道命令都必须经过同一个状态机，避免两套边界逻辑互相打架。
- 通道控制器与边缘检测解耦。没有证明鼠标可控时，不能把 K94 实验阻塞在鼠标上。
- 若使用“设备换通道”而非“软件转发”，不要用 Mac 本机虚拟显示器/隐藏窗口制造假的跨屏状态，先证明设备切换本身可靠。
- 剪贴板同步独立实现和测试，不能因为输入焦点失败而把大文件复制操作无限重试。

## 5. K94 已掌握的源码事实

官方源码：

- https://github.com/KEMOVE-Official/KEMOVE-QMK-Firmware
- 2026-11-18 读取的 `main` tree SHA：`c04f415f5934d6e48a76e7100a2c541116941b90`
- 官方 K94 入口页：https://www.kemove.com/pages/k94-hub
- VIA JSON：https://download.kemove.com/k94/via/kemove-k94.json?v=20260920

以下均为源码中直接可见的事实：

1. 键盘目录是 `keyboards/8r101_k94`。
2. `info.json` 标记主控为 `FS026`，USB VID `0x36B0`，PID `0x314B`。
3. `rules.mk` 中有 `BOARD = FS026` 和 `BLUETOOTH_CUSTOM = yes`。
4. 键位表包含 `MD_BLE1`、`MD_BLE2`、`MD_BLE3`、`MD_24G`。
5. `8r101_k94.c` 的 `process_record_user` 调用 `Uart_Key_Mode_Key_Scan(keycode, pressed)`。
6. `rdr_common.h` 包含 `raw_hid.h`，并定义以下无线切换命令常量：

```text
USER_SWITCH_2P4G_MODE = 0x00
USER_SWITCH_BLE_1_MODE = 0x01
USER_SWITCH_BLE_2_MODE = 0x02
USER_SWITCH_BLE_3_MODE = 0x03
USER_SWITCH_2P4G_PAIR = 0x04
USER_SWITCH_BLE_1_PAIR = 0x05
USER_SWITCH_BLE_2_PAIR = 0x06
USER_SWITCH_BLE_3_PAIR = 0x07
USER_SWITCH_USB_MODE = 0x08
```

7. `rdr_common.h` 还定义了 `MODE_2P4G_IO (B12)`、`MODE_BLE_IO (B13)`、`MAC_WIN_IO (B14)`。
8. 键盘库是 `lib/rdr_lib/librdrcommon.a`，无线具体实现主要落在预编译库内，不在键位表本身。
9. 官方 VIA 固件文件 `8r101_k94_via.bin` 已下载到当前工作目录 `tmp/8r101_k94_via.bin`，大小 81,484 bytes，SHA-256：`ffd34212071191f7083f82682b090a0c26d9b68ca4934b613472707979cb1292`。此文件只作为研究输入，尚未刷入。

### 5.1 由这些事实可以提出的推断，不等于已验证

- 可能存在从主机经 raw HID 控制通道的接口，需要读二进制/源码或抓包确认。
- 无线切换可能由独立 RF 模块参与，需要确认主控和模块间协议、确认回执与状态。
- `USER_SWITCH_*` 常量本身不能证明这些值可以直接作为 USB raw HID payload 发出。

## 6. 阶段 A：只读侦察和恢复准备

### 目标

在不改变当前可用系统的情况下，确定控制接口、固件工具链和回退材料。

### 执行步骤

1. 在独立研究目录中 clone 官方源码，记录 commit、子模块状态、工具链版本。
2. 复制而不是覆盖已有临时分析材料；对固件和配置做 SHA-256 清单。
3. 阅读 `keyboards/8r101_k94` 全部源码、`lib/rdr_lib/rdr_common.h`、QMK raw HID/VIA 实现。
4. 检查 `librdrcommon.a` 的架构、对象文件、符号、字符串和调用关系。
5. 读取官方 VIA JSON，确认自定义键码、VIA 自定义命令、raw HID usage page/usage 是否公开。
6. 查官方固件恢复/刷写说明，确认 FS026 的 bootloader、刷写工具和现有固件备份的可获得性。
7. 先尝试**不修改行为地编译**官方 K94 固件。记录是否缺少库、编译器、子模块或厂商私有文件。
8. 检查现有 Mac HID 枚举信息，确认 USB 有线模式下的 VID/PID、raw HID 接口和报告描述符。

### 阶段门槛

- 若能找到现成的 raw HID 切通道命令，进入阶段 B，不写自定义固件。
- 若只有键位处理入口而没有主机接口，进入阶段 C，评估最小固件补丁。
- 若没有可用恢复固件/刷写方法，不执行刷写；先做桌面模拟和只读分析，并向用户说明缺口。

## 7. 阶段 B：证明 K94 可由主机控制

### 优先级

1. 现成 raw HID 接口。
2. 官方 Web Hub 的 USB/WebHID 命令。
3. VIA 自定义命令。
4. 最后才是自定义固件补丁。

### 实验

1. K94 用 USB-C 有线连接 Mac，鼠标/键盘日常通道保持不动。
2. 写独立的命令行 probe，先枚举/读取状态，不直接发送写操作。
3. 分析 Web Hub 前端源码和浏览器 WebHID 请求，寻找“切模式/切 BT/读状态”的现有命令；不要把 Sync Time 命令误当作切通道命令。
4. 若协议明确，单独执行一次 BT2 切换，确认 Windows 能收到 K94 输入。
5. 再执行 BT1 回切，确认 Mac 能收到输入。
6. 记录命令字节、接口、报告长度、ACK、切换耗时、失败行为。
7. 尝试断线、Windows 休眠、重复命令和快速往返，检查是否卡死。

### 通过标准

得到最小的、可重复验证的 K94 API：

```text
get_state() -> mode, channel, connection_status
switch_to(BT1 | BT2 | BT3 | RF24 | USB) -> ACK / timeout / error
```

如果实际没有状态读取或 ACK，必须明确标出，不能假装有可靠状态反馈。

## 8. 阶段 C：需要固件时的最小修改

仅在阶段 B 证明没有现成入口后考虑。

1. 先刷官方/未修改重建固件的可恢复性要单独评估，未经用户明确同意不执行。
2. 设计一个 narrow raw HID command，仅暴露读取状态和切换已有 BT 通道，不重写无线协议。
3. 修改必须局限在键盘入口和 raw HID handler，避免改动 RF、RGB、屏幕、休眠和键位行为。
4. 保留固件版本号、VIA 兼容性、按键映射、启动恢复路径。
5. 为命令格式、长度、无效输入、重复命令和超时做主机侧测试。
6. 先让用户确认固件修改的具体内容、恢复材料、可能失效的功能，再进行刷写。

### 禁止默认采用的路径

- 不绕过芯片读保护、secure boot 或其他锁。
- 不在没有恢复固件/硬件版本确认时尝试网上找到的相似固件。
- 不把 K94 原厂预编译库或反编译内容直接发布到公开仓库。
- 不用“QMK 支持蓝牙”推断 K94 的自定义三模实现一定开源。

## 9. 阶段 D：鼠标控制路径，单独设 Go/No-Go

### 先回答的问题

M585/M590 是否有可从 Mac/Windows 主机调用的通道切换接口？

### 研究步骤

1. 只读枚举蓝牙 HID 服务和 HID++ 能力，不修改配对。
2. 查公开的 Linux/Solaar/Libratbag/hidapitester 资料，看该型号是否支持 host channel change、device switch 或 host switching。
3. 明确“Easy-Switch 按键手动切换”与“主机可以发命令切换”不是同一个能力。
4. 如果存在接口，实现最小 probe：切到 Windows、回到 Mac，各验证输入和恢复。
5. 如果不存在接口，记录为 No-Go，停止为该鼠标反复尝试私有命令。

### 三条后续路线

- **D1：现有鼠标可控。** 实现设备通道切换，和 K94 共用状态机。
- **D2：现有鼠标不可控，但可用软件输入转发。** 自己实现鼠标事件转发，K94 仍走物理通道切换。必须重写/验证 macOS 光标隐藏与焦点状态，不复用 Deskflow 的 macOS 1.27.0 跨屏状态管理。
- **D3：增加 USB HID 转发硬件。** 键鼠接转发器，由转发器选择输出到 Mac 或 Windows。需要额外硬件和嵌入式开发，先与用户讨论成本、物理连接和 UAC 限制，不默认采购。

## 10. 阶段 E：自研跨屏服务

在 K94 和鼠标控制路径至少有可行结论后实施。

### 状态机

建议明确以下状态，不允许只靠全局布尔值：

```text
LOCAL_MAC
SWITCHING_TO_WINDOWS
REMOTE_WINDOWS
SWITCHING_TO_MAC
RECOVERY_REQUIRED
```

每次切换是带 ID 的操作：

1. 收到边缘或热键请求。
2. 检查目标在线/可用。
3. 锁定重复请求，记录开始时间。
4. 切换设备通道或启用输入转发。
5. 等待 ACK/连接/客户端确认。
6. 成功才提交 `activeTarget`。
7. 失败则超时回到上一个安全状态，显示日志和恢复入口。

### 必须处理

- 屏幕边缘驻留与防抖，不能一进 Windows 就因坐标映射马上弹回 Mac。
- 热键在所有活动状态下可用。
- 用户拖拽、长按修饰键时避免意外切换。
- Windows 睡眠、关机、网络变化、Mac 换 Wi-Fi 时不盲目切走。
- 状态不确定时允许回到 Mac，且不让两侧同时消费输入。
- 日志带时间戳、状态、命令、结果和延迟。
- 默认不记录实际输入文本或剪贴板内容，只记录类型、大小和状态。

### GUI

- Windows 和 Mac 都显示运行状态。
- 提供活动电脑、连接状态、最近错误、Start/Restart/Stop/Quit。
- 提供“回到 Mac”与“恢复旧方案”按钮。
- 终端不是日常使用界面，故障详情放日志窗口。

## 11. 阶段 F：剪贴板

将剪贴板与输入切换分开实现：

1. 先支持文本，确认 Unicode、中文和常用快捷键。
2. 再支持图片，限制大小并处理格式转换。
3. 文件同步定义元数据、临时目录、校验、取消、失败清理和覆盖策略。
4. 不把本地剪贴板变动无控制地循环回另一台机器。
5. 网络异常时给出状态，不阻塞输入切换。

LocalSend 可继续承担大文件传输；是否把文件复制纳入自研协议，根据用户实际需求决定，不为了功能列表而重写成熟传输工具。

## 12. 测试矩阵

| 类别 | 测试 |
| --- | --- |
| 基础切换 | 左右边缘往返、热键往返、快速连续往返 |
| 输入 | 打字、中文输入、复制粘贴、Shift/Ctrl 长按、组合键、拖拽 |
| 鼠标 | 光标唯一性、按钮、滚轮、侧键、焦点点击 |
| Windows 安全层 | UAC、锁屏、登录界面分别验证 |
| 网络 | 换 Wi-Fi、断网、IP 变化、重连、Windows 未开机 |
| 电源 | Windows 睡眠唤醒、Mac 休眠/恢复、K94 休眠唤醒 |
| 固件 | K94 正常键位、VIA、屏幕、灯光、三模和恢复操作 |
| 故障恢复 | 命令超时、通道无响应、客户端退出、服务重启 |
| 数据 | 文本、图片、文件、中文文件名、大文件、覆盖冲突 |

记录实际次数和日志。50 次往返通过不能证明 UAC 通过，网络连接 Established 也不能证明输入正确。

## 13. 逆向工具选择

优先候选：

1. `OrbitCurve/firmware-reverse-engineering`
   - https://github.com/OrbitCurve/firmware-reverse-engineering
   - 约 234 stars，2026-11-17 仍活跃。
   - 提供面向 Codex/Claude/Droid 的固件提取、静态分析、Ghidra、模拟和报告工作流。
   - 适合 FS026 固件分析，但只提供工作流，分析能力取决于 Ghidra 是否支持该目标。
2. `sjkim1127/Reversecore_MCP`
   - https://github.com/sjkim1127/Reversecore_MCP
   - 约 224 stars，2026-11-18 仍活跃。
   - 提供 Radare2、Ghidra 相关二进制分析和功能重建，可交叉验证。

使用原则：

- 先审查 SKILL.md、安装脚本、依赖、网络行为和实际适配范围，再安装。
- 优先在独立研究目录或隔离环境中运行。
- 不因为仓库叫 reverse-everything 就默认安装；目前没有找到证据表明这个名字本身是本项目最合适的工具。
- 公开源码能解决的问题不用反编译补齐，优先追踪 raw HID、WebHID、UART/SPI 和已有符号。

## 14. 回退策略

### 14.1 研究期间

保持现有 Deskflow 与已停用 Flow 状态不变。所有 probe 在 USB 有线模式下进行，不改配对，不自动启动新服务。

### 14.2 自研方案试用失败

1. 停用自研 daemon、取消登录启动、退出相关 GUI。
2. 恢复 K94 为普通原厂固件/原键位，或者停止使用其自定义命令。
3. 恢复 K94 到 Mac 的 BT1，鼠标恢复到可用通道。
4. 根据当时状态恢复 Deskflow 或 Logitech Flow。
5. 保留实验日志，不在失败后删除证据。

### 14.3 当前 Deskflow 的已知恢复点

- Mac 服务标签：`org.deskflow.deskflow.server`。
- Mac 配置：`~/Library/Deskflow/Deskflow.conf`。
- Windows 托盘 GUI 和 `Deskflow Client` 登录任务。
- Logi Options+ 当前仍安装，Mac `com.logi.cp-dev-mgr` 与 Windows `Open Logi Options+` 为停用状态。
- 不要同时启用 Flow、Deskflow 和自研边缘切换。

## 15. 给接手模型的首个执行清单

按顺序执行，遇到相应结果就进入对应分支：

- [ ] 读完两份 AGENTS.md、本文和运维日志第十三节。
- [ ] 建立状态记录和证据清单，记录当前运行配置与源码版本。
- [ ] 获取官方源码并完整阅读 K94 入口、raw HID/VIA、无线库符号。
- [ ] 分析 K94 Web Hub 的 WebHID 接口，找是否已有通道切换命令。
- [ ] 分析 VIA JSON 与 raw HID 描述符，确认能否直接控制 BT1/BT2。
- [ ] 尝试无修改编译官方 K94 固件，确认恢复工具链。
- [ ] 写只读 USB/HID probe，先枚举再测试明确可逆的通道命令。
- [ ] 对鼠标 M585/M590 做独立的主机可控性调查。
- [ ] 将结论写成：K94 `Go/No-Go`、鼠标 `D1/D2/D3`、恢复材料是否齐全。
- [ ] 只有上述结论明确后，才开始写跨屏状态机或讨论固件补丁。

## 16. 最重要的决策点

项目是否成立，主要取决于两个可验证的问题：

1. **K94 是否能由主机可靠地切换蓝牙通道并报告结果？**
2. **现有鼠标是否能被主机控制换通道？**

第一问决定 K94 能否无缝跟随，第二问决定是否需要软件鼠标转发或额外硬件。不要先投入大量时间写 GUI 和剪贴板，再发现这两个底层能力不存在。

