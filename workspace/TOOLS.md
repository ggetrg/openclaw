# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## 项目知识库问答（QQ Bot）

- 触发词：当用户消息以“项目问题”开头时，优先执行项目知识库问答流程，不走普通闲聊。
- 问题提取：去掉前缀“项目问题”后，再去掉开头的空格、`:`、`：`、`-`，剩余即 `question`。
- 问答命令：
  `python3 /Users/ikun/.openclaw/agents/main/agent/project_kb_worker.py ask --kb-root /Users/ikun/.openclaw/qqbot/data/project-kb/new --question "<question>"`
- 失败兜底：若 ask 失败或知识库为空，提示先执行扫描命令：
  `python3 /Users/ikun/.openclaw/agents/main/agent/project_kb_worker.py scan --project-path /Users/ikun/.openclaw/new --kb-root /Users/ikun/.openclaw/qqbot/data/project-kb/new`
- 回复格式固定三段：
  `【建议】`、`【相关模块】`、`【涉及文件】`（最多 8 个文件，优先列出包含 symbols 的文件）。
