---
name: remind-at-done
description: 主任务准备最终答复时，核对真实完成状态和本项目标的经过时间；严格超过五分钟才主动编写摘要，通过本机 Remind-at-done 投递桌面提醒。阶段进展、提问、暂停、失败与子代理返回不投递。
---

# 完成提醒

在主任务最终答复前读取本技能，再判断是否通知。不要登记开始，不从 daemon 状态猜测完成，也不把一个 turn 结束当成用户目标完成。

1. 确认用户要求及必要验证确已完成；如果仍等待用户、审批、运行结果或后续阶段，正常回复但不发完成提醒。子代理不投递。
2. 从 `installation.json` 取得本机 `rad` 路径。运行 `rad context`，核对当前线程、`is_child` 和工作目录。这个命令仅查询事实，不开始计时，不修改任务。
3. 结合上下文选择**本项工作最初请求**对应的 `turns[].task_key` 与 `started_at`（Unix 秒）。需要更早的请求时，用 `rad context --cursor <next_cursor>` 分页。澄清和自动续行继续使用原起点；同线程的新独立任务换起点。若 `goal.objective` 与本次目标一致，也可使用 `goal.createdAt`，以 `goal:<createdAt>` 为 task_key。不能用线程创建时间、最近一条消息、文件时间或估计值替代。
   若需精确到毫秒的用户事件起点，用 `rad context --turn <轮次ID>` 读取该轮次中用户消息的 `started_at_ms` 和 `message:` task_key，可用游标继续查询。目标自动续行的轮次可能没有用户消息，此时保留原目标起点，不选第一条代理消息。
4. 读取当前时间，按实际经过秒数计算，包含等待。用随技能提供的 `scripts/check-completion.ps1` 核对门槛：传入带时区的 `StartedAt`、`CompletedAt`、`State completed`，并只在主任务时加 `-RootTask`。`eligible` 为 false 则结束本技能，不写提醒。时间缺失、倒置或无时区时不编造；若属于正常长任务且无法取起点，最终答复简短说明限制。
5. eligible 为 true 时，由你自己编写 UTF-8 JSON 文件，使用以下字段。标题 ≤24、摘要 ≤120、可选验证 ≤80 个可见字符；如实保留“未运行”等限制。不要让后端生成摘要。不要包含凭证或私密聊天原文。

```json
{
  "task_key": "turn:实际起始轮次ID",
  "status": "completed",
  "title": "任务成果标题",
  "summary": "简短说明已完成的结果。",
  "verification": "实际完成的检查及限制",
  "completed_at": "2026-10-29T13:00:00+08:00",
  "elapsed_seconds": 301,
  "timing_source": "history_metadata"
}
```

`timing_source` 按实际证据选择 `history_metadata`、`goal_metadata` 或 `context`。时间与示例数字必须替换为实际值。CLI 自动补齐实例、当前线程、工作目录和稳定 event_id。

6. 用 `& <rad路径> notify --file <UTF-8文件>` 投递。也可使用 UTF-8 `--stdin`，但 Windows PowerShell 5.1 默认管道编码可能破坏中文，优先文件。
7. stdout 的 `accepted` 或 `duplicate`（退出码 0）表示已保存，不表示用户已读。连接错误（退出码 3）至多重试一次，复用**完全相同**的文件，包括时间；每次调用最多等 5 秒。保存错误为 4、冲突为 5、格式/身份错误为 2；不要用新 task_key 绕开冲突。投递失败不改变任务成果，不无限等待。

   `outside_retention`（退出码 2）表示报告不在最近 3 天的最新 20 项内，没有保存。不重试，也不要改写完成时间以绕过保留规则。

提醒尝试结束后给用户正常最终答复。短任务也读取本技能，但不投递，不在最终答复中额外报告跳过通知。
