"""
Fetch latest tech-related stock news from RSS sources, do a simple analysis (summary, sentiment, impact),
and email the top 5 to the recipient via SMTP.

Environment variables (set these as GitHub Secrets):
- SMTP_HOST (e.g. smtp.qq.com)
- SMTP_PORT (e.g. 465)
- SMTP_USER (your QQ email)
- SMTP_PASS (your QQ SMTP/授权码)
- RECIPIENT_EMAIL (recipient email address)

This script is intentionally lightweight and uses RSS feeds + simple heuristics for analysis.
"""

import os
import sys
import time
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.header import Header

# RSS sources (Chinese + some international tech feeds)
RSS_FEEDS = [
    # 36Kr
    "https://36kr.com/feed",
    # 新浪科技
    "http://feed.tech.sina.com.cn/tech/rollnews.xml",
    # 腾讯科技
    "https://tech.qq.com/rss.jsp",
    # 网易科技
    "http://tech.163.com/special/00097UHL/rss_news.xml",
    # 搜狐科技
    "https://www.sohu.com/rss/1/257",
    # 虎嗅
    "https://www.huxiu.com/rss/"
]

# Keywords to filter for stock-related tech news (Chinese)
STOCK_KEYWORDS = [
    "上市", "IPO", "回购", "融资", "亏损", "盈利", "下滑", "增长", "裁员", "合作", "并购", "收购", "涨停", "下跌", "股价", "股票", "A股", "港股", "美股"
]

POS_WORDS = ["增长", "盈利", "上升", "提振", "利好", "回暖", "上涨", "扩张", "改善"]
NEG_WORDS = ["亏损", "下滑", "下跌", "裁员", "降薪", "减持", "停牌", "质疑", "担忧", "恶化"]


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


def simple_summary(text, max_chars=240):
    if not text:
        return "(无法抓取正文，使用 RSS 摘要)"
    # For Chinese: split by 。！？\n
    for sep in ['。', '！', '？', '\n']:
        text = text.replace(sep, sep+'\n')
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
    # simple keyword-based sentiment
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

    # impact heuristic: if stock keywords appear with pos/neg words
    impact = '中性'
    if sentiment == '正面' and any(kw in text for kw in ['股价', '上涨', '利好', '回购', '盈利', '增长']):
        impact = '可能正面'
    if sentiment == '负面' and any(kw in text for kw in ['亏损', '下跌', '停牌', '裁员', '下滑', '减持']):
        impact = '可能负面'
    return sentiment, impact


def compose_email(items):
    date_str = datetime.now().strftime('%Y-%m-%d')
    subject = f"每日科技股票新闻汇总（{date_str}）"

    lines = [f"{subject}", "", "以下为自动抓取并分析的 5 条最新一手科技类股票新闻：", ""]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. 标题: {it['title']}")
        lines.append(f"   来源: {it['source']}  发布: {it['published'].strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"   链接: {it['link']}")
        lines.append(f"   摘要: {it['summary']}")
        lines.append(f"   情感: {it['sentiment']}   影响判断: {it['impact']}")
        lines.append("")

    lines.append("----\n抓取来源 RSS 列表: " + ", ".join(RSS_FEEDS))
    body = '\n'.join(lines)
    return subject, body


def send_email(subject, body, smtp_host, smtp_port, smtp_user, smtp_pass, recipient):
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = smtp_user
        msg['To'] = recipient
        msg['Subject'] = Header(subject, 'utf-8')

        port = int(smtp_port) if smtp_port else 465
        # use SSL for port 465
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
    entries = fetch_feed_entries()
    # filter stock-related
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

    # fetch article text and analyze, pick top 5 most recent
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
        print('No stock-related tech news found in feeds.')
        return

    subject, body = compose_email(results)

    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = os.getenv('SMTP_PORT')
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')
    recipient = os.getenv('RECIPIENT_EMAIL')

    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, recipient]):
        print('Missing SMTP or recipient configuration. Please set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, RECIPIENT_EMAIL as environment variables or GitHub Secrets.', file=sys.stderr)
        return

    sent = send_email(subject, body, smtp_host, smtp_port, smtp_user, smtp_pass, recipient)
    if not sent:
        sys.exit(1)


if __name__ == '__main__':
    main()
