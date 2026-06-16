"""
HTML 邮件 + 失败告警版脚本
- 成功时发送 HTML 格式的每日汇总邮件
- 出错时发送包含错误信息的 HTML 告警邮件

需要在仓库 Secrets 中设置：
- SMTP_HOST
- SMTP_PORT
- SMTP_USER
- SMTP_PASS
- RECIPIENT_EMAIL
可选：
- ALERT_RECIPIENT_EMAIL (若不设置则使用 RECIPIENT_EMAIL)
"""
import os
import sys
import time
import traceback
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

# RSS sources (Chinese + some international tech feeds)
RSS_FEEDS = [
    "https://36kr.com/feed",
    "http://feed.tech.sina.com.cn/tech/rollnews.xml",
    "https://tech.qq.com/rss.jsp",
    "http://tech.163.com/special/00097UHL/rss_news.xml",
    "https://www.sohu.com/rss/1/257",
    "https://www.huxiu.com/rss/"
]

# Keywords to filter for stock-related tech news (Chinese)
STOCK_KEYWORDS = [
    "上市", "IPO", "回购", "融资", "亏损", "盈利", "下滑", "增长", "裁员", "合作", "并购", "收购", "涨停", "下跌", "股价", "股票", "A股", "港股", "美股"
]

POS_WORDS = ["增长", "盈利", "上升", "提振", "利好", "回暖", "上涨", "扩张", "改善"]
NEG_WORDS = ["亏损", "下滑", "下跌", "裁员", "降薪", "减持", "停牌", "质疑", "担忧", "恶化"]

MAX_SUMMARY_CHARS = 300


def fetch_feed_entries():
    entries = []
    for url in RSS_FEEDS:
        try:
            d = feedparser.parse(url)
            for e in d.entries:
                # normalize
                published = None
                if 'published_parsed' in e and e.published_parsed:
                    published = datetime.fromtimestamp(time.mktime(e.published_parsed))
                elif 'updated_parsed' in e and e.updated_parsed:
                    published = datetime.fromtimestamp(time.mktime(e.updated_parsed))
                else:
                    published = datetime.utcnow()

                entries.append({
                    'title': e.get('title', '').strip(),
                    'link': e.get('link', '').strip(),
                    'summary': e.get('summary', '').strip(),
                    'published': published,
                    'source': d.feed.get('title', url)
                })
        except Exception as ex:
            print(f"Failed to parse feed {url}: {ex}", file=sys.stderr)
    # sort by published desc
    entries.sort(key=lambda x: x['published'], reverse=True)
    return entries


def fetch_article_text(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
        # extract paragraphs
        ps = soup.find_all('p')
        text = '\n'.join([p.get_text().strip() for p in ps if p.get_text().strip()])
        if not text:
            # fallback to meta description
            meta = soup.find('meta', attrs={'name': 'description'})
            if meta and meta.get('content'):
                text = meta.get('content')
        return text
    except Exception as ex:
        print(f"Failed to fetch article {url}: {ex}", file=sys.stderr)
        return ""


def is_stock_related(entry):
    txt = (entry['title'] + ' ' + entry.get('summary', ''))
    for kw in STOCK_KEYWORDS:
        if kw in txt:
            return True
    return False


def simple_summary(text, max_chars=MAX_SUMMARY_CHARS):
    if not text:
        return "(无法抓取正文，使用 RSS 摘要)"
    for sep in ['。', '！', '？', '\n']:
        text = text.replace(sep, sep + '\n')
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    summary = ''
    for ln in lines:
        if len(summary) + len(ln) > max_chars:
            break
        summary += ln
        if not summary.endswith('。'):
            summary += '。'
        if len(summary) >= max_chars:
            break
    return summary[:max_chars]


def sentiment_and_impact(text):
    score = 0
    for w in POS_WORDS:
        if w in text:
            score += 1
    for w in NEG_WORDS:
        if w in text:
            score -= 1
    if score > 0:
        sentiment = '正面'
    elif score < 0:
        sentiment = '负面'
    else:
        sentiment = '中性'

    impact = '中性'
    if sentiment == '正面' and any(kw in text for kw in ['股价', '上涨', '利好', '回购', '盈利', '增长']):
        impact = '可能正面'
    if sentiment == '负面' and any(kw in text for kw in ['亏损', '下跌', '停牌', '裁员', '下滑', '减持']):
        impact = '可能负面'
    return sentiment, impact


def make_html_email(items, date_str):
    # compose an HTML email with items (list of dict)
    rows = []
    for i, it in enumerate(items, 1):
        rows.append(f"""
        <tr style="vertical-align:top;">
          <td style="padding:8px;border-bottom:1px solid #eee;"><strong>{i}. {escape_html(it['title'])}</strong>
            <div style="color:#666;margin-top:6px;">{escape_html(it['summary'])}</div>
            <div style="margin-top:6px;font-size:13px;color:#333;">
              来源: {escape_html(it['source'])} · 发布: {it['published'].strftime('%Y-%m-%d %H:%M:%S')}
              <br/>情感: <strong>{it['sentiment']}</strong> · 影响判断: <strong>{it['impact']}</strong>
              <br/><a href="{it['link']}" target="_blank">阅读原文</a>
            </div>
          </td>
        </tr>
        """)

    body = f"""
    <html>
    <head>
      <meta charset="utf-8"/>
    </head>
    <body style="font-family:Arial, Helvetica, sans-serif; color:#222;">
      <h2>每日科技股票新闻汇总（{date_str}）</h2>
      <p>以下为自动抓取并分析的 5 条最新一手科技类股票新闻：</p>
      <table style="width:100%;border-collapse:collapse;">{''.join(rows)}</table>
      <hr/>
      <div style="color:#666;font-size:13px;">抓取来源 RSS 列表: {escape_html(', '.join(RSS_FEEDS))}</div>
    </body>
    </html>
    """
    return body


def make_html_alert(error_text, recent_items):
    # recent_items can be empty; include short list
    items_html = ""
    if recent_items:
        for it in recent_items[:5]:
            items_html += f"<li><a href='{it['link']}' target='_blank'>{escape_html(it['title'])}</a> — {escape_html(it['source'])}</li>"
    else:
        items_html = "<li>(无可用抓取条目)</li>"

    body = f"""
    <html><body style="font-family:Arial, Helvetica, sans-serif;color:#222;">
      <h2 style="color:#b00020">[失败警报] 每日科技股票新闻发送失败</h2>
      <p>时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
      <h3>错误摘要</h3>
      <pre style="background:#f7f7f7;padding:10px;border-radius:4px;overflow:auto;">{escape_html(error_text)}</pre>
      <h3>抓取到的最近条目（最多 5 条）</h3>
      <ul>{items_html}</ul>
      <hr/>
      <div style="color:#666;font-size:13px;">如果该错误持续出现，请检查 Secrets 配置（SMTP_*）和 QQ 邮箱授权码是否有效。</div>
    </body></html>
    """
    return body


def escape_html(s):
    if s is None:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#39;"))


def send_email_html(subject, html_body, smtp_host, smtp_port, smtp_user, smtp_pass, recipient, sender_name=None):
    try:
        msg = MIMEText(html_body, 'html', 'utf-8')
        msg['From'] = formataddr((sender_name or smtp_user, smtp_user))
        msg['To'] = recipient
        msg['Subject'] = Header(subject, 'utf-8')

        port = int(smtp_port) if smtp_port else 465
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_host, port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, port, timeout=30)
            server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [recipient], msg.as_string())
        server.quit()
        print('Email sent to', recipient)
        return True
    except Exception as ex:
        print('Failed to send email:', ex, file=sys.stderr)
        return False


def main():
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = os.getenv('SMTP_PORT')
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')
    recipient = os.getenv('RECIPIENT_EMAIL')
    alert_recipient = os.getenv('ALERT_RECIPIENT_EMAIL') or recipient

    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, recipient]):
        print('Missing SMTP or recipient configuration. Please set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, RECIPIENT_EMAIL as environment variables or GitHub Secrets.', file=sys.stderr)
        return

    try:
        entries = fetch_feed_entries()
        stock_entries = [e for e in entries if is_stock_related(e)]

        # deduplicate by link/title
        seen = set()
        filtered = []
        for e in stock_entries:
            key = (e['link'], e['title'])
            if key in seen:
                continue
            seen.add(key)
            filtered.append(e)
            if len(filtered) >= 30:
                break

        results = []
        for e in filtered:
            full_text = fetch_article_text(e['link'])
            summary = simple_summary(full_text if full_text else e.get('summary', ''))
            sentiment, impact = sentiment_and_impact((e['title'] + ' ' + summary + ' ' + (e.get('summary') or '')))
            results.append({
                'title': e['title'],
                'link': e['link'],
                'source': e['source'],
                'published': e['published'],
                'summary': summary,
                'sentiment': sentiment,
                'impact': impact
            })
            if len(results) >= 5:
                break

        if not results:
            # 如果没有找到合适的条目，也作为一种情况处理，但仍给出通知（这里选择不发送失败告警，仅在日志输出）
            print('No stock-related tech news found in feeds.')
            return

        date_str = datetime.now().strftime('%Y-%m-%d')
        subject = f"每日科技股票新闻汇总（{date_str}）"
        html_body = make_html_email(results, date_str)

        sent = send_email_html(subject, html_body, smtp_host, smtp_port, smtp_user, smtp_pass, recipient, sender_name="每日科技新闻机器人")
        if not sent:
            # 发送失败 -> 发告警邮件（包含错误跟踪）
            err_text = "SMTP 发送失败（脚本内部检测）"
            alert_html = make_html_alert(err_text, results)
            send_email_html(f"[失败警报] {subject}", alert_html, smtp_host, smtp_port, smtp_user, smtp_pass, alert_recipient, sender_name="每日科技新闻机器人")
            sys.exit(1)

    except Exception as ex:
        # 捕获任意未处理异常并发送告警邮件
        tb = traceback.format_exc()
        print('Unhandled exception:', tb, file=sys.stderr)
        # 尝试发送告警邮件（如果 SMTP 配置存在）
        try:
            smtp_host = os.getenv('SMTP_HOST')
            smtp_port = os.getenv('SMTP_PORT')
            smtp_user = os.getenv('SMTP_USER')
            smtp_pass = os.getenv('SMTP_PASS')
            alert_recipient = os.getenv('ALERT_RECIPIENT_EMAIL') or os.getenv('RECIPIENT_EMAIL')
            alert_html = make_html_alert(tb, [])
            if smtp_host and smtp_port and smtp_user and smtp_pass and alert_recipient:
                send_email_html(f"[失败警报] 每日科技股票新闻脚本异常", alert_html, smtp_host, smtp_port, smtp_user, smtp_pass, alert_recipient, sender_name="每日科技新闻机器人")
        except Exception:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
