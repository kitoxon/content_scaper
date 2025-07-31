from bs4 import BeautifulSoup
import trafilatura
import requests
import chardet
from utils import is_valid_url, is_html_content, detect_expand_buttons_in_soup
from dynamic_scraper import scrape_with_playwright
import re
def get_article_text(url: str) -> dict:
    if not is_valid_url(url):
        return {"status": "Invalid URL", "title": "", "content": ""}
    if not is_html_content(url):
        return {"status": "Non-HTML Content", "title": "", "content": ""}

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        extracted = trafilatura.extract(resp.content)
        # Detect encoding safely
        detected = chardet.detect(resp.content)
        encoding = detected.get("encoding", "utf-8")
        html = resp.content.decode(encoding, errors="replace")
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip() if soup.title else ""
        # --- Use trafilatura content if it looks good ---

        expand_tags = detect_expand_buttons_in_soup(soup)
        if expand_tags:
            # Fallback to Playwright scraper
            print("🔁 Switching to dynamic scrape due to expandable content")
            return scrape_with_playwright(url)

        for tag in soup.select("header, footer, aside, nav, .ads, .related, .banner, .comments"):
            tag.decompose()
        if extracted and len(extracted.strip()) > 100 and "���" not in extracted:
            content = extracted.strip()
            return {
                "status": "Success",
                "title": title,
                "content": clean_article_text(content)
            }



        # --- Fallback: use BS4 full-page text ---
        fallback_text = soup.get_text(separator="\n", strip=True)
        if len(fallback_text.strip()) > 100 and "���" not in fallback_text:

            return {
                "status": "Fallback Used",
                "title": title,
                "content": clean_article_text(fallback_text)
            }

        return {"status": "Dynamic Needed", "title": title, "content": ""}

    except requests.exceptions.RequestException as e:
        return {"status": f"HTTP Error: {str(e)}", "title": "", "content": ""}
    except Exception as e:
        return {"status": f"Unexpected Error: {str(e)}", "title": "", "content": ""}
def clean_article_text(content: str) -> str:
    lines = content.splitlines()
    clean_lines = []
    skip = False

    for line in lines:
        line = line.strip()

        # Start skipping when we hit unrelated sections
        if any(keyword in line for keyword in [
            '関連記事', 'この記事のフォト', 'この記事を読んだ人',
            'PR:', '提供', 'キャンペーン', 'おすすめ情報'
        ]):
            skip = True
            continue

        # Skip metadata like publication date or bullets
        if re.match(r'\d{4}年\d{1,2}月\d{1,2}日', line):
            continue
        if line.startswith('- ') or line.startswith('●') or line == '':
            continue

        # Continue skipping lines in a block once marked
        if skip:
            continue

        clean_lines.append(line)

    # Join and normalize spacing
    cleaned = '\n'.join(clean_lines)
    cleaned = re.sub(r'\n{2,}', '\n', cleaned).strip()
    patterns = [
            r'dメニューニュース.*?ご利用ください。',  # JavaScript prompts
            r'# .*?$',                                  # Headings or anchors
            r'（スポニチアネックス）｜.*?（NTTドコモ）', # Source credit
            r'\n{2,}',                                   # Multiple newlines
            r'スポニチアネックス\d+/\d+\(.+?\)',       # Source date
            r'<.*?>'                                     # Remove HTML tags
        ]
    text = ''
    for pattern in patterns:
        text = re.sub(pattern, '', cleaned, flags=re.MULTILINE)
    return text

if __name__ == "__main__":
    result = get_article_text("https://topicool.jp/article/starto/sixtones/kiji-sixtones/article-49338")
    print(result)
