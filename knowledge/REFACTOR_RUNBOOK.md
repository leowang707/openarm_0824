# 下週本機重構 Runbook

本包不操作馬達、不改 UART/CAN baud、不改 firmware，也不自動 commit/push。
`changes/` 只有要變更的檔案，不是完整 repository；不要把它當新 repo 執行。

## 0. 先確認本機狀態，保存今天的 B

先關閉 GUI、Python motor 程式與官方調試工具；硬體測試先暫停。

```powershell
cd C:\dev\openarm_0824
git status --short
git --no-pager log -5 --oneline
```

若仍有 A2/B 或其他未提交內容，先 review 再提交；不要 `reset --hard`、不要
刪除不認識的修改。當下工具只接受乾淨的 working tree/index，避免套用途中
才發現前一步沒保存。B 是否已 push 以 `git fetch` 後的本機/遠端差異為準。

```powershell
git fetch origin
git --no-pager log --oneline origin/feature/lande-pa043..HEAD
```

上面是讀取與比較，不會自動 merge / rebase。建立工作分支時保留當前本機 HEAD：

```powershell
git switch -c refactor/vendor-layout-20260921
```

分支已存在時，先檢查其 HEAD 再用 `git switch` 切換，不要 force 覆蓋。

## 1. 把壓縮包解在 repo 外面

建議路徑：

```text
C:\dev\openarm_refactor_20260918\apply_refactor.py
C:\dev\openarm_refactor_20260918\manifest.json
C:\dev\openarm_refactor_20260918\changes\...
```

這可避免安裝腳本與內容檔案自己變成 repo 的 untracked changes。
舊的 `apply_bus_profiles_adapter_caps.py`、`apply_j8009_fw6417_docs.py`
不要再重跑；本包已處理已知前／後版本。

## 2. 明確使用專案的 Python

```powershell
cd C:\dev\openarm_0824
$py = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $py -c "import sys; print(sys.executable)"
```

應指向這個 repo 的 `.venv`。不依賴 PowerShell prompt 是否有 `(.venv)`，
也不呼叫別的 PATH `python` 作子程序。

## 3. 只預覽：不改任何 repo 檔案

```powershell
& $py C:\dev\openarm_refactor_20260918\apply_refactor.py --repo C:\dev\openarm_0824 --plan
```

工具會檢查：Git root、已知來源內容、payload 雜湊、Python 語法、路徑安全、
existing changes。忽略 CRLF/LF 差異，但不忽略真的程式碼差異。

如果看到 `Preflight conflicts`，**整批不寫入**。不要移除 hash guard；
改為比較本機版本與包內 `patches/`，人工做受控 merge。

## 4. 套用並記下 Backup ID

```powershell
& $py C:\dev\openarm_refactor_20260918\apply_refactor.py --repo C:\dev\openarm_0824 --apply
```

工具在 Git metadata 下的 `openarm-refactor-backups/<ID>/` 備份原始 bytes，
完成後才逐檔寫入；發生一般套用錯誤會嘗試回復。它不 stage、不 commit、不 push。
多檔寫入不是 OS 層級的單一 atomic transaction；有保存 backup manifest 供中斷後回復。

套用後先檢查：

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff --check
```

`git --no-pager` 不會停在先前看到的 `:` 畫面。
Windows LF→CRLF 提示本身不是測試失敗；whitespace error 才要處理。

## 5. 先做完全離線測試

完整檢查：

```powershell
& $py tools\verify_refactor.py
```

它依序做 Python 語法、40 個 isolated contract checks、真實套件的 FakeBus / Flask smoke，
最後檢查 diff whitespace。不開 CAN adapter、不自動讓馬達動。

若缺少套件，命令會明確失敗，不會把 skipped 當 PASS：

```powershell
& $py -m pip install -r requirements.txt
& $py tools\verify_refactor.py
```

不要為了安裝問題無意更新整台機器的 global Python。測試輸出會列出實際
`python-can / pyserial / damiao-motor / Flask` 版本；驗收後可另存 dependency lock。
本包沒有聲稱已在每個版本的 `damiao-motor>=1.0.6` 驗證過。

僅在尚未安裝套件時看純架構：

```powershell
& $py tools\verify_refactor.py --mock-only
```

`MOCK-ONLY PASS` **不是完整 release approval**，之後仍必須執行完整模式。

## 6. 檢查 catalog，不探測馬達

```powershell
& $py -m diagnostics.catalog
```

預期三個原有 key 都存在，並按 DaMiao / LANDA 分群。
J8009 的 FD candidate 保持 `implemented=False`。

需要列舉目前 COM/USB/SocketCAN 介面時才使用：

```powershell
& $py -m diagnostics.catalog --devices
```

`--devices` 不傳 motor commands，但作業系統／第三方 USB 列舉可能耗時。
發現 serial 裝置不代表辨識出馬達或 CAN protocol。

## 7. 無馬達 GUI 檢查

```powershell
& $py start_gui.py
```

瀏覽 `http://127.0.0.1:5000`，先只做畫面／catalog 檢查：

- 品牌下拉可選 DaMiao / LANDA，型號會跟著過濾。
- Bus Profile 顯示 Classic default；FD candidate 灰色停用。
- CAN Backend 標示 serial / direct_usb / os_stack；不把這些都當硬體品牌。
- CH340 port 列出但顯示 unverified candidate，需明確選 `usbcan_a` 才會用此協定。
- 輪盤、選取馬達、原有按鈕與 routes 保留。沒有馬達時不應據空值宣稱已驗證位置。

**這階段不按 Enable/Spin，不做 Restore Defaults/Calibration。**
測試後關閉 GUI，才進行下一步 Git 操作。

## 8. Review 與 commit

本包涉及 module -> package 遷移，請把互相依賴的檔案放在同一個原子 commit，
不要只 commit 刪檔而漏掉新的 `__init__.py`。

```powershell
git add -A -- README.md can_profiles.py can_adapters motors motor_service.py gui_server.py templates/custom_gui.html lande_motor.py diagnostics tests/refactor_contract_checks.py tests/refactor_dependency_checks.py tools/verify_refactor.py knowledge/ARCHITECTURE.md knowledge/REFACTOR_RUNBOOK.md knowledge/HARDWARE_OBSERVATIONS.md knowledge/DAMIAO_PROTOCOL_AUDIT.md

git --no-pager diff --cached --check
git --no-pager diff --cached --stat
git status --short
```

確認沒有 `.venv`、備份、暫時測試資料或其他不相關檔案後：

```powershell
git commit -m "refactor: organize motor backends by vendor and guard CAN profiles"
```

完整離線測試通過且 review 完成後，先推工作分支：

```powershell
git push -u origin refactor/vendor-layout-20260921
```

不要 force-push 原 feature branch。合回 feature branch 前，依團隊習慣 PR/review。
真實硬體測試留成獨立紀錄與 commit，不把離線結果寫成實機通過。

## 9. 未 commit 前回復

保留 `--apply` 印出的 Backup ID。尚未 commit、沒有後續人工修改且 index 未 stage 時：

```powershell
& $py C:\dev\openarm_refactor_20260918\apply_refactor.py --repo C:\dev\openarm_0824 --rollback BACKUP_ID
```

若已 stage，先 review 並僅 unstage 這次改動；若 HEAD 已改變／已 commit，
工具拒絕檔案式回復，改用 review 過的 `git revert <commit>`。
若某檔案套用後又被你修改，rollback 會停止，不覆蓋新工作。

## 10. 下週硬體驗收前的限制

還沒有驗證通訊 profile 的 J8009 個體，先不要直接做運動。
`5.00Mbps` 輸出不能代替 CAN-FD bit timing/frame format 的實測證據。
確認實體型號、firmware、CAN 設定、穩定的新 feedback 與現場安全條件後，
才安排受控動作測試。

CAN-FD driver / UART / 混型號共線都不在本次運動驗收範圍；這次並未實作它們。
