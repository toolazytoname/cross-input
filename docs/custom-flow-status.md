# K94/M585 自研跨屏输入实施状态与证据

更新时间：2026-11-19 America/Los_Angeles。本文对应 K94-CUSTOM-FLOW-PLAN.md 的阶段 A/B/C，以及 M585/M590 阶段 D 的只读调查与双向硬件闭环。所有“运行时已验证”只用于实际设备返回或用户实测；未发送写命令或仅有离线验证的项目一律保持对应限定。

## 1. 当前结论

| 问题 | 结论 | 依据等级 |
| --- | --- | --- |
| K94 原厂固件能否直接由主机切 BLE/2.4G/USB？ | **No-Go**。公开源码、Web Hub 和闭源库符号都没有主机侧切通道 API。USB raw HID 与标准 VIA 通路已于 2026-11-19 实测通过。 | 源码/Hub/静态反汇编证据 + USB 只读运行时验证 |
| K94 项目是否继续？ | **阶段 C 离线完成，硬件双向仍 No-Go/阻塞**。补丁可独立应用、编译并通过 host mock，但 stock USB raw 与 BLE handler 模式互斥；恢复材料不齐全，不能刷写。 | 离线构建/测试 + 静态反汇编 + B1 运行时证据 |
| M585/M590 控制路线 | **D1 双向硬件闭环已通过；自动贴边已到离线实现**。Mac→Windows 正向切换已由用户确认；Windows→Mac 单次回切后 Mac 复核 current slot 1。 | Mac/Windows 双向实际设备返回；自动贴边监督验收与完整输入体验未执行 |
| M585/M590 备选路线 | D2 作为 D1 双向失败后的回退；D3 当前 No-Go，不购买、不引入硬件。 | 决策 |
| K94 固件能否未修改编译？ | **能**。两次干净构建产物 SHA-256 一致。 | 实际编译证据 |
| 固件恢复/刷写材料是否齐全？ | **不齐全**。无 revision 匹配的 custom bootloader 刷写工具、PCB 版本确认和当前固件备份；不能刷写。 | 官方 README 与材料盘点 |

本 worker 没有停止或重启 Deskflow/Flow，没有改变 K94/M585 配对，没有刷固件，没有拆机，没有修改 Windows 网络/WOL/SSH/RDP。协调者按用户授权执行过一次 M585/M590 通道切换，随后只读复查 current index 回到 Mac；配对关系未改变。只读快照显示 Mac Deskflow server 进程仍在运行，com.logi.cp-dev-mgr 仍为 disabled；Logi Options+ updater 进程存在，这是未由本轮改动的既有状态。

## 2. 版本与关键哈希

| 材料 | 版本/命令 | SHA-256 |
| --- | --- | --- |
| K94 官方源码 | git clone --recurse-submodules https://github.com/KEMOVE-Official/KEMOVE-QMK-Firmware.git；HEAD c04f415f5934d6e48a76e7100a2c541116941b90 | 按目录保留 |
| Git 子模块 | git submodule status 为空；依赖以普通源码提交，修订见 KEMOVE_PACKAGE.md | 事实 |
| 工厂参考 BIN | 81,484 bytes，file 识别为 TTComp archive data, binary, 1K dictionary | ffd34212071191f7083f82682b090a0c26d9b68ca4934b613472707979cb1292 |
| 仓库 VIA JSON | 10,871 bytes | e12165f7c7d249e6e04946b697edde4a2c927c32db915bb5b51a7b50a7a46b67 |
| 官方下载 VIA JSON | 11,135 bytes；Python 解析后与仓库 JSON 相等 | 04132e452e467591e7fbb818f33043f66d032ae077cacbf3fecf1b79c5546cae |
| KEMOVE Web Hub 入口 | https://app.kemove.com/，asset index-DFFgNwDd.js | entry 3149c01f7ddca85f39b48d6edefc41bbdd67d3357d4f1e743a4288bd4e1d5425；JS 5be9728d2861d98dfce0550a7614b28ba0abf7f52165388ec07064b53644f988 |
| Solaar 源码 | git clone --depth 1 https://github.com/pwr-Solaar/Solaar.git；HEAD e7304c4c451cc9bb4f206a914844525e67856a28 | 按目录保留 |
| K94 闭源库 | 329,986 bytes，ARM ELF relocatable object，带 DWARF，未 strip | 0c0bdedde8402ff842679a5f81573765c5ea14c67758ab4d7d186be01dc92d48 |
| 提取的 rdr_common.o | 322,612 bytes | 7a31723d059995537ce51107069159a61d9fbd8bffda8cf57c1b68ba1d14a4d3 |
| 本地重建 K94 BIN | 79,816 bytes，两次构建相同 | 1e0c0557af6ebad3742c084e20514f48b2d71c3390a85590a8d9d886a398d7e6 |
| 阶段 C 统一 diff | 10,451 bytes，对官方基线 apply-check 通过 | 1bdd2c85591c8be1696d9a3e3b78e82a92a322893b146ef767c8590c6ccd0cef |
| 阶段 C built BIN | 80,548 bytes，未刷写 | fb45c9c74bf5ca89d7d11351c392e4d0c38dc7201db1129fe869beca6dc9100c |
| 阶段 C built ELF | text 78,598、data 1,948、bss 14,432 | 69862d51267961043b580985d3b3fd1f620258e5198f34eb033947759e8c3ce6 |
| M585 一次性实验脚本 | 12,090 bytes；默认 plan-only，本轮未接触硬件 | 0364d2229d59373283cfdbabcc796b222abdf0955e0fce254f2272058f0e8f8a |
| M585 Mac→Windows 日常入口 | 714 bytes；显式 attempt-id、guard 与日志 | 3c543fa981022d2335f6bdc58d2a47c1946605bc55aec2c4dd7c58a508570ea0 |
| M585 Mac 自动贴边 controller | 43,231 bytes；21 项单元/集成测试通过，只读环境检查通过 | 8b31b63bc0d34c1106d3a700b527c214bc93591cd3e2afccb2caacac58cb7bb8 |
| Windows HID 只读查询脚本 | 15,489 bytes；12 项静态审计通过，并已在 Windows 只读运行 | 4b875c31604e336e2047edeba7123a464104f36c483022c999f18a1badd29d90 |
| Windows 协议 probe | 110,680 bytes；Windows 内置编译 + 15 项可控 transport 测试、27 项静态审计通过 | 8fa534621e3db6a08ac7688c3869485cfda39760266e369b08c1456b1ed8f4d1 |
| Windows 协议 probe SSH 入口 | 4,236 bytes；固定 metadata/只读/回切/edge/hotkey/peer-health/K94/test 入口 | 5d78010da613a678d021a29b0c347c4435230b6f4b66dd5a061fd773bca499b8 |
| Windows supervisor bootstrap | 2,864 bytes；启动前创建 JSONL，保留子进程退出码 | 57f905a13adfc90a768b532ddc5b6302f65e7d1d2819cbb45beb40cd55bbf59b |
| Windows Interactive task controller | 2,722 bytes；register/start/status/stop/remove | 8839609cc2fa7cd488e252fb249d8c9c8a12bbfacca782ba7127903f1bdde879 |
| Windows SSH task 入口 | 1,673 bytes；可回退 register-start/status/stop/remove | a01799f7e64f6207be67639549aa3ab86420faf10ccb2d8b1d635e9457e60072 |
| Windows 可见 TEMP 启动器 | 1,008 bytes；不提权、不安装，支持 watch/dry-run | f55562a30f38ef6ea67aec7df7b6c4dbcc23a4897bd34ff4051839055bfe507e |
| Windows TEMP 复制脚本 | 819 bytes；仅复制四个文件，不执行 | 70f675520f9da1f0b018ae5a41573fdb98924cdf61a87ec2da39498edb5f23ab |
| ARM 工具链 PKG | Arm GNU Toolchain 15.3.Rel2；PKG SHA-256 与 Homebrew cask 声明一致 | 779972fa545f738bfbba2ff0ae44d5ad7510b00cfb414702974844ba625412f3 |

全部本轮证据文件哈希见 [evidence/SHA256SUMS](../evidence/SHA256SUMS)。

环境：macOS 27.2.1 Build 26B131，arm64；Python 3.9.6；QMK CLI 1.2.0；hidapi 0.14.0.post4；Arm GNU Toolchain 15.3.1；Node 24.22.3；Git 2.54.0。

## 3. 阶段 A：K94 源码、Hub 与固件材料

### 3.1 QMK raw HID / VIA 源码事实

执行过：

~~~sh
git -C research/k94/KEMOVE-QMK-Firmware rev-parse HEAD
git -C research/k94/KEMOVE-QMK-Firmware submodule status
rg -n -i 'raw_hid|via_command|usage_page|report_id' \
  research/k94/KEMOVE-QMK-Firmware/keyboards/8r101_k94 \
  research/k94/KEMOVE-QMK-Firmware/lib/rdr_lib \
  research/k94/KEMOVE-QMK-Firmware/quantum \
  research/k94/KEMOVE-QMK-Firmware/tmk_core
~~~

[事实] K94 目标是 keyboards/8r101_k94，info.json 为 VID 0x36B0、PID 0x314B、processor FS026、bootloader custom。via keymap 设置 VIA_ENABLE = yes，QMK common_features.mk 因此设置 RAW_ENABLE = yes。

[事实] QMK raw HID 默认 usage page/usage 是 0xFF60/0x61，报告长度 RAW_EPSIZE。源码里的 raw collection 同时声明 input usage 0x62 和 output usage 0x63。证据：[evidence/k94/qmk-raw-default-usage.txt](../evidence/k94/qmk-raw-default-usage.txt)、[evidence/k94/qmk-raw-hid-descriptor-source.txt](../evidence/k94/qmk-raw-hid-descriptor-source.txt)。

[事实] K94 键盘目录和 lib/rdr_lib 没有 via_command_kb 或 raw_hid_receive 覆盖；唯一命中是 QMK 核心 quantum/via.c 的 weak via_command_kb() 和标准 raw_hid_receive()。因此公开源码中的 raw HID 入口只处理标准 VIA 命令。证据：[evidence/k94/k94-via-entry-search.txt](../evidence/k94/k94-via-entry-search.txt)。

[事实] 标准 VIA 命令 id_get_protocol_version = 0x01 可做只读探测；该源码版本的 VIA_PROTOCOL_VERSION 是 0x000C。这可以验证 USB raw HID 通路，但它不是切通道命令。

### 3.2 KEMOVE Web Hub 事实

执行过：

~~~sh
curl -L --fail --silent --show-error 'https://www.kemove.com/pages/k94-hub' \
  -o research/k94/k94-hub.html
curl -L --fail --silent --show-error 'https://app.kemove.com/' \
  -o research/k94/kemove-app.html
curl -L --fail --silent --show-error \
  'https://app.kemove.com/assets/index-DFFgNwDd.js' \
  -o research/k94/kemove-hub-index.js
npx --yes prettier@3.8.1 --parser babel \
  research/k94/kemove-hub-index.js > research/k94/kemove-hub-index.pretty.js
~~~

[事实] Web Hub 的设备表把 0x36B0_0x314B_0 标为 protocol QMK、name KEMOVE K94。QMK 连接探测先发 VIA 命令 1 读取协议版本，并提示授权 0xff60 通信口。证据：[evidence/k94/webhub-k94-entry.txt](../evidence/k94/webhub-k94-entry.txt)、[evidence/k94/webhub-qmk-probe.txt](../evidence/k94/webhub-qmk-probe.txt)。

[事实] Web Hub 对 K94 暴露的 BLE1/BLE2/BLE3/2.4G/USB 是可配置键码 MD_BLE1、MD_BLE2、MD_BLE3、MD_24G、MD_USB。检索整个 1.8 MB Hub JS，没有发现 Logitech 式 Change Host、switch host、host switch 或 K94 专用主机切通道 API；命中只有键码和 UI 模式图标。证据：[evidence/k94/webhub-k94-custom-keycodes.txt](../evidence/k94/webhub-k94-custom-keycodes.txt)、[evidence/k94/webhub-host-switch-search.txt](../evidence/k94/webhub-host-switch-search.txt)。

[推断] Web Hub 的 K94 流程是“通过 VIA 配置一个会切模式的按键”，不是“主机直接调用切通道 API”。这解释了为什么 Hub 不需要私有切通道命令。

### 3.3 闭源无线库静态证据

macOS ar 不能直接处理该 GNU archive 的 rdr_common.o/ 成员名；我用 Python 按 archive header 提取到 evidence/k94/rdr_common.o，没有修改库本身。

执行过：

~~~sh
ar t research/k94/KEMOVE-QMK-Firmware/lib/rdr_lib/librdrcommon.a
nm -gU research/k94/KEMOVE-QMK-Firmware/lib/rdr_lib/librdrcommon.a
nm research/k94/KEMOVE-QMK-Firmware/lib/rdr_lib/librdrcommon.a | rg ' U (raw_hid|via_)'
dwarfdump --debug-info evidence/k94/rdr_common.o
research/k94/toolchain-pkg/bin/arm-none-eabi-objdump -dr \
  --disassemble=User_process_record_user evidence/k94/rdr_common.o
~~~

[事实] librdrcommon.a 只有一个 ARM/Thumb ELF object，带 DWARF。导出 Uart_Key_Mode_Key_Scan、User_process_record_user、Spi_Send_Commad、Mode_Synchronization、Keyboard_Info、Keyboard_Status 等符号；未定义 HID/VIA 符号只有 raw_hid_send，没有 raw_hid_receive 或 via_command_kb。证据：[evidence/k94/rdr-library-key-symbols.txt](../evidence/k94/rdr-library-key-symbols.txt)。

[事实] DWARF 显示该库由 GNU C11 10.1.0、Cortex-M0、Windows 构建路径编译。反汇编中 User_process_record_user() 的 BLE1/BLE2/BLE3 分支分别在清理键盘状态后调用 Spi_Send_Commad(1/2/3) 并保存状态；USB 分支调用 Spi_Send_Commad(8)、es_restart_usb_driver() 并保存状态。证据：[evidence/k94/user-process-mode-switch-disassembly.txt](../evidence/k94/user-process-mode-switch-disassembly.txt)。

[事实] rdr_common.h 标明这些值属于 SPI 命令：USER_SWITCH_BLE_2_MODE = 0x02、USER_SWITCH_USB_MODE = 0x08 等。MD_BLE2 等 QMK 键码进入闭源库的按键处理路径后才转换为这些 SPI 命令。

[推断] USER_SWITCH_* 常量不能作为 USB raw HID payload 直接发给 K94；它们是主控发给无线模块的内部 SPI 协议值。最小固件补丁应复用现成按键处理/切换路径，而不是把常量原样转发到 raw HID。

[未知] 无线模块是否返回异步连接状态、何时提交 Keyboard_Status、切换失败时是否回滚。仅靠静态证据无法证明可靠 ACK。

### 3.4 2026-11-18 BLE 快照

执行过：

~~~sh
research/mouse/venv/bin/python scripts/k94_readonly_probe.py \
  > evidence/k94/k94-probe-current-list.json
ioreg -r -c IOHIDDevice -l > evidence/k94/current-ioreg-iohiddevice.txt
system_profiler SPUSBDataType -detailLevel full \
  > evidence/k94/current-usb-system-profiler.txt
~~~

[事实] 2026-11-18 快照时，K94 以 BLE 名称 KEMOVE K94-1 连接，VID/PID 为 14000/12292，即 0x36B0/0x3004。report descriptor 只有 keyboard、mouse、system、consumer、NKRO 等 HID 集合，没有 0xFF60/0x61 raw collection。系统 USB 枚举中没有 K94。

[事实] 2026-11-18 BLE 快照不能验证 USB 模式的 VID/PID、raw interface 或 VIA 响应。当时 scripts/k94_readonly_probe.py 输出 qmk_raw_collections: []，这是未插 USB 时的预期结果，不证明 USB 模式缺少 raw 接口；该未知已由下节 B1 运行时验证解除。

### 3.4.1 K94 USB B1 只读运行时验证（2026-11-19）

用户确认把 K94 用 USB-C 接到 Mac mini 并拨到 Wired 后，按已审核范围执行：

~~~sh
research/mouse/venv/bin/python scripts/k94_readonly_probe.py \
  > evidence/k94/k94-usb-probe-list.json
research/mouse/venv/bin/python scripts/k94_readonly_probe.py --via-probe \
  > evidence/k94/k94-usb-via-protocol-probe.json
ioreg -r -c IOHIDDevice -l \
  > evidence/k94/k94-usb-ioreg-iohiddevice.txt
~~~

[事实，运行时已验证] USB 枚举为 manufacturer RDMCTMZT、product KEMOVE K94、VID/PID 14000/12619，即 0x36B0/0x314B，serial 20250901。唯一 QMK raw collection 为 usage page 65376（0xFF60）、usage 97（0x61）、interface 1，输入/输出 report size 均为 32 bytes。ioreg report descriptor 为 0660ff0961a1010962150026ff009520750881020963150026ff00952075089102c0。证据：[evidence/k94/k94-usb-probe-list.json](../evidence/k94/k94-usb-probe-list.json)、[evidence/k94/k94-usb-raw-interface-ioreg.txt](../evidence/k94/k94-usb-raw-interface-ioreg.txt)。

[事实，运行时已验证] 对该 raw collection 发送 33-byte HID 写帧 000100...00（report ID 0 + 32-byte VIA command 0x01），设备返回 01000c...00。解码 VIA protocol version 为 0.0C，与源码 expected 0.0C 一致。证据：[evidence/k94/k94-usb-via-protocol-probe.json](../evidence/k94/k94-usb-via-protocol-probe.json)。

[事实] 本 probe 未出现 macOS 授权提示，未打开 M585/M590，未发送 MD_*、USER_SWITCH_*、VIA set/save/reset/bootloader 或任何切通道命令。

[推断] B1 已通过：K94 有线模式的 raw HID 枚举和标准 VIA 协议通路真实可用。由于该通路只进入标准 VIA handler，阶段 B“原厂固件主机切通道 No-Go”的结论不变，可进入阶段 C 的最小补丁设计与编译验证。

### 3.5 未修改编译验证

第一次尝试 make 8r101_k94:via 失败，原因是本机没有 qmk CLI。随后在 research/k94/qmk-venv 安装 QMK 1.2.0 和仓库 requirements.txt，第二次失败在 arm-none-eabi-gcc 缺失。

brew install --cask gcc-arm-embedded 下载成功但安装需要 sudo 密码，未安装到系统。改为在独立目录下载并校验官方 Arm PKG，然后仅解出工具链：

~~~sh
curl -L --fail --show-error \
  'https://gitlab.arm.com/api/v4/projects/tooling%2Fgnu-toolchains-for-arm/packages/generic/gnu-toolchain/15.3.rel2/arm-gnu-toolchain-15.3.rel2-darwin-arm64-arm-none-eabi.pkg' \
  -o research/k94/toolchain-pkg/arm-gnu-toolchain.pkg
shasum -a 256 research/k94/toolchain-pkg/arm-gnu-toolchain.pkg
cd research/k94/toolchain-pkg
xar -xf arm-gnu-toolchain.pkg
tar -xf Payload ./arm-none-eabi
tar -xf Payload ./bin ./lib ./libexec
~~~

GCC 15 对 FS026 头文件错误的 header guard 按 -Werror 报错。以下命令只通过 QMK 已提供的 ALLOW_WARNINGS=yes 关闭警告转错误，没有修改源码：

~~~sh
PATH="$PWD/research/k94/qmk-venv/bin:$PWD/research/k94/toolchain-pkg/bin:$PATH" \
ALLOW_WARNINGS=yes make 8r101_k94:via
~~~

[事实] 编译成功，产物保存在 [evidence/k94/build](../evidence/k94/build)。删除 .build 后重建一次，两次 BIN SHA-256 均为 1e0c0557af6ebad3742c084e20514f48b2d71c3390a85590a8d9d886a398d7e6。ELF arm-none-eabi-size 为 text 77,866、data 1,948、bss 14,432。

[事实] 工厂参考 BIN 与本地重建 BIN 大小和哈希不同。二者都是 TTComp 压缩/封装格式，不是可直接比对的 plain MCU image。

[推断] 编译成功证明公开源码、依赖和工具链基本完整；不证明 rebuilt BIN 与当前键盘 PCB/固件兼容，更不能作为恢复镜像。

### 3.6 恢复材料判断

已有：

- 官方源码 HEAD 和依赖源码。
- 官方工厂参考 BIN 8r101_k94_via.bin 及 SHA-256。
- 官方 VIA JSON；下载版和仓库版语义相同。
- 本地可复现构建工具链和编译产物。
- K94 官方 README 和 KEMOVE_PACKAGE 的刷写风险边界。

缺失：

- 当前键盘 PCB revision、出厂固件版本和工厂 BIN 是否匹配的证据。
- FS026 custom bootloader 的官方进入方法、刷写工具和命令。
- 从当前设备读回固件备份的方法。
- 刷坏后可验证的官方恢复流程。
- revision 匹配的无线模块/屏幕固件与恢复材料。

结论：固件恢复材料不齐全，阶段 C 只能设计和编译，不能刷写。

## 4. 阶段 B：K94 Go/No-Go 和下一步最小实验

### 4.1 结论

原厂固件主机控制切通道：No-Go。

理由：

1. 公开源码只把 raw HID 接到标准 VIA 处理器，没有键盘级 override。
2. Web Hub 把 K94 识别为 QMK/VIA，只提供 MD_* 键码配置，没有主机侧 Change Host API。
3. 闭源库显示 USER_SWITCH_* 是内部 SPI 命令，入口是按键处理函数，不是 raw HID 命令解析函数。
4. 2026-11-18 BLE 枚举没有 raw collection；2026-11-19 USB B1 实测存在 raw collection 和 VIA 0.0C 响应，但仍未发现主机侧切通道 API。

### 4.2 最小实验 B1：USB 只读验证（已通过）

#### 运行前置条件、授权对象和回退

| 项目 | 约定 |
| --- | --- |
| 物理前置条件 | 用户确认已把 K94 用 USB-C 数据线接到 Mac mini；我不发送任何“切换到有线/USB 模式”的命令，也不改现有 BT1/BT2/BT3/2.4G 配对。 |
| 授权对象 | 只授权运行 `research/mouse/venv/bin/python scripts/k94_readonly_probe.py` 的宿主进程访问 K94 USB raw HID collection：VID `0x36B0`、PID `0x314B`、usage page `0xFF60`、usage `0x61`。本 probe 不使用浏览器 WebHID；如 macOS 要求 Input Monitoring/HID 权限，授权对象是承载本 worker 终端的 Orca/terminal 宿主，而不是整个浏览器。 |
| 允许动作 | HID 枚举；选择上述唯一 raw collection；发送 32-byte VIA command `0x01`（Get protocol version）；读取一次响应；保存 JSON 证据。 |
| 禁止动作 | 不发送 MD_*/USER_SWITCH_*、VIA set/custom save/bootloader/eeprom reset 等任何改变状态命令；不打开或授权 M585/M590；不运行刷写工具。 |
| 立即中止条件 | USB VID/PID 不是 `0x36B0/0x314B`、没有 `0xFF60/0x61` collection、HID open/write/read 失败、收到无法识别响应，或用户要求停止。 |
| 失败回退 | 停止脚本并保存错误；拔掉 USB-C 线。本轮不发送模式切换或配对命令；用户已物理拨到 Wired，如需恢复日常使用，由用户用原有物理开关回 BT1，不尝试发送恢复命令。 |

用户已把 K94 用 USB-C 数据线接到 Mac mini 并拨到 Wired。B1 已于 2026-11-19 执行通过；以下命令保留为复现步骤：

~~~sh
research/mouse/venv/bin/python scripts/k94_readonly_probe.py \
  > evidence/k94/k94-usb-probe-list.json
research/mouse/venv/bin/python scripts/k94_readonly_probe.py --via-probe \
  | tee evidence/k94/k94-usb-via-protocol-probe.json
~~~

通过条件：

- USB 枚举 VID/PID 为 0x36B0/0x314B。
- 存在 usage page 0xFF60、usage 0x61 的 raw collection。
- VIA 协议版本响应为 0.0C 或该键盘实际固件声明的版本。
- 不发送任何 BLE/RF/USB 切换写命令。

若浏览器或系统需要 HID 授权，只授权 K94 的 raw collection。不要授权或打开 M585/M590。

### 4.3 阶段 C 最小补丁边界

2026-11-19 已按以下边界完成离线阶段 C：

1. 使用标准 VIA custom value 命令 `0x07/0x08`、channel `0`、私有 value `0xB1`、协议版本 1；没有新造顶层命令 ID。
2. 切换执行复用键盘原生 `process_record_user()` 的 `MD_BLE1/2/3` 瞬时按键路径：先 pressed=true、后 pressed=false，不重写 RF 协议，不直接发送 `USER_SWITCH_*`。
3. 严格校验 32-byte 长度、版本、target 1..3、非零 request ID、保留字节和尾部零；未知 custom 子命令返回 VIA `0xFF`。
4. 支持 pending 去重、同 ID 不同目标拒绝、并发 busy、completed request replay、already-current、3500 ms 持久化冷却和 source-mode fail-closed。
5. ACK 只表示 queued 或本地 callback 已提交，不表示目标主机收到输入；raw `Keyboard_Status` 字段只透传，不解释。
6. 已完整干净编译并保存 BIN/ELF/HEX/map/hash；统一 diff 对官方基线 `git apply --check` 通过。built ELF 反汇编验证 state task 两次调用 callback（true/false），生产 callback 将 pressed 写入 keyrecord 并两次调用 `process_record_user()`。
7. 未刷写、未进入 bootloader、未读取受保护固件、未向硬件发送任何 custom 命令。

详细协议、验证矩阵、模式互斥和恢复阻塞见 [k94-stage-c-protocol.md](k94-stage-c-protocol.md)。

### 4.4 阶段 C 硬件可达性结论

[事实] 官方源码 baseline 是 commit `c04f415f5934d6e48a76e7100a2c541116941b90`、tree `6450072e8ffe5a648c94427ca286b1e18f980e3e`，两者必须区分。

[事实] USB B1 运行时证明 wired USB 模式存在 raw HID，而 stock `User_process_record_user()` 的 BLE1/BLE2/BLE3 分支都要求 `Keyboard_Info.Key_Mode == QMK_BLE_MODE == 0`。USB 模式下 `Key_Mode == QMK_USB_MODE == 2`，这些分支会直接跳过。

[事实] 2026-11-18 BLE 快照没有 `0xFF60/0x61` raw collection。物理开关路径 `Key_Switch_Mode_Scan()` 切无线时调用 `Usb_Disconnect()`，再发送 SPI 命令并调用 `Save_Flash_Set()`。

[结论] 当前不存在已证明“同时可达且可执行”的 stock 控制路径：USB 有 raw 但 BLE handler 不可达；BLE handler 可达但没有 raw 控制口。补丁因此在 USB 源模式返回 `SOURCE_BLOCKED`，不排队、不执行，避免把 wired ACK 误当作双向方案。

[未知] 2.4G 接收器是否暴露可用的主机控制口、K94 在 2.4G 模式下的 raw 枚举、以及从 Windows 发起回切的控制通道均未验证。

[副作用] 真实 BLE slot 变更会调用 `Save_Flash_Set()`；反汇编确认它设置 `Save_Flash` 并重置 3 秒计数，后续保存路径会写持久化存储。频繁贴边切换会造成重复写入和延迟。补丁加 3500 ms 冷却，但这只是降低风险，不是完整闪存寿命方案。

[事实] Vector78 中断反汇编显示 Key_Ble_1/2/3_Status 若保持为 1，清除时会分别发送 SPI 0x05/0x06/0x07（配对命令）。因此仅合成 press 的适配器不安全；当前 host mock 和 built ELF 均验证 press/release 成对完成，不会留下 held flag。

## 5. 阶段 D：M585/M590 只读可控性

### 5.1 本机枚举事实

执行过：

~~~sh
system_profiler SPBluetoothDataType -detailLevel full \
  > evidence/mouse/mac-bluetooth-system-profiler.txt
ioreg -r -c IOHIDDevice -l > evidence/mouse/mac-ioreg-iohiddevice.txt
research/mouse/venv/bin/python scripts/m585_readonly_probe.py \
  > evidence/mouse/m585-probe-current-list.json
~~~

[事实] M585/M590 通过 BLE 连接，地址 FC:07:F2:53:5B:A2，VID/PID 0x046D/0xB01B，serial 7A09C04B5120EA18，固件 MPM05.10_0011，电量 100%。

[事实] 140-byte HID descriptor 包含 Logitech vendor collection：usage page 0xFF43、usage 0x0202、report ID 0x11、19-byte input/output 声明。这与 Solaar 的 HID++ long report 常量一致。证据：[evidence/mouse/m585-hid-descriptor-summary.txt](../evidence/mouse/m585-hid-descriptor-summary.txt)。

### 5.2 Solaar 公开源码证据

Solaar 设备转储 docs/devices/Multi Device Silent Mouse M585-M590 406B.txt 显示同型号：

- HID++ protocol 4.5。
- feature 9：CHANGE_HOST 1814 V1。
- feature 10：HOSTS_INFO 1815 V1。
- 转储设备有两个已配对 host。

实现证据：

- 读状态：feature function 0x00，响应前两字节为 host count 和 current host。
- 写切换：feature function 0x10，参数是 0-based host index；Solaar 标记 no_reply=True，设备不保证回包。
- 蓝牙直连设备用 HID++ long report 0x11、device number 0xFF，Software ID 会占用 request low nibble。
- ChangeHost 不持久化，避免把目标主机写进配置。

具体源码摘录见 [evidence/mouse/solaar-change-host-implementation.txt](../evidence/mouse/solaar-change-host-implementation.txt)。本轮只整理了该帧格式，没有发送 function 0x10。

### 5.3 本机只读 HID++ 查询尝试

#### 后续只读运行边界

| 项目 | 约定 |
| --- | --- |
| 物理前置条件 | M585/M590 继续保持当前 BLE 连接；不插 2.4G 接收器，不按 Easy-Switch，不重新配对。 |
| 授权对象 | 只在协调者单独确认后，授权承载本 worker 终端的 Orca/terminal 宿主进程打开 M585/M590 的 vendor HID++ collection：VID `0x046D`、PID `0xB01B`、usage page `0xFF43`、usage `0x0202`。 |
| 允许动作 | HID 枚举；Root GetFeature 查询 feature `0x1814` 的 index；对该 feature 发送 function `0x00` 读 host count/current host；保存原始帧和错误。 |
| 禁止动作 | 不发送 CHANGE_HOST function `0x10`，不写 HOSTS_INFO，不发 HID++ set/register 写命令，不用 sudo 绕过 macOS 权限。 |
| 立即中止条件 | open 失败、feature index 为 0/未知、响应与 Solaar 格式不一致、设备断链，或用户要求停止。 |
| 失败回退 | 停止脚本并保存错误；本轮未修改鼠标状态。若设备意外断链，由用户用既有 Easy-Switch 物理按键回到已知 Mac 通道；不尝试发送命令恢复。 |

~~~sh
research/mouse/venv/bin/python scripts/m585_readonly_probe.py --query \
  > evidence/mouse/m585-read-only-hidpp-probe.txt 2>&1
~~~

[事实] 枚举成功并列出 0xFF43/0x0202 vendor collection；随后 hid.device.open_path() 返回 OSError: open failed，因此 Root GetFeature 和 CHANGE_HOST 状态读取没有执行。

[推断] 该历史失败与默认独占打开方式相符：Solaar 在 Darwin 的 lib/hidapi/hidapi_impl.py 显式调用 hid_darwin_set_open_exclusive(0) 后再打开 HID 设备。

### 5.3.1 修正后的只读 HID++ 查询（2026-11-19）

已重写 scripts/m585_readonly_probe.py：

- 精确唯一匹配 046d:b01b 且 usage page/usage 为 FF43:0202 的 collection；匹配数不是 1 即失败。
- 通过同一 hidapi 动态库调用 Darwin 非独占打开设置，不使用 sudo 或 TCC 绕过。
- 查询前调用只读 IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)；本轮返回 granted，宿主为 Codex codex-darwin-arm64 进程树。
- 每帧固定 20 bytes：report 0x11、device 0xFF、feature index、function/SWID 0x01。
- 严格匹配 report ID、device number（BT 允许 FF 或 00）、feature index、function/SWID 和长度；识别 HID++ error、timeout、短写、无关通知，未匹配帧不用于索引发包。
- 白名单仅 Root GetFeature 0x1814 与该 feature function 0x00；Root 返回 index 0/无效、错误或超时时 fail-closed，不发第二包。
- 离线假传输 6 项测试通过，不触碰系统权限或输入配置。

运行时结果见 [m585-change-host-readonly-query.json](../evidence/mouse/m585-change-host-readonly-query.json)：Root GetFeature 返回 feature index 0x09；CHANGE_HOST function 0x00 返回 host_count=2、current_host_index=1。

[事实，运行时已验证] 该鼠标当前固件支持 CHANGE_HOST，feature index 为 9，共有两个 host，当前 slot 为 1。由于本次响应是在 Mac 当前 BLE 链路上读取到的，slot 1 映射 Mac 有现有设备证据支持；此次 CHANGE_HOST 查询本身不含名称，slot 0 由下节 HOSTS_INFO 只读确认。该只读阶段未发送 function 0x10。

### 5.3.2 HOSTS_INFO 只读映射确认（2026-11-19）

经协调者明确授权，脚本新增独立 `--hosts-info` opt-in 分支。该分支只允许 Root GetFeature `0x1815`、已严格解析出的 HOSTS_INFO function `0x00` GetHostInfo、每个已确认 slot 且回包 slot 匹配的 function `0x10` GetHostDescriptor，以及按描述符长度有限读取并校验 slot/offset/长度的 function `0x30` GetHostName。

该分支不导入或调用 Solaar `get_host_names()`，因此不会触发其 macOS hostname 不一致时的 function `0x40` set_host_name。离线假传输 11 项测试覆盖合法序列、能力位缺失、坏描述符、descriptor slot/name slot/offset 不匹配、错误/超时 fail-closed 和函数白名单。

本轮唯一一次设备读取见 [m585-hosts-info-readonly-query.json](../evidence/mouse/m585-hosts-info-readonly-query.json)。结果：slot 0 已配对且名称为 `LAZY-WINDOWS`，slot 1 已配对且名称为 `lazy的Mac Mini`。

[事实，运行时已验证] M585/M590 slot 0 为 Windows、slot 1 为 Mac，不再依赖运维台账旁证。该查询阶段未发送 CHANGE_HOST function `0x10`，也未发送 HOSTS_INFO function `0x40`。

### 5.3.3 一次用户授权的 Mac→Windows 实测（2026-11-19）

协调者执行、用户已明确授权且授权已消费；本轮 worker 未操作硬件。初次尝试时鼠标不在 Mac，前置枚举为 0 collections，脚本在打开设备前退出且 0 次写入。用户把鼠标按回 Mac 后重新完成严格前置检查：序列号 `7A09C04B5120EA18`、CHANGE_HOST feature index 9、current index 1，HOSTS_INFO 确认两个 host 与两个 descriptor slot。

实际写入证据：

- [m585-first-switch-attempt.jsonl](../evidence/mouse/m585-first-switch-attempt.jsonl)：Root/CHANGE_HOST 状态帧、20-byte switch frame `11ff091100...`、一次 `write-returned` 20/20。
- [m585-first-switch-mac-bluetooth.log](../evidence/mouse/m585-first-switch-mac-bluetooth.log)：06:44:27.719 Mac BLE 报告 M585/M590 disconnect；06:44:36.717 首次重新出现 BLE 电源源事件。
- 用户实际观察：Windows 硬件通道 1 光标响应。
- [m585-first-switch-mac-restored.json](../evidence/mouse/m585-first-switch-mac-restored.json)：后续只读复查 current index 回到 1，即 Mac 所在第二通道。

[事实，运行时已验证] 这证明该鼠标的一次 Mac→Windows 硬件通道切换和目标主机输入可用，且 no_reply 写入后没有重试或自动回切。

Deskflow 相关时间线来自 [m585-first-switch-deskflow.log](../evidence/mouse/m585-first-switch-deskflow.log)：06:44:27.125 Deskflow 先 Windows→Mac；06:44:27.719 鼠标 BLE 断链；06:44:36.717 鼠标首次重新出现在 Mac BLE；随后 06:44:45.935 Mac→Windows、06:44:46.193 Windows→Mac、06:44:46.483 Mac→Windows。

[结论] “鼠标硬件通道位于 Windows”与“Deskflow 活动屏/转发仍在控制 Windows”可以同时成立。约 290 ms 的快速屏幕变化与用户描述的“闪回来”吻合，但日志不能把该现象归属到某一次具体按键或鼠标事件；不能声称 Windows 软件回切已验证。

### 5.4 D1/D2/D3 结论

| 路线 | 结论 | 条件 |
| --- | --- | --- |
| D1 现有鼠标可控 | **双向硬件闭环通过；自动贴边待监督验收** | Mac→Windows function 0x10 已由用户确认；Windows→Mac 单次回切后 Mac 复核 current slot 1；离线 edge controller 已实现但未启用 |
| D2 软件鼠标转发 | 保留为 D1 失败后的回退 | 需重新实现 macOS 光标隐藏/焦点状态，不复用 Deskflow 1.27.0 的跨屏状态管理 |
| D3 USB HID 转发硬件 | **当前 No-Go** | 需要采购和嵌入式开发；在 D1/D2 未被运行时排除前不推进 |

D1 的已完成最小后续实验：

1. Windows 侧已实现只读可审计的 HID++ preflight 和固定 slot 1 回切入口。
2. 双向 function 0x10 均已各执行一次且无重试；后续自动化仍必须保留完整 preflight、单次提交和物理回退条件。
3. 记录 Windows 发送、Mac BLE 重新上线、Mac 光标实际输入和失败回退行为。

### 5.5 Windows 接收器与双向路线只读审计

#### K94 2.4G 静态证据

KEMOVE Web Hub 公开前端包含：

- 接收器身份 `0x36B0:0x3002`，名称 `2.4G Dongle`。
- 内嵌 `KEMOVE_K94_24G` 定义，identity 同样为 vendor `0x36B0`、product `0x3002`。
- D0 通知解析：报告 `AA D0`，byte 8 为 keyboardNum，bytes 9..12 为设备 VID/PID，byte 13 为 status；status=4、keyboardNum>=1 且设备标识满足 rfQmk 规则时，Hub 将接收器标记为 QMK over dongle（deviceMode 2），再走 VIA/QMK 探测。

证据：[webhub-k94-24g-static.txt](../evidence/k94/stage-c/webhub-k94-24g-static.txt)。

[事实] Web Hub 静态支持 K94 24G 配置和接收器上的 QMK/VIA 通路；Windows PnP 与 metadata-only HID caps 又实测确认接收器 MI_01 存在 `FF60:0061`、33-byte input/output raw collection。尚未向该 collection 发送 VIA/QMK 请求，因此“主机命令能到达键盘”仍属待验证；即使到达，当前补丁在 K94 source mode 1/2 也按设计返回 `SOURCE_BLOCKED`，不会执行 BLE 切换。

#### Windows 只读访问尝试

- `ssh-keygen -F 192.168.1.8` 只读确认已有 ED25519 host key。
- `ssh -G 192.168.1.8` 显示默认用户为 lazy、端口 22、只使用本机默认 public key。
- 使用 `BatchMode=yes`、`StrictHostKeyChecking=yes` 的非交互只读尝试返回 `Permission denied (publickey,password,keyboard-interactive)`，未猜凭据、未改 known_hosts、未改防火墙/RDP。

证据：[windows-known-host-check.txt](../evidence/k94/windows-known-host-check.txt)、[windows-ssh-effective-ip-config.txt](../evidence/k94/windows-ssh-effective-ip-config.txt)、[windows-ssh-readonly-ip-attempt.txt](../evidence/k94/windows-ssh-readonly-ip-attempt.txt)。

协调者随后找到既有 SSH 别名 `lazy-windows-ts`；BatchMode + StrictHostKeyChecking 只读登录成功，hostname 为 `lazy-windows`。协调者先用 Windows 自带 `Get-PnpDevice`/`Get-PnpDeviceProperty` 完成只读 PnP baseline，见 [windows-pnp-readonly-baseline.json](../evidence/windows/windows-pnp-readonly-baseline.json)：

- Windows PowerShell 5.1.26100.9818。
- K94 接收器 `36B0:3002` 在场，MI_01 HardwareIds 直接确认 `UP:FF60_U:0061`。
- 同一接收器 MI_02 COL05 是 `UP:FF00_U:0001`。
- M585/M590 只看到 BTHLE 配对节点 `BTHLE\DEV_FC07F2535BA3`；鼠标当时在 Mac 通道，未出现 Windows HID vendor collection。

已准备并修正单文件只读查询脚本 [windows_hid_readonly_query.ps1](../scripts/windows_hid_readonly_query.ps1)，可在 Windows 本地会话执行：

~~~powershell
powershell -NoProfile -File .\scripts\windows_hid_readonly_query.ps1
~~~

该脚本使用 Windows 自带 SetupAPI/HID API，先用 native `HidD_GetAttributes` 获取 VID/PID，再按目标过滤；对 USB 标准路径和 BTHLE/Bluetooth 路径都保留候选，避免在取得 attributes 前排除鼠标 BLE collection。它用 desiredAccess=0、read/write shared、`OPEN_EXISTING=3` 的元数据句柄调用 `HidD_GetPreparsedData`/`HidP_GetCaps`，输出 usage page、usage、input/output/feature report lengths、VID/PID、实例 ID 和 open/caps 错误码。它不调用 WriteFile/DeviceIoControl/Set 类 API，不安装依赖，不需要管理员，也不改变服务或网络。默认只输出 K94 接收器与 M585/M590；追加 `-All` 可枚举全部当前 HID interfaces。

互操作修正后，脚本包含完整 64-byte native `HIDP_CAPS` 布局并在运行时校验 size/offset，`HidP_GetCaps` 成功码固定为 `0x00110000`；`SetupDiGetDeviceInterfaceDetailW` 使用动态原生缓冲，Unicode cbSize x64=8/x86=6，设备路径从 offset 4 解码；枚举终止显式区分 ERROR_NO_MORE_ITEMS；JSON 用 `ConvertTo-Json -InputObject @(...)` 保持空数组/单项目稳定。Mac 端无 C# 编译器，但修正版已通过 12 项静态审计，并经现有 SSH 别名以 stdin 流式送到 Windows PowerShell 5.1 编译和只读运行；静态审计输出见 [windows-hid-query-static-tests.txt](../evidence/windows/windows-hid-query-static-tests.txt)。

实际 Windows metadata-only 运行结果见 [windows-hid-readonly-query.json](../evidence/windows/windows-hid-readonly-query.json) 和 [windows-hid-readonly-query-summary.txt](../evidence/windows/windows-hid-readonly-query-summary.txt)。7 个 K94 接收器 HID collection 全部 open/attributes/caps 成功；MI_01 为 `FF60:0061`，input/output report length 均为 33 bytes；MI_02 COL05 为 `FF00:0001`，input/output 均为 64 bytes。未发现 M585/M590 collection，与鼠标仍在 Mac 通道一致。本轮未发送 HID output report，也未做通道切换。

实际远端执行方式为标准输入流式传输，避免 Windows 命令行 8191 字符限制，也无需修改执行策略：

~~~sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes lazy-windows-ts \
  "powershell -NoProfile -NonInteractive -Command -" \
  < scripts/windows_hid_readonly_query.ps1
~~~

### 5.6 一次性 M585 切换实验脚本（离线准备）

已准备与默认只读 probe 分离的 [m585_single_switch_experiment.py](../scripts/m585_single_switch_experiment.py)。默认不带模式参数时只打印计划，不做 HID 枚举或 IO；`--dry-run` 才执行只读前置检查；`--apply` 还必须同时提供精确目标名、`--confirm-single-send` 和 `--user-ready-rollback`。

执行时它会重新选择唯一序列号 `7A09C04B5120EA18` 的 `046d:b01b FF43:0202` collection，重新读取并严格验证 CHANGE_HOST feature index 9、current index 1、HOSTS_INFO feature index 10、两个 descriptor slot 和名称 `LAZY-WINDOWS`/`lazy的Mac Mini`。任何序列号、feature index、当前 slot、target slot、配对状态或名称不匹配都在写入前退出。

写入路径使用一次性 guard 文件，只调用一次已验证 CHANGE_HOST feature index 9 的 function `0x10`、目标参数固定 0；失败也不重试，且不自动回切。no_reply 写入只记录 report 提交，Windows 光标可用性以用户实际观察为准。目标解锁和 Easy-Switch 物理回退可用性由协调者确认，代码不从 TCP/Deskflow 状态推断。

本轮 worker 只运行 fake transport，未向实际鼠标发送任何数据包。21 项 fake/CLI 测试覆盖默认无 HID IO、dry-run、合法 apply 只写一次、目标名必须显式提供、当前 slot 误匹配、目标不可用、guard 阻止重复尝试、授权缺失、发送失败不重试、错误序列号/重复 collection 等；输出见 [m585-single-switch-offline-tests.txt](../evidence/mouse/m585-single-switch-offline-tests.txt)。正向 Mac→Windows 授权已被协调者消费，该脚本未经新的单独授权不得再执行 apply。

### 5.7 Windows 协议 probe 修正与离线验证（2026-11-19）

新增 [windows_hid_protocol_probe.ps1](../scripts/windows_hid_protocol_probe.ps1) 与 [run_windows_hid_protocol_probe.sh](../scripts/run_windows_hid_protocol_probe.sh)。默认入口只做 metadata 枚举并输出 `HidOutputReportSent=false`；显式入口只有：

- `mouse-readonly`：唯一选择 Windows 视图的 `046D:B01B` vendor collection，预期 usage `FF43:0202`。读取白名单为 Root GetFeature `0x1814`、CHANGE_HOST function `0x00`、Root GetFeature `0x1815`、HOSTS_INFO state/descriptor/name 只读函数；要求 current slot 0、slot 0 名 `LAZY-WINDOWS`、slot 1 名 `lazy的Mac Mini`。
- `k94-via-version`：唯一选择 `36B0:3002` MI_01、usage `FF60:0061`、input/output 均 33 bytes，只发送 report ID 0 + VIA command `0x01` Get Protocol Version，2 秒限时后取消。

两个入口均不提供任意 frame 参数。数据句柄使用 GENERIC_READ|GENERIC_WRITE、FILE_SHARE_READ|FILE_SHARE_WRITE、OPEN_EXISTING=3 与 FILE_FLAG_OVERLAPPED。Input 与 Output report length 分别来自 native HIDP_CAPS，写入使用 output caps，读取使用 input caps；fake 成功用 input=20、output=22 验证，短读用 input=31、output=33 验证，避免把 output 长度套到读端。

Windows overlapped I/O 已按 pending 生命周期重写：每次操作独立分配 native buffer 与清零 OVERLAPPED，创建手动重置事件，显式写入 hEvent，并持有 device/event SafeHandle。CancelIoEx 传入确切的 OVERLAPPED 指针；初始等待有 2 秒期限，取消后的 completion 等待上限 1 秒。ERROR_NOT_FOUND 按已完成竞态处理，先设置事件再取结果。未确认完成的操作进入进程级 static 保留列表，持有指针和 SafeHandle 引用，绝不调用释放；每次 SSH probe 都是独立 PowerShell 进程，进程退出是隔离边界。确认完成的 read 先复制 buffer 再释放。证据输出分别记录 write/read 的 initial/wait/cancel/GetOverlappedResult/final native error 与真实 elapsed/cancel wait。

HID++ 请求 byte 3 固定带实际 SWID 0x01：Root/state 为 0x01，HOSTS_INFO descriptor 为 0x11，读名为 0x31。构造器只接受 Root 0x1814/0x1815、feature 9 status、feature 10 state/descriptor/name 的固定参数形状，feature 9 function 0x10 会被拒绝。响应必须严格回显 feature index 和含 SWID 的 byte 3；HID++ 错误帧转成明确错误码。执行前还校验 host count/current slot、HOSTS_INFO capability bit、两个 slot 的 paired/status/name length/max length 与 UTF-8 名称。

K94 请求只保留 report ID 00、VIA command 01 和全零 tail，不再预填 00 0C。选择条件同时要求 DeviceInstanceId 为 MI_01、usage FF60:0061、input/output caps 均为 33。回复 matcher 已核对 Web Hub 可接受前缀：01...、00 01...、AA 01...、AA ?? 01... 与 ?? AA 01...，并要求版本 0.000C；测试响应是独立 fixture，echo（版本为 0）会被拒绝。单纯 timeout 仍只表示接收器路径未完成该请求，不作为键盘端证据。

验证结果：

- Windows PowerShell 5.1 Add-Type 编译成功；15 项内置可控 transport 测试通过，覆盖默认无请求、精确 MI_01 选择、短读、成功路径、不同 input/output caps、有界取消、ERROR_NOT_FOUND 完成竞态、未确认操作不释放、HID++/K94 匹配、回切前完整 preflight。证据：[windows-hid-protocol-probe-offline-tests.json](../evidence/windows/windows-hid-protocol-probe-offline-tests.json)。
- Windows 静态审计当前为 25 项：[windows-hid-protocol-probe-static-tests.txt](../evidence/windows/windows-hid-protocol-probe-static-tests.txt)、[test_windows_hid_protocol_probe_static.py](../evidence/windows/test_windows_hid_protocol_probe_static.py)。
- 默认 metadata-only 运行未发送任何 HID output report；K94 接收器 7 个 collection 可见，唯一 raw collection 为 MI_01 FF60:0061 且 input/output 均 33 bytes，M585/M590 vendor collection 不存在，与鼠标仍在 Mac BLE 一致。证据：[windows-protocol-probe-default-metadata.json](../evidence/windows/windows-protocol-probe-default-metadata.json)。

旧 K94 负对照在键盘仍以 USB 连接 Mac 时由早期实现执行：请求为 0001000C...，不是当前同形请求；WriteFile 2000 ms 未完成，CancelIoEx 后 NativeError 995、BytesWritten 0，且旧证据的 ElapsedMilliseconds=0 不能反映真实耗时。该原始 JSON 保留不改，但只作为早期实现历史，不作为键盘端证据或当前负对照结论。说明见 [k94-receiver-via-negative-control.early-implementation-note.txt](../evidence/windows/k94-receiver-via-negative-control.early-implementation-note.txt) 与 [windows-hid-protocol-probe-summary.txt](../evidence/windows/windows-hid-protocol-probe-summary.txt)。

### 5.8 M585/M590 双向硬件闭环（2026-11-19）

Windows probe 新增固定 mouse-switch-mac-once 入口。它先执行与只读模式完全相同的 9 个 HID++ 查询并校验 feature index、current slot 0、HOSTS_INFO capability、两个 slot 的 paired/name/max length 与 UTF-8 名称；全部通过后才构造唯一允许的 CHANGE_HOST feature 9 function 0x10 + SWID 1、目标 slot 1 请求 11FF091101...。该请求由独立 builder 生成，feature index 不是 9 会拒绝，入口没有任意 frame 参数。写入是 no-reply 单次提交，不重试、不自动回切，并记录 native 各阶段错误、完成字节数与耗时。

Mac 侧新增 [m585_switch_to_windows_once.sh](../scripts/m585_switch_to_windows_once.sh) 日常入口。调用者必须提供新的 path-safe attempt ID；包装器只填充既有一次性实验脚本的精确目标名和两个安全确认，并为该 attempt ID 创建独立 guard 与日志。底层仍要求 current slot 1、feature 9/10、paired 状态和两个 host 名称全部匹配，然后单次提交 slot 0。

实测顺序：

1. Mac 只读确认 current slot 1。
2. roundtrip-20261119 一次性 Mac→Windows 提交 20/20 bytes。
3. Windows 只读确认 current slot 0 和两个 host 名称。
4. Windows→Mac 固定入口提交 20/20 bytes，WriteFinalNativeError 0。
5. Mac 只读确认 current slot 1；随后 Windows metadata-only 枚举不再出现 M585/M590 vendor collection。

证据：[m585-mac-before-round-trip.json](../evidence/mouse/m585-mac-before-round-trip.json)、[m585-mac-to-windows-roundtrip.json](../evidence/mouse/m585-mac-to-windows-roundtrip.json)、[m585-windows-before-return-switch.json](../evidence/windows/m585-windows-before-return-switch.json)、[m585-windows-to-mac-roundtrip.json](../evidence/windows/m585-windows-to-mac-roundtrip.json)、[m585-mac-after-round-trip.json](../evidence/mouse/m585-mac-after-round-trip.json)、[windows-protocol-probe-after-return-metadata.json](../evidence/windows/windows-protocol-probe-after-return-metadata.json)、[m585-bidirectional-roundtrip-summary.txt](../evidence/mouse/m585-bidirectional-roundtrip-summary.txt)。

[事实，运行时已验证] M585/M590 的双向硬件通道闭环已经通过：Mac slot 1 到 Windows slot 0，再从 Windows slot 0 回到 Mac slot 1。两次切换各提交一次、各 20 bytes、无重试。目标屏幕上的光标可用性仍以用户观察为准；Mac 正向曾有用户确认，本次闭环以两端 current slot 只读复核证明通道落点。

后续一步到位路线与阶段边界见 [custom-cross-input-roadmap.md](custom-cross-input-roadmap.md)。自动边缘检测、键盘跟随、剪贴板和 GUI 尚未实现，不能把本次手动闭环扩大解释为完整桌面替代方案。

### 5.9 自动贴边切换离线实现（2026-11-19）

新增 [m585_edge_controller.py](../scripts/m585_edge_controller.py)。Mac 端使用 listen-only CGEventTap 监听 mouse moved/dragged，不修改或消费输入事件；用 CGGetActiveDisplayList/CGDisplayBounds 读取实际显示 frame，默认取最左 display 的 x 边界，不写死 1440/1920/3840。触发条件包含 400 ms 贴边驻留、2500 ms 冷却、非拖拽、无鼠标按键、无修饰键、进程锁、Mac 只读 current slot 1，以及 Windows peer 离线健康检查通过。每次自动尝试生成独立 UUID、JSONL attempt 记录和恢复入口；watch 模式提供只读 slot 证据驱动的 JSON health endpoint，Windows 只有看到 ready=true、mouse_current_slot=1、state=READY_MAC 才可发起回切。

Windows probe 新增固定 mouse-edge-watch、mouse-edge-dry-run、mouse-return-hotkey 入口。右边界来自 live SM_XVIRTUALSCREEN/SM_CXVIRTUALSCREEN，同样有驻留、冷却、按键/修饰键抑制、输入桌面可访问性检查、Mac health、current slot 0 完整 preflight 和单次提交。Ctrl+Alt+Shift+M 是显式回 Mac 热键。UAC/登录桌面只允许 SESSION_UNAVAILABLE/RECOVERY_REQUIRED，不宣称自动支持。

2026-11-19 复核后修正 Mac 竞态：冷却从固定入口实际完成时的当前 monotonic 时间起算，且每次触发后必须先离开左边缘才能重新武装；慢 HID preflight/submit 后持续陈旧贴边事件不会产生第二次 CHANGE_HOST。提交后不再把 slot1 查询直接当作回连成功，而是区分 device-absent、query-failed、wrong-slot 与 present-slot-1。独立 1 秒只读状态轮询不写 HID；成功切换需先观察到设备消失，再在 5 秒稳定窗口后连续两次读到 slot1 才恢复 READY_MAC。设备一直未离开、连续查询失败、目标不可用或提交失败进入显式恢复语义，不因后续一次 slot1 查询自动恢复。Health ready 同时要求 controller running、READY_MAC 和最新 slot1 证据。

离线与只读验证结果：

- Mac 环境检查通过：Accessibility true、listen-only event tap 可创建、当前显示 frame 1440x900、左边界 x=0、唯一鼠标 vendor collection/serial 正确。
- Windows test-only 15/15 仅作为离线编译/transport 证据；Mac peer 检查已改用 peer-health，不再把 test-only 当目标健康。
- Mac edge 单元测试 18/18 通过，覆盖慢提交后的持续陈旧贴边、提交完成时间冷却、必须离开边缘才能重武装、设备消失/查询失败/目标不可用区分、两次 slot1 回连确认、Windows peer health 版本/时效/目标与回切 ready 区分、native argtypes/restype、实际 frame、dry-run、固定入口路径、进程锁、health readiness 和显式退出/手动入口。
- Mac 三个 M585 测试模块合计 39/39 通过。
- Windows 编译与 15 项可控 transport 测试、27 项静态审计通过；脚本内置可直接在交互 PowerShell 前台调用的 -WindowsEdgeWatch/-WindowsEdgeDryRun/-WindowsReturnHotKey/-WindowsPeerHealth 参数。
- Mac 3 秒 dry-run 成功启动 listen-only tap，未做 HID++ 输出或 peer 命令。
- Windows 3 秒 SSH dry-run 正确报 SESSION_UNAVAILABLE，未做 HID++ 输出；这是非交互 SSH 边界，证明 fail-closed，不代表用户桌面会失败。

证据：[m585-edge-controller-tests.txt](../evidence/mouse/m585-edge-controller-tests.txt)、[m585-mac-edge-environment-with-windows-peer.json](../evidence/mouse/m585-mac-edge-environment-with-windows-peer.json)、[m585-mac-edge-dry-run.jsonl](../evidence/mouse/m585-mac-edge-dry-run.jsonl)、[m585-windows-edge-dry-run.jsonl](../evidence/windows/m585-windows-edge-dry-run.jsonl)、[m585-automatic-edge-offline-summary.txt](../evidence/mouse/m585-automatic-edge-offline-summary.txt)。

[边界] 自动 watch/hotkey 进程未安装、未启用、未遗留运行；Deskflow 未停止或重配置；本阶段未执行任何自动硬件切换。50 次双向、防乒乓、两端实际点击、睡眠恢复和网络异常的验收标准已固定在 [custom-cross-input-roadmap.md](custom-cross-input-roadmap.md)，需协调者审核后再安排监督实测。
只读进程复核仍看到 Mac Deskflow server 与 Windows Deskflow daemon/GUI/core。后续监督实测前必须先由协调者审核并明确暂停 Deskflow，禁止两套边缘切换同时消费输入。

### 5.10 监督实测准备修正（2026-11-20）

Windows 新增固定 peer-health 只读入口，输出 schema/controller_ready/ready、desktop 状态、鼠标 present/current slot/slot evidence、UTC 生成与过期时间、hid_output_report_sent=false。该入口优先读取交互桌面 watch 进程每秒原子更新的 TEMP health 文件；没有新鲜文件时退回当前进程只读探测。ready 只在交互桌面、鼠标存在且完整 preflight 证明 slot 0 时为 true；controller_ready 单独表示交互控制器可接收下一跳，避免鼠标尚在 Mac 时把回切 ready 伪装成目标可用。Mac peer 检查要求 peer-health v1、15 秒 freshness（允许 2 秒时钟偏差）、controller_ready、desktop available 且无 HID 写。

单一 Windows watch 进程同时注册 Ctrl+Alt+Shift+M（显式回 Mac）与 Ctrl+Alt+Shift+X（一键停止），用 PeekMessage 与 50ms 边缘轮询共存，不需要第二个热键窗口。停止时会删除 health 文件；异常退出后文件 15 秒自然过期。

新增 [deploy_windows_m585_edge_launcher.sh](../scripts/deploy_windows_m585_edge_launcher.sh) 只把 probe 和 [windows_m585_edge_launcher.cmd](../scripts/windows_m585_edge_launcher.cmd) 复制到 Windows 用户 TEMP，不执行、不安装、不提权。启动器打开可见 PowerShell 窗口，固定 Mac 地址 192.168.1.4:8787、写 TEMP JSONL 日志、支持 dry-run 参数，并显示 M/X 热键与停止方式。Mac watch 输出 Ctrl+C 退出和手动 Mac→Windows 单次入口；health 端口绑定失败输出 JSON 错误。

当前真实只读 peer-health 经 SSH 返回 controller_ready=false、ready=false、desktop=SESSION_UNAVAILABLE、mouse present=false，符合鼠标在 Mac 且 SSH Session 0 不可访问输入桌面的 fail-closed 预期；证据见 [m585-windows-peer-health-current.json](../evidence/windows/m585-windows-peer-health-current.json) 和 [m585-mac-edge-environment-with-windows-peer.json](../evidence/mouse/m585-mac-edge-environment-with-windows-peer.json)。

### 5.11 可见启动器红字与交互任务验证（2026-11-20）

用户本地可见启动器的 cmd PID 39068 与 powershell PID 12976 均在 SessionId 1，命令为 -WindowsEdgeWatch 管道 Tee-Object；但 JSONL 与 health 文件均不存在，证明失败发生在首个 controller Emit 之前，Tee-Object 因没有收到输出而未创建文件。协调者桌面捕获确认 RegisterHotKey Ctrl+Alt+Shift+M 失败 1459。

修正后新增 [windows_m585_edge_bootstrap.ps1](../scripts/windows_m585_edge_bootstrap.ps1) supervisor：先创建/append JSONL，再调用 probe；bootstrap-start/error/stopped 与退出码直接写文件，红色错误同时显示，probe 在 Add-Type 前写入 CONTROLLER_STARTING health，Add-Type/runtime 异常分别写 ERROR_ADD_TYPE/ERROR_RUNTIME 并返回 2/3。故意损坏 C# 的 Windows 实测产生 ERROR_ADD_TYPE health 和退出码 2。单一 watch 保留 Ctrl+Alt+Shift+M/X，并把 PeekMessage 修正为 Unicode PeekMessageW。

真实根因是 SSH Session 0 没有交互 window station。用 Scheduled Task LogonType Interactive 的当前 Administrator principal 实测：Session 1、UserInteractive=true、OpenInputDesktop=true、RegisterHotKey(IntPtr.Zero)=true；再以临时任务启动 dry-run controller，实测 PID 41200、Session 1、任务 State 4/Running、health desktop.available=true、JSONL 启动记录存在、controller_ready=false 且无 HID 输出。新增可回退 [start_windows_m585_edge_from_ssh.sh](../scripts/start_windows_m585_edge_from_ssh.sh)，操作 register-start/status/stop/remove，任务名 MiniOpsM585EdgeWatch；这不是服务或登录自启动。

证据：[m585-windows-scheduled-dry-run-live.json](../evidence/windows/m585-windows-scheduled-dry-run-live.json)、[m585-windows-interactive-desktop-probe.json](../evidence/windows/m585-windows-interactive-desktop-probe.json)、[m585-windows-watch-add-type-error-health.json](../evidence/windows/m585-windows-watch-add-type-error-health.json)、[m585-windows-supervised-launch-diagnosis.txt](../evidence/windows/m585-windows-supervised-launch-diagnosis.txt)。

收尾时 lazy-windows-ts 与 192.168.1.8 停止响应，未尝试 WOL；MiniOpsM585SupervisedDryRun 已由测试脚本移除，早期 MiniOpsInteractiveDesktopProbe 的清理命令未能复查，需在线后再查询/移除。Deskflow 一直未停止，也未执行鼠标切换。

### 5.12 正式 watch JSONL 缺失诊断（2026-11-20）

3090 在线后的正式 Interactive watch 实测为 Task State 4、bootstrap PID 43388、SessionId 1，health 每秒更新且 controller_ready=true；鼠标未在 Windows slot 0 时 ready=false、mouse.present=false。旧 JSONL 只有 bootstrap-starting 的根因是 C# Emit 使用 Console.Out.WriteLine，直接写控制台而不进入 PowerShell pipeline，旧 bootstrap 的 ForEach-Object 无法捕获；watch 本身未卡死。临时 dry-run 报 RegisterHotKey 1409，进一步证明正式 watch 已占用 M/X 热键。

修正后的 bootstrap 以独立 cmd/PowerShell 子进程运行 probe，将 stdout/stderr 重定向到临时文件，父进程实时 tail 并 append 主 JSONL、镜像显示、保留退出码。fake probe 集成测试捕获 direct Console.Out、Console.Error 和退出码 5；真实 probe 在正式 watch 占用热键时产生的 1409 runtime error 也被新 supervisor 捕获。正式 watch 仍在旧 bootstrap 进程内，需协调者审核后 stop/restart 才能加载修正。当前本工作区未发现 Mac watch 进程或 8787 health 响应，需重启/复核后再继续正向实测。

证据：[m585-windows-current-watch-status.json](../evidence/windows/m585-windows-current-watch-status.json)、[m585-windows-current-watch-peer-health.json](../evidence/windows/m585-windows-current-watch-peer-health.json)、[m585-windows-bootstrap-console-capture.jsonl](../evidence/windows/m585-windows-bootstrap-console-capture.jsonl)、[m585-windows-fixed-bootstrap-interactive-dry-run.json](../evidence/windows/m585-windows-fixed-bootstrap-interactive-dry-run.json)、[m585-windows-watch-jsonl-diagnosis.txt](../evidence/windows/m585-windows-watch-jsonl-diagnosis.txt)。

### 5.13 Mac 启动期 RECOVERY 受控恢复（2026-11-20）

复核协调者的 CGEvent 回调修正后，发现初版按键字段 100..102 实为 macOS SDK 的 scroll 字段；现已改为 drag 事件类型、公开 kCGMouseEventPressure 字段 2 与低 8 位 mouse-button flags，并把 modifier mask 与鼠标低位拆开，移除 CGEventSourceButtonState 声明/调用。RECOVERY_REQUIRED 记录进入时间，只在 listen-only event tap 已运行、连续两次只读 slot1 且 5 秒稳定窗后恢复 READY_MAC；query failure 或 wrong slot 会清零确认计数，恢复后仍需离开左边缘才可重新触发。

验证：Mac edge 21/21、三个 Mac 测试模块合计 42/42；只读环境检查 Accessibility/event tap/唯一鼠标 collection 通过。当前旧 watch health 为 RECOVERY_REQUIRED、controller_running=true、query_failure_count=9，stderr 为 M585/M590 is not connected；新分类将其归为 device-absent，另一次真实查询发生 hidapi short write(-1/20)，均未发送 HID 写，新状态机针对这些启动瞬断自动恢复。证据见 [m585-mac-current-health-before-restart.json](../evidence/mouse/m585-mac-current-health-before-restart.json)、[m585-mac-recovery-fix-summary.txt](../evidence/mouse/m585-mac-recovery-fix-summary.txt)。

Web Hub 路由审计见 [webhub-k94-receiver-qmk-routing.txt](../evidence/windows/webhub-k94-receiver-qmk-routing.txt)：Hub 将 `0x3002` 识别为 dongle，对 dongle 建立 deviceMode 2，经 `FF60/0061` 发送 VIA command `0x01`；D0 通知使用 status=4、keyboardNum>=1 和设备 VID/PID 判断 rfQMK。该代码证明 Hub 的候选路径，但响应可能由接收器或键盘生成，静态源码不足以区分实际响应者。

协调者后续只读触发命令：

~~~sh
scripts/run_windows_hid_protocol_probe.sh mouse-readonly \
  > evidence/windows/m585-windows-readonly-protocol.json \
  2> evidence/windows/m585-windows-readonly-protocol.stderr
~~~

前置条件是用户已把 M585/M590 切到 Windows slot 0、Windows 已解锁，且默认 metadata 枚举能看到唯一 vendor collection。该命令仍不发送 CHANGE_HOST function 0x10；固定回切入口见上一节，执行前同样要求 current slot 0、slot 0/1 名称映射、Mac 可重新连线、用户手边有 Easy-Switch 物理回退。

K94 2.4G 正对照由协调者安排，不在本轮自动切换设备。前置条件是 K94 脱离 Mac USB 并处于 2.4G/接收器在线状态，然后执行：

~~~sh
scripts/run_windows_hid_protocol_probe.sh k94-via-version \
  > evidence/windows/k94-receiver-via-positive-control.json \
  2> evidence/windows/k94-receiver-via-positive-control.stderr
~~~

若返回 VIA 0.0C，只能说明接收器路径有响应；响应者可能是接收器固件，也可能是 K94 键盘，仍不能仅凭该响应证明 BLE 通道可切换。若再次超时，应记录 write/read 各阶段 NativeError、完成字节数与真实时间，不能否定 2.4G 在线连接本身。

#### 当前可行的双向控制路线排序

| 路线 | Mac → Windows | Windows → Mac | 结论 |
| --- | --- | --- | --- |
| M585/M590 CHANGE_HOST | 已实测：Mac slot 1 发送 slot 0，用户看到 Windows 硬件通道光标 | 已实测：Windows slot 0 发送 slot 1 后 Mac 复核 current slot 1 | **最有证据的物理通道路线**；双向硬件闭环通过，自动化与输入体验未验收 |
| K94 USB 固定连接 | USB raw 可达，但 stock BLE handler 要求 BLE source mode | USB 只提供单一有线主机，不存在跨主机回切 | 当前补丁 fail-closed，非双向方案 |
| K94 BLE 直连 | BLE handler source mode 可行，但 BLE HID 无 raw collection | Windows BLE 侧同样缺少 raw 控制证据 | 控制通道缺失 |
| K94 2.4G 接收器 | Windows 已实测枚举 MI_01 FF60:0061 raw collection，33-byte input/output；早期实现的 VIA 0x01 写入超时且请求非同形 | 需要 K94 处于 2.4G 在线状态的同形正对照，且仍不能仅凭响应证明 BLE 可切换 | 有主机侧候选控制口，仍未成为方案 |

[结论] 现阶段唯一已有设备级双向映射和公开控制特性的是 M585/M590 D1。K94 仍缺“同时可达且可执行”的控制通道；接收器 vendor collection 或 QMK VIA 配置本身不能补足这个结论。

## 6. 事实 / 推断 / 未知汇总

[事实]

- K94 官方源码 HEAD、工厂 BIN、VIA JSON、闭源库和构建依赖已落地并哈希记录。
- K94 公开源码 raw HID 是标准 VIA，usage 0xFF60/0x61。
- K94 Web Hub 只把 MD_* 暴露为键码，没有主机切通道 API。
- K94 闭源库的 BLE1/BLE2/BLE3/USB 按键路径分别调用 SPI 命令 1/2/3/8。
- K94 当前 BLE 枚举没有 raw collection；用户拨到 Wired 后，USB raw collection 0xFF60/0x61 和 VIA 0.0C 响应已实测存在。
- K94 未修改固件在本地可复现编译，但 rebuilt BIN 不等于工厂 BIN。
- K94 阶段 C 补丁可独立应用、干净编译并通过 host mock；生产调用边界为成对 press/release 进入 process_record_user()，USB raw 与 stock BLE handler 的模式互斥已由静态与运行时证据固定。
- M585/M590 本机 BLE descriptor 有 HID++ vendor report 0xFF43/0x0202/0x11。
- Solaar 同型号转储和实现明确支持 CHANGE_HOST 0x1814。
- M585/M590 本机只读 HID++ 查询成功：CHANGE_HOST feature index 9、host count 2、current slot 1；HOSTS_INFO feature index 10 且 slot 0=LAZY-WINDOWS、slot 1=lazy的Mac Mini。
- 协调者已执行一次用户授权的 CHANGE_HOST function 0x10：20/20 bytes 提交一次，Mac BLE 06:44:27.719 断链，用户看到 Windows 硬件通道光标，后续只读复查 current index 回到 1。
- 本轮完成 M585/M590 双向闭环：Mac current slot 1 时单次切到 slot 0；Windows current slot 0 时单次切回 slot 1；最终 Mac 只读复核 current slot 1。两次写入各 20/20 bytes、无重试。
- 自动贴边离线实现完成：Mac listen-only CGEventTap、实际 display frame、驻留/提交完成冷却/交互抑制/离开边缘重武装、独立只读状态轮询、进程锁、slot 证据、peer health 与 JSONL 记录已实现；Windows live virtual screen、同样防抖与 fail-closed 状态、peer health 与单一 watch 双热键已实现。Mac 18 项 edge 单元测试与 Windows 27 项静态审计通过。
- 一次性 M585 实验脚本 21 项 fake/CLI 测试通过；Windows HID 只读查询脚本 12 项静态审计通过。本轮 worker 未向实际鼠标发送数据包。
- Windows 只读 PnP 与 metadata-only HID 查询成功：K94 接收器 MI_01 为 FF60:0061，input/output report length 均 33 bytes；MI_02 COL05 为 FF00:0001，input/output 均 64 bytes。
- 更正：前一条“未发送数据包”仅限定 5.6 的离线准备阶段；5.8 已完成实际双向闭环。
- Windows 协议 probe 在 PowerShell 5.1 编译并通过 15 项内置可控 transport 测试与 27 项 Mac 静态审计；默认 metadata-only 实测未发送 HID output report，唯一 K94 raw collection 为 MI_01、FF60:0061、input/output 33 bytes。
- K94 位于 Mac USB 时，早期实现对接收器 MI_01 的一次 VIA 0x01 写入在 2000 ms 未完成，CancelIoEx 后 NativeError 995、BytesWritten 0、无响应；该请求预填 00 0C 且旧 elapsed 为 0，已降级为早期实现历史。

[推断]

- K94 原厂固件无现成主机切通道 API；当前窄补丁只是 fail-closed 离线 proof，尚未解决控制通道可达性。
- Web Hub 的 MD_* 是写入键位让用户按键触发，不是主机直接切换。
- M585/M590 的双向硬件通道已经可用；自动贴边已具备监督实测条件，但 50 次验收、实际输入体验、键盘跟随、剪贴板和稳定 GUI 仍未完成。

[未知]

- K94 无线模块切换 ACK、连接状态和失败行为。
- K94 处于 2.4G 在线状态时接收器 FF60:0061 collection 能否完成同形 VIA 0x01 正对照、响应由谁生成，以及 source mode 1/2 下的安全切换路径。
- K94 当前 PCB revision 与工厂参考 BIN 是否匹配。
- FS026 custom bootloader 的官方刷写/恢复流程。
- M585/M590 连续自动切换时的防抖窗口、目标屏幕输入确认方式和快速 Deskflow 屏幕跳动的准确事件归因。
- 自动贴边在真实用户桌面、多显示器/DPI 变化、Windows 睡眠恢复和 Deskflow 并行运行时的行为。

## 7. 本轮产物

- 状态报告：[docs/custom-flow-status.md](custom-flow-status.md)。
- 阶段 C 协议与验证：[docs/k94-stage-c-protocol.md](k94-stage-c-protocol.md)。
- K94 只读 probe：[scripts/k94_readonly_probe.py](../scripts/k94_readonly_probe.py)。
- M585/M590 只读 probe：[scripts/m585_readonly_probe.py](../scripts/m585_readonly_probe.py)。
- M585/M590 一次性实验脚本：[scripts/m585_single_switch_experiment.py](../scripts/m585_single_switch_experiment.py)。
- M585/M590 Mac→Windows 日常入口：[scripts/m585_switch_to_windows_once.sh](../scripts/m585_switch_to_windows_once.sh)。
- M585/M590 Mac 自动贴边 controller：[scripts/m585_edge_controller.py](../scripts/m585_edge_controller.py)。
- 自研跨屏完整路线：[docs/custom-cross-input-roadmap.md](custom-cross-input-roadmap.md)。
- Windows HID 只读查询脚本：[scripts/windows_hid_readonly_query.ps1](../scripts/windows_hid_readonly_query.ps1)。
- K94 阶段 C 验证摘要：[verification-summary.txt](../evidence/k94/stage-c/verification-summary.txt)。
- M585/M590 验证摘要：[m585-verification-summary.txt](../evidence/mouse/m585-verification-summary.txt)。
- M585/M590 首次正向切换摘要：[m585-first-switch-summary.txt](../evidence/mouse/m585-first-switch-summary.txt)。
- M585/M590 双向闭环摘要：[m585-bidirectional-roundtrip-summary.txt](../evidence/mouse/m585-bidirectional-roundtrip-summary.txt)。
- 自动贴边离线摘要：[m585-automatic-edge-offline-summary.txt](../evidence/mouse/m585-automatic-edge-offline-summary.txt)。
- Windows HID 查询静态摘要：[windows-hid-query-static-summary.txt](../evidence/windows/windows-hid-query-static-summary.txt)。
- Windows PnP 只读 baseline：[windows-pnp-readonly-baseline.json](../evidence/windows/windows-pnp-readonly-baseline.json)。
- Windows HID metadata-only 实测：[windows-hid-readonly-query.json](../evidence/windows/windows-hid-readonly-query.json)。
- Windows 协议 probe：[windows_hid_protocol_probe.ps1](../scripts/windows_hid_protocol_probe.ps1)。
- Windows 协议 probe SSH 入口：[run_windows_hid_protocol_probe.sh](../scripts/run_windows_hid_protocol_probe.sh)。
- Windows 可见 TEMP 启动器：[windows_m585_edge_launcher.cmd](../scripts/windows_m585_edge_launcher.cmd)。
- Windows supervisor bootstrap：[windows_m585_edge_bootstrap.ps1](../scripts/windows_m585_edge_bootstrap.ps1)。
- Windows Interactive task controller：[windows_m585_edge_task_controller.ps1](../scripts/windows_m585_edge_task_controller.ps1)。
- Windows SSH task 入口：[start_windows_m585_edge_from_ssh.sh](../scripts/start_windows_m585_edge_from_ssh.sh)。
- Windows TEMP 只复制部署脚本：[deploy_windows_m585_edge_launcher.sh](../scripts/deploy_windows_m585_edge_launcher.sh)。
- Windows 协议 probe 汇总：[windows-hid-protocol-probe-summary.txt](../evidence/windows/windows-hid-protocol-probe-summary.txt)。
- 当前 Windows peer-health 只读结果：[m585-windows-peer-health-current.json](../evidence/windows/m585-windows-peer-health-current.json)。
- Windows supervised launch 诊断：[m585-windows-supervised-launch-diagnosis.txt](../evidence/windows/m585-windows-supervised-launch-diagnosis.txt)。
- 旧 K94 负对照降级说明：[k94-receiver-via-negative-control.early-implementation-note.txt](../evidence/windows/k94-receiver-via-negative-control.early-implementation-note.txt)。
- Web Hub 接收器 QMK 路由审计：[webhub-k94-receiver-qmk-routing.txt](../evidence/windows/webhub-k94-receiver-qmk-routing.txt)。
- K94 证据：[evidence/k94](../evidence/k94)。
- 鼠标证据：[evidence/mouse](../evidence/mouse)。
- 汇总哈希：[evidence/SHA256SUMS](../evidence/SHA256SUMS)。

## 8. 偏差与纠正记录

1. QMK 编译和 qmk clean 的默认规则会把输出 BIN 复制到源码仓库根部，覆盖本地克隆里的工厂参考 BIN 两次；每次都立即执行 git restore 8r101_k94_via.bin，最终 git status 干净，官方 BIN 哈希恢复为 ffd342...1292。编译产物另存于 evidence/k94/build/。
2. 尝试 brew install --cask gcc-arm-embedded 时安装阶段因无 sudo 终端失败；未系统安装。随后改为在项目研究目录下载并校验官方 PKG 后解出工具链。Homebrew 自身执行了自动更新。
3. research/k94/toolchain-pkg/ 保留约 1 GB 级下载/解包材料，用于后续复现编译；未改系统工具链。
4. 初版 M585/M590 probe 使用 hidapi 默认 Darwin 打开方式并在 open 阶段失败；已按 Solaar 证据改为非独占打开，并加入严格响应匹配与离线 fail-closed 测试。默认 probe 仍只读；唯一一次切 host 写入由协调者在后续单独授权下执行。
5. 阶段 C 独立克隆中的 QMK 构建同样把输出 BIN 复制到仓库根部；已在保存产物后恢复该克隆的工厂参考 BIN。官方研究克隆保持 clean。
