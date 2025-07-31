
import requests
from urllib.parse import urlparse
def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def is_html_content(url: str) -> bool:
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.head(url, allow_redirects=True, timeout=10, headers=headers)
        content_type = resp.headers.get('Content-Type', '')
        return 'text/html' in content_type
    except requests.exceptions.RequestException as e:
        print(f"[info] Failed to check content type for {url}: {e}")
        return False
def get_japanese_expand_keywords():
    return [
        "続きを読む", "続きはこちら", "もっと読む", "もっと見る", "詳細を見る",
        "全文を読む", "全文表示", "すべて表示", "記事を読む", "内容を表示",
        "この続きを見る", "表示を増やす"
    ]

def get_priority_expand_keywords():
    return ["続きを読む", "全文を読む", "全文表示", "続きを見る", "写真の記事を読む"]

def detect_expand_buttons_in_soup(soup):
    keywords = get_priority_expand_keywords()
    return soup.find_all(lambda tag: (
        tag.name in ["a", "button", "span", "div", "label"] and
        any(kw in tag.get_text() for kw in keywords)
    ))


async def try_click_keywords(page, keywords, max_clicks=3):
    for kw in keywords:
        locator = page.locator(f"text={kw}")
        count = await locator.count()
        if count:
            try:
                for i in range(min(count, max_clicks)):
                    await locator.nth(i).click(timeout=2000)
                return kw  # return the clicked keyword
            except Exception as e:
                print(f"[warn] Failed to click '{kw}':", e)
    return None


async def detect_expand_buttons_in_page(page, auto_click=True, max_clicks=3):
    keywords = get_japanese_expand_keywords()
    priority_keywords = get_priority_expand_keywords()
    found = []

    # Collect all matches
    for kw in keywords:
        locator = page.locator(f"text={kw}")
        if await locator.count():
            found.append(kw)

    if auto_click:
        clicked_kw = await try_click_keywords(page, priority_keywords, max_clicks)
        if not clicked_kw:
            fallback_keywords = [kw for kw in keywords if kw not in priority_keywords]
            await try_click_keywords(page, fallback_keywords, max_clicks)

    return found
