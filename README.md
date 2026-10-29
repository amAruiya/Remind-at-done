# Remind at done

Windows 上的 Codex 完成提醒助手。任务完成后，从圆形悬浮入口展开简短摘要；点击提醒或历史记录，在新的 PowerShell 视图中恢复对应 Codex 线程。

当前为 **0.1.0 开发预览**。支持本机 Windows x64，已验证 Codex CLI / daemon 0.165.0。功能与验证边界见 [实施说明](docs/implementation.md)。

## 功能

- 40 DIP 圆形入口，可拖动、记住位置、保持置顶。
- 入口、完成摘要和任务面板共用一个窗口，平滑展开、收回。
- “进行中”在前，“已完成”在后；完成记录保留最近 3 天、最多 20 项，每页 10 项。
- 按需查询当前主任务，隐藏子代理；读取失败时保留旧快照。
- 按实例和线程 ID 返回原任务，支持原终端标签已关闭的情况。
- 深浅主题、减少动画、免打扰、托盘恢复、可选登录启动。
- 本地持久收据、重复报告去重、明确成功或失败回执。

## 构建与安装

本仓库提供源码；生成的安装包和本机运行数据不提交到 Git。需要 Windows PowerShell 5.1、Git 和可运行的 Codex CLI / daemon。

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-sdk.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1 -Output output/release/app -SelfContained
powershell -NoProfile -ExecutionPolicy Bypass -File output/release/app/install.ps1
```

SDK 脚本安装固定的 .NET SDK 10.0.403 并核对 SHA-512，不修改系统 PATH。自包含发布目录不要求目标电脑另装 .NET 运行时。安装脚本会登记 Codex 实例、安装收尾 skill 和指引，并启动助手。

默认安装目录为 `%LOCALAPPDATA%\RemindAtDone\app`。如果自动定位 Codex 失败，可向安装脚本传入实际的 `-CodexHome` 和 `-CodexExe`。更新时运行新版安装脚本即可，已有设置和完成记录会保留。

若自行打包分发，接收者解压后在 `RemindAtDone` 文件夹运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

## 启动与使用

安装后，在 PowerShell 运行：

```powershell
& "$env:LOCALAPPDATA\RemindAtDone\app\rad.exe" start
```

也可双击安装目录中的 `RemindAtDone.exe`。点击圆形入口查看任务，点击面板外部关闭；拖动入口移动位置。如果入口被隐藏，在系统托盘右键点击星形图标，选择“恢复悬浮入口”。登录启动默认关闭，可在设置中开启。

完成摘要默认显示 8 秒，允许选择 5 / 8 / 10 秒。关闭或自动收回不代表已读。全屏期间入口仍可见，但新摘要静默保存，退出全屏后不补播。

## 完成提醒规则

执行任务的 Codex 在最终答复前读取 [收尾 skill](skills/remind-at-done/SKILL.md)，使用该项工作的真实起点判断：**确已完成且经过时间严格大于 300 秒**才编写摘要并投递。无需开始登记，不通过后台猜测任务完成，也不额外调用模型生成摘要。

```powershell
& "$env:LOCALAPPDATA\RemindAtDone\app\rad.exe" context
& "$env:LOCALAPPDATA\RemindAtDone\app\rad.exe" notify --file report.json
```

`context` 提供有界、可分页的时间及身份信息；它不登记任务。报告使用 UTF-8 JSON，PowerShell 5.1 推荐 `--file`。安装指引由新 Codex 任务载入，已运行任务不保证立即获得。

## 数据与排错

设置、完成记录和诊断日志位于 `%LOCALAPPDATA%\RemindAtDone`。它们可能含有工作目录、任务标识和摘要，不应提交到 GitHub。`RAD_DATA_DIR` 可指定隔离测试目录。

- daemon 未运行时，先用原 Codex 工作流恢复，再刷新任务列表；助手不会重启用户的 daemon。
- 线程或工作目录不存在时保留摘要并提示原因，不跳转到最近的其他任务。
- 收据成功后才返回 `accepted`；重试相同内容返回 `duplicate`，冲突或保存失败返回明确错误。
- 历史损坏优先恢复有效备份；没有有效备份时不会静默清空。

卸载时运行安装目录中的 `uninstall.ps1`，撤销本工具指引、skill 和登录启动项。程序文件、历史和设置保留，可按需手动移除。

## 验证

```powershell
& "$env:LOCALAPPDATA/RemindAtDone.Build/dotnet/dotnet.exe" run --project tests/RemindAtDone.Tests -c Release
& "$env:LOCALAPPDATA/RemindAtDone.Build/dotnet/dotnet.exe" run --project tests/RemindAtDone.UiTests -c Release -- output/theme-check/info/results.json
python -X utf8 scripts/verify-skill.py
```

其他桌面和 daemon 集成脚本位于 `scripts`。部分脚本依赖多屏布局、真实 Codex 实例或先前创建的隔离测试资料，请按脚本参数准备；原始桌面录屏、个人会话和测试日志不随源码发布。

锁屏恢复、实际系统缩放切换、物理拔屏和完整工作日观察尚未全部实测。当前不支持远程 daemon、其他平台、任务编辑或桌宠引擎。
