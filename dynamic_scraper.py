from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re
import asyncio
from utils import detect_expand_buttons_in_page

async def scrape_async(url: str, headless: bool = True) -> dict:
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled"
                ]
            )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/114.0.0.0 Safari/537.36"
                )
            )

            page = await context.new_page()

            # Block unnecessary resources
            async def block_unwanted(route, request):
                if request.resource_type in ["image", "font", "stylesheet"]:
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", block_unwanted)

            # Disable service workers
            await page.add_init_script("navigator.serviceWorker.register = () => {}")

            await page.goto(url, timeout=20000)

            expand_labels = await detect_expand_buttons_in_page(page, auto_click=True)
            if expand_labels:
                print("🔍 Expand buttons clicked:", expand_labels)
                await asyncio.sleep(1.0)

            # Controlled scrolling (optional)
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(0.4)

            html = await page.content()

    except Exception as e:
        return {"status": f"Error: {str(e)}", "title": "", "content": ""}
    finally:
        if browser:
            await browser.close()

    # Parse content with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title else ""

    # Mixi-specific
    if "mixi.jp" in url:
        main_div = soup.find("div", class_="newsArticle") or soup.find("div", class_="contents")
        if main_div:
            return {"status": "Success", "title": title, "content": main_div.get_text("\n", strip=True)}

    # Livedoor-specific
    if "livedoor.com" in url:
        article_body = soup.find("div", class_="articleBody")
        if article_body:
            return {"status": "Success", "title": title, "content": article_body.get_text("\n", strip=True)}

    # General fallback parsing
    content = None
    for tag in ["article", "main", "section"]:
        candidate = soup.find(tag)
        if candidate and len(candidate.get_text()) > 300:
            content = candidate
            break

    if not content:
        candidates = soup.find_all(["div", "section"], recursive=True)
        scored = [(len(c.get_text()), c) for c in candidates if len(c.get_text()) > 300]
        if scored:
            content = max(scored)[1]

    if not content:
        paragraphs = soup.find_all("p")
        text = "\n".join(p.get_text(strip=True) for p in paragraphs)
    else:
        text = content.get_text("\n", strip=True)

    clean_text = re.sub(r"\n{2,}", "\n", text).strip()
    return {"status": "Success", "title": title, "content": clean_text}


def scrape_with_playwright(url: str, headless: bool = True):
    return asyncio.run(scrape_async(url, headless=headless))
