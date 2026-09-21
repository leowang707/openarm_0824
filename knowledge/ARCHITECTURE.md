# OpenArm 馬達控制架構與品牌化重構規格

**版本：2026-09-18｜適用專案：`leowang707/openarm_0824`**

本文件分開描述「本次交付的程式」、「保留的既有功能」與「未來工作」。
品牌分類不是新增一套 CAN 協定，也不代表完成硬體驗收。

## 1. 基準與適用範圍

本次查詢遠端 `feature/lande-pa043`，HEAD 為：

```text
4d3c279e5cd96f24902adac42996d9b08adac2ab
feat: add DM-J8009P and expand DaMiao control modes
```

使用者提供的本機紀錄另包含 A2 文件 commit `7072776`，以及 B 階段的
`BusProfile / AdapterCapabilities` 修改與離線檢查結果。不能僅憑遠端狀態
推定本機是否已 commit B；下週開始仍以本機 `git status` / `git log` 為準。

重構包辨識三種已知檔案內容：遠端 4d3c279、加上 A2、加上 A2+B。
所有待修改檔案先比對內容雜湊；不認識的版本全部停止，不會嘗試強制覆蓋。
支援 CRLF/LF 正規化，但不忽略其他內容差異。

## 2. 設計原則

**Motor Brand / Model、Motor Protocol、Bus Profile、Host Backend、Device/Channel**
是五個不同概念：

| 概念 | 說明 | 例子 |
|---|---|---|
| 品牌與型號 | 顯示名稱、SDK preset、型號差異 | DaMiao J6248P、J8009P；LANDA PA043 |
| 馬達協定 | 命令封包、回饋、參數存取規則 | DaMiao Classic；LANDA PA043 |
| Bus Profile | 選定的 CAN frame 類型與 bit timing 描述 | `classic_1m`；停用的 FD candidate |
| Host Backend | 電腦如何存取 CAN 介面 | `slcan`、`usbcan_a`、`gs_usb`、`socketcan` |
| Device/Channel | 這次選到的實體／OS 介面 | COM7、USB device index 0、can0 |

同品牌可以共享協定整合；不同型號仍保留各自 scaling 與模式限制。
相同硬體在不同 OS 也可能有不同存取路徑。

## 3. 目前實際資料流

```text
Browser GUI / existing HTTP API / CLI
                |
                v
          MotorService
     [one selected model / one bus session]
                |
        +-------+-------------------+
        |                           |
        v                           v
  Motor Registry              Adapter Registry
  brand / model               host backend / channel
  SDK preset                  software capabilities
  supported modes             candidate confidence
  bus profile                 OS availability
  protocol binding                  |
        |                           |
        v                           v
  Brand backend             configuration admission
  + DaMiao Classic          no silent FD fallback
  + LANDA PA043                     |
        |                           |
        +----------> ThreadSafeBus <-+
                          |
                host-specific python-can backend
                          |
               external CAN bus / motor
```

**目前一個 MotorService 只綁定一個型號。** 可控制該型號的多個 ID，
但這次沒有新增「同一個 session 混合 PA043、J6248P、J8009」的能力。
要支援混型號共線，後續必須處理唯一 RX owner、回覆分派與 address collision，
不能只把 UI 改成品牌選單就宣稱完成。

## 4. 目錄架構：本次真正建立的檔案

```text
openarm_0824/
├── start_gui.py                        既有入口，不改用法
├── gui_server.py                       既有 HTTP routes / control loop
├── motor_service.py                    profile 驗證、連線、backend delegation
├── can_profiles.py                     中立的 BusProfile dataclass
├── templates/
│   └── custom_gui.html                 品牌 / 型號 / profile / backend / channel
│
├── motors/
│   ├── __init__.py                     載入品牌、匯出相容 API
│   ├── base.py                         MotorBackend contract，保持原檔
│   ├── registry.py                     MotorSpec + 品牌/型號 catalog
│   ├── damiao/
│   │   ├── __init__.py                 註冊型號、保留舊 import
│   │   ├── common.py                   mode 名稱、scan bounds
│   │   ├── models.py                   型號與 SDK preset/reference mapping
│   │   ├── profiles.py                 Classic profile + disabled FD candidate
│   │   └── classic.py                  共用 DaMiao Classic integration
│   └── lande/
│       ├── __init__.py                 品牌註冊、舊 import 相容
│       ├── protocol.py                 原 lande_motor.py，保留封包編碼
│       └── pa043.py                    PA043 MotorBackend / registry
│
├── can_adapters/
│   ├── __init__.py
│   ├── base.py                         AdapterCapabilities / AdapterDevice
│   ├── registry.py                     列舉、解析、open guard、ThreadSafeBus
│   ├── slcan.py                        serial / ASCII SLCAN
│   ├── usbcan_a.py                     serial / Waveshare backend wrapper
│   ├── gs_usb.py                       direct USB
│   └── socketcan.py                    Linux OS CAN stack
│
├── usbcan_a.py                         既有 Waveshare binary driver，不搬動
├── lande_motor.py                      舊 public import 的相容轉接檔
├── lande_probe.py                      既有 CLI，位置與指令保留
├── lande_diag.py                       既有 CLI，位置與指令保留
├── diagnostics/
│   ├── __init__.py
│   └── catalog.py                      無硬體開啟的 catalog；裝置列舉需明確要求
├── tests/
│   ├── refactor_contract_checks.py     isolated mocks / architecture contracts
│   └── refactor_dependency_checks.py   真實已安裝套件 + FakeBus + Flask smoke
├── tools/
│   └── verify_refactor.py              同一 interpreter 執行離線驗證
└── knowledge/
    ├── ARCHITECTURE.md                 本文件
    ├── REFACTOR_RUNBOOK.md             下週操作與驗收
    ├── HARDWARE_OBSERVATIONS.md        實測事實 / 候選解釋 / 未確認項目
    ├── DAMIAO_PROTOCOL_AUDIT.md         更新後的協定邊界
    └── PA043_CAN_PROTOCOL_AUDIT.md      原有文件保留
```

不建立空的 `canfd.py`，避免讓空殼檔案看起來像已完成控制。
不建立 `uart.py` / `damiao_uart_probe.py`。保留 `pyserial` 是因為
SLCAN 與 Waveshare 的 host transport 仍會走 COM，不代表提供馬達 debug UART。

## 5. 各品牌如何共享程式

### 5.1 DaMiao

`classic.py` 保留共用 `_DaMiaoBackend`，實際低階命令仍由既有
`damiao-motor` 套件處理，不再複製另一份 MIT encoder。

`models.py` 保存型號的 identity、preset、模式集合與供測試使用的 mapping reference：

| repo key | SDK preset | 保留模式 | mapping reference: P / V / T |
|---|---|---|---|
| `damiao_6248p` | `6248P` | MIT / POS_VEL / VEL / FORCE_POS | 12.566 / 20 / 120 |
| `damiao_8009p` | `8009` | MIT / POS_VEL / VEL | 12.5 / 45 / 54 |

這些值承接原 repo 與所用 SDK preset。**不是本次實機讀回值，也不是安全運動上限。**
程式不因為表格有參考值就寫入馬達的 PMAX、VMAX、TMAX。

J8009 / J8009P 的完整實物型號尚未由 UART 確認；不自動將 firmware number
映射為 `P` 版，亦不自動放開受測個體的 `Hybrid`。

### 5.2 LANDA

`protocol.py` 是原 `lande_motor.py` 的移動，不改 CAN ID、bit packing、
mapping、參數 read/write 或特殊命令內容。

`pa043.py` 保留掃描、模式切換、服務層介面與 PA043 註冊。
GUI 的 PA043 預設運動鎖與原有 environment gate 保持不變。
原文件中的 high-ID addressing 與 fault/temp 歧義，不在目錄重構時自行猜解。

## 6. 公開介面的相容性

以下 key 保留，不因目錄改名而更換：

```text
damiao_6248p
damiao_8009p
lande_pa043

slcan
usbcan_a
gs_usb
socketcan

classic_1m
canfd_1m_5m
```

舊 import 保留：

```python
from motors.damiao import DaMiao6248PBackend, DaMiao8009PBackend
from motors.lande import LandeBackend
from lande_motor import LandeMotor
from motors import BusProfile
```

`BusProfile` 的 canonical 定義移至 `can_profiles.py`；原路徑重新匯出同一個 class，
不是宣告兩個不同型別。`default_bitrate` getter 與 JSON 欄位保留，舊 caller
仍可不傳 `bus_profile`，使用該型號原來的 Classic default。

既有 HTTP route 名稱、輪盤 ID 與動作控制路徑保留。
`/api/connect` 可接受 `bus_profile`；`/api/capabilities?devices=0`
只回 catalog，不進行裝置列舉。

型號 catalog 額外提供：`brand`、`brand_name`、`family`、`protocol_family`。
GUI 用這些資料分群，不用字串前綴猜品牌。

## 7. Adapter 與 gs_usb / SocketCAN 的關係

保留四個 backend，但補 `backend_kind`：

| key | backend_kind | 此次程式開放能力 |
|---|---|---|
| slcan | serial | Classic CAN |
| usbcan_a | serial | Classic CAN |
| gs_usb | direct_usb | Classic CAN |
| socketcan | os_stack | Classic CAN |

這張表描述**本 repo 的 backend 實作**，不代表 SocketCAN、USB protocol 或
所有相容硬體的最大能力。Linux SocketCAN 本身有 CAN-FD 支援；此包沒有將它開放。[S3]

```text
同一個 gs_usb-compatible 裝置可能有兩條 host 路徑：

user-space Python -> direct gs_usb/USB -> device
Linux Python -> SocketCAN can0 -> kernel driver (possibly gs_usb) -> device
```

本次不自動解除 kernel driver，不在直接 USB 失敗時偷偷切 backend。
也不因為同時看到 `can0` 和一個 USB 裝置，就在沒有 physical identity 證據下
當成同一個裝置。這些功能列入後續 device inventory 工作，不混入本次搬檔。

### 裝置辨識的修正

CH340 裝置保持出現在列表，但標記為 candidate、`auto_selectable=False`。
只有 CH340 時，`auto` 應要求使用者指定 backend/channel，而不是向 USB-TTL
發 Waveshare binary configuration。

`AdapterDevice.capabilities` 是預留的 device-level metadata 欄位；目前沒有
自動硬體能力量測與提升 FD 權限的功能。不能靠填一個 True 就繞過 backend/profile gate。

## 8. CAN profile 的驗證順序

```text
request motor_model + bus_profile
           |
           v
profile 是否存在、格式是否有效？
           |
           v
profile.implemented 是否 True？
           |
           v
profile.protocol_key 是否有對應 motor protocol binding？
           |
           v
backend capabilities 是否允許此 frame 類型？
           |
           v
resolve actual channel -> open backend
           |
           v
scan/request feedback -> 才能驗證馬達是否回應
```

連線前被拒絕的 profile 不應觸發硬體開啟。
直接呼叫 `open_can_bus()` 也有 FD guard，不僅 `MotorService.connect()` 有。
`ThreadSafeBus.send()` 會拒絕在 Classic connection 上送 FD frame、Classic+BRS
或超過八個 payload bytes；不自動降級。

### 5 Mbps 個體的處理

保留 `canfd_1m_5m` 方便承接本機 B，但更正為 `candidate_not_hardware_verified`。
UART 僅印出 `5.00Mbps`；官方 workflow 的 `Motor_Control(1000000, 5000000, ...)`
是候選設定的參考，不直接證明此個體採相同 nominal/data/BRS。[S2]

`implemented=False` 持續生效；就算只把這個 flag 改 True，protocol binding
仍應拒絕讓 Classic backend 冒充 CAN-FD backend。

## 9. 本次有意改變與沒有改變的行為

**有意改變：**

- GUI 增加品牌與 profile 選擇；未實作 profile 顯示但不可選。
- CH340 不再僅憑 VID/PID 被 Auto 當成 Waveshare。
- DaMiao scan 遇到狀態 request 例外，不再 fallback 到 `send_cmd_mit()`。
- 新增低層 FD guard；無效 profile 在新硬體 open 前失敗。
- 連線資訊額外列 `connection_state=adapter_open`，不把開 port 當成馬達已回應。

**刻意不變：**

- 三個既有馬達 key、控制模式範圍、CAN 編碼與原有入口。
- 原有 DaMiao dependency、PA043 mapping 與 GUI motion policy。
- GUI control loop 的既有頻率、目標生成、Enable/Disable 調用方式。
- 掃描範圍：DaMiao 1–15；PA043 GUI 0–16。

`disconnect()` 原有 disable/cleanup 行為也保留；因此 `scan()` 不送運動 fallback
不等於整個 connect/disconnect 生命週期是純被動監聽。

## 10. 不該被「架構測試 PASS」掩蓋的既有問題

以下未在此包宣稱解決，應獨立排程：

| 優先 | 項目 | 原因／完成條件 |
|---|---|---|
| P0 | 真正收到 feedback 才確認 enable/state | 現有 GUI tracks 主要記錄發送意圖，不是硬體 ACK |
| P0 | dependency 的 auto-enable / auto-clear 行為 | 本包只移除 scan fallback，正常 command API 仍需單獨審核 |
| P0 | FW6417/004 的 wire protocol | 確認 exact model、Classic/FD、nominal/data/BRS、支援的 query |
| P1 | DaMiao register readback 與 cache | 驗證改模式後收到的是新 response，不是舊 cache |
| P1 | Motor ID / MST_ID routing | 目前 low-nibble restriction 仍在；高 ID 不能直接放寬 |
| P1 | GUI gain limits | 舊通用 UI 的 Kp/Kd bounds 尚未完全依 mode/brand 調整 |
| P1 | RX ownership / mixed-model bus | 同一 bus 不能讓多個 consumer 互搶回覆；需統一 dispatcher |
| P1 | SocketCAN 實際 bit timing 驗證 | Python 參數不代表 OS can0 已被重設；需讀實際介面設定 |
| P2 | 偵測耗時與熱插拔 | refresh 目前仍同步列舉；需 timeout/background/device identity |

其中 GUI gain、Enable/Disable、停止後保持力矩等，須與實機安全策略一起驗收，
不在純目錄重構時盲目調大或調小。

## 11. 未來擴充架構：不是本次已完成項目

混型號、CAN-FD 與高頻控制需要另一個階段：

```text
SessionManager
  + BusSession(backend, device, physical configuration)
      + one RX dispatcher
      + MotorInstance(model, tx_id, feedback_id, verified firmware, codec)
      + MotorInstance(...)

ProtocolBackend registry
  + damiao_classic
  + lande_pa043
  + damiao_canfd  [future: audited and tested before registration]
```

同一 physical bus 的 bit timing 必須一致；`MotorInstance` 不可各自偷偷改共享 bus。
註冊 CAN-FD 時須同時具備 transport 支援、codec binding、型號/firmware 證據、
單元測試與可受控的硬體測試。不要只新增 `fd=True`。

UART 不放進這個目標；未來真的需要某個型號專用 debug 工具時，再獨立做
有版本邊界的工具，而不是宣稱整個品牌共享 UART protocol。

## 12. 驗收與交付定義

本次交付的「完成」指：品牌化目錄、相容 import、profile metadata、backend guard、
GUI catalog 及可重跑的離線驗證工具。

交付環境完成 isolated contract tests、Python 語法、JavaScript 語法及套用工具測試。
真實套件 smoke tests 和 Windows/motor 硬體測試仍必須在你的 `.venv` 與實機完成。
詳細紀錄以重構包的 `reports/VALIDATION.md` 為準，不使用主觀完成百分比。

## 來源

[S1] 被檢查的 repo revision：
https://github.com/leowang707/openarm_0824/tree/4d3c279e5cd96f24902adac42996d9b08adac2ab

[S2] 達妙官方 CAN-FD workflow（本次查得 blob `d222057742a07ac5486feb0276750df892cb1961`）：
https://github.com/dmBots/motor-sdk/blob/main/Python%E4%BE%8B%E7%A8%8B/u2canfd/WORKFLOW.md

[S3] Linux kernel SocketCAN documentation：
https://docs.kernel.org/networking/can.html

[S4] Python subprocess documentation（執行子程序採同一 `sys.executable`）：
https://docs.python.org/3/library/subprocess.html

[S5] 本對話附帶 `apply_j8009_fw6417_docs.py`、`apply_bus_profiles_adapter_caps.py`
以及使用者 UART / CAN / Git 終端輸出。這些是本機候選版本與實測紀錄，
不是宣稱已存在於遠端 commit。
