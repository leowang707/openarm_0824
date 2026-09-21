# 硬體實測紀錄與證據邊界

更新：2026-09-18。來源為本次使用者提供的終端輸出、照片與測試結果，
不是由 repository code 或本文件自動驗證硬體。

## 1. 達妙受測個體：先稱為 J8009 系列

使用者後來提出，受測馬達也可能是 **DM-J8009-2EC**，而不是
**DM-J8009P-2EC**。UART 沒有列出完整產品型號，故尚不能確定 P / 非 P。
GUI 仍保留既有 `damiao_8009p` key，以相容既有程式；這個 key 不代表
程式已辨識出受測個體的完整型號。

使用者提供的 UART 開機輸出摘要：

```text
DMBOT Motor Driver--V3.0
Firmware Version: 6417
Sub Version: 004
CAN ID:     0x001
MASTER ID:  0x011
CAN Baud:   5.00Mbps
V_BUS=24.0940

Control Mode:
1:MIT Mode <----
2:position-speed cascade Mode
3:speed Mode
4:Hybrid control Mode

Commands:
 m - Motor Mode
 s - Setup Mode
 esc - Exit to Menu
```

UART 接收使用 921600 baud；使用者曾收到 `Entering Motor Mode`，
也在送 `0x1B` 後收到主選單。在確認主選單後送 `s`，當次測試沒有回覆。
**沒有回覆不等於功能不存在，也不能證明 setup 被 firmware 關閉。**

本次重構不提供 UART driver、UART 自動探測、設定寫入或 Motor Mode 操作。
這些紀錄只作為指定受測個體的診斷證據。

## 2. 能確認與仍未確認的項目

| 項目 | 能確認的範圍 |
|---|---|
| CAN ID / MASTER ID | UART 印出 `0x001` / `0x011` |
| 韌體版號 | UART 印出 6417 / 004；不是完整型號識別 |
| `5.00Mbps` | UART 印出的報告值；沒有直接揭露 nominal/data phase/BRS |
| 1M nominal + 5M data | 達妙官方 CAN-FD 範例採用；尚非此個體的匯流排量測 |
| `Hybrid` | 選單有模式 4 的名稱；不直接證明等同 `FORCE_POS` payload |
| Classic/FD 自動切換 | 沒有足夠證據確認有或沒有 |
| 1 Mbps Classic 測試 | 使用 Waveshare 對已知 ID 發 `0x7FF / 01 00 CC ...` 時未收到回覆 |
| `NO RX` 的根因 | 尚未唯一定位；不能只據此排除接線、實體收發器、bit timing、firmware 指令支援 |

`canfd_1m_5m` 目前只是 **candidate / implemented=False**。
不因為看到 `5.00Mbps` 就自動選取，也不嘗試任何 CAN baud / firmware 寫入。
把 FD data bitrate 改成 1M，亦不等於必然變成 Classic CAN。

## 3. Waveshare USB-CAN-A

照片確認型號；使用者曾以官方工具及 raw Python serial 成功完成內部迴路測試：

```text
CFG: aa 55 12 01 01 00 00 00 00 00 00 00 00 01 00 00 00 00 00 15
TX : aa c8 23 01 11 22 33 44 55 66 77 88 55
RX : aa c8 23 01 11 22 33 44 55 66 77 88 55
```

這支持該次 serial 傳輸／接收、設定與 internal loopback 路徑可工作。
**不證明外部 CAN-H/L 收發器、馬達端接線或 CAN ACK 都已驗證通過。**
早先測試誤把 mode `0x02` 當成 loopback；後來使用 `0x01` 成功。
不再把前者的失敗當作 adapter 損壞或 repo normal-mode 錯誤證據。

CH340 `1A86:7523` 也可能出現在 USB-TTL，不足以識別 Waveshare。
本次 UI 保留列出 serial port，但 Auto 不會僅憑 CH340 自動選用 USB-CAN-A。
COM 號是當時 OS 的指派，不是永久硬體識別碼。

## 4. CANable2 / LANDA PA043

使用者先前在 SLCAN 版本查詢得到：

```text
16e7497-dirty github.com/normaldotcom/canable2.git
```

這支持當時該個體的 host protocol 為相應 SLCAN 韌體；不代表所有 CANable2
都使用同一 protocol，亦不保證此 repo 的 SLCAN backend 支援該硬體所有能力。

PA043 已有使用者回報的離線 frame 測試，但尚未提供本次架構版本完成
實機位置／速度／扭矩運動驗收的證據。保留預設 GUI motion lock。

## 5. 官方參考資料與其角色

- J8009P V1.0 手冊（使用者指定、供舊 Classic profile 對照）：
  https://doc.switch-science.com/media/files/0eacb9ba-85e6-4761-93df-92773000fddb.pdf
- 達妙官方 CAN-FD 範例（展示 1M/5M，不是受測個體證明）：
  https://github.com/dmBots/motor-sdk/blob/main/Python%E4%BE%8B%E7%A8%8B/u2canfd/WORKFLOW.md
- Waveshare USB-CAN-A：
  https://www.waveshare.com/wiki/USB-CAN-A

外部文件與實測紀錄分開保存；未經再次查證，不將 generic SDK 的能力自動
提升為所有型號／所有 firmware 的功能保證。
