每日 08:30 抓取并发送 5 条最新的一手科技类股票新闻

概要
- 分支: automate/daily-tech-news
- 工作流: .github/workflows/daily-tech-news.yml
- 脚本: scripts/fetch_and_analyze_news.py
- 依赖: requirements.txt

Secrets（请在仓库 Settings → Secrets 中添加）
- SMTP_HOST (smtp.qq.com)
- SMTP_PORT (465)
- SMTP_USER (你的 QQ 邮箱，例如 1466707429@qq.com)
- SMTP_PASS (QQ 邮箱的 SMTP/授权码)
- RECIPIENT_EMAIL (接收邮件的邮箱，例如 1466707429@qq.com)

说明
- 我使用 RSS 源抓取新闻（不依赖第三方 News API）。默认 RSS 列表包含 36Kr、新浪科技、腾讯科技、网易科技、搜狐、虎嗅等。
- 工作流每天运行（cron 设为 00:30 UTC -> 对应 Asia/Shanghai 08:30），并且支持手动触发（workflow_dispatch），方便测试。
- 分析方法为轻量级启发式：从文章正文抽取前若干句作为摘要；使用关键词判断情感与对股价的可能影响。

测试建议
1) 在仓库 Secrets 中添加上面列出的键和值（SMTP_PASS 请使用 QQ 邮箱设置中生成的授权码）。
2) 在 Actions 页面选择 "daily-tech-news" workflow，使用 "Run workflow"（手动触发）来测试一次。
3) 查看 Actions 日志以确认脚本运行并发送邮件。

注意
- 该实现为轻量级、无需额外付费的初版。如需更准确的 NLP 分析或更稳定的一手抓取（例如绕过站点反爬），建议后续接入付费 News API 或使用更强的文本模型（需额外 API key）。
