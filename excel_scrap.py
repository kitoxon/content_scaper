import pandas as pd
import time
import os
import glob
import concurrent.futures
import logging
import gc
import argparse
from scraper import get_article_text
from dynamic_scraper import scrape_with_playwright
from chatgpt_checker import is_article_related
from gemini_checker import article_check

# Constants
LOGIN_INDICATORS = ["ログイン", "会員限定", "有料", "登録してください"]
NOT_FOUND_INDICATORS = ["404", "ページが見つかりません", "記事が存在しません", "not found"]
CHUNKSIZE = 100
LOG_DIR = "logs"
OUTPUT_DIR = "outputs"
CHUNK_DIR = "chunks"

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def detect_status(title: str, content: str) -> str:
    combined = (title or "") + (content or "")
    if any(key in combined for key in LOGIN_INDICATORS):
        return "🔒 Login Required"
    if any(key in combined.lower() for key in NOT_FOUND_INDICATORS):
        return "❌ Article Not Found"
    if not content.strip():
        return "❌ No Content"
    return "✅ Success"

def fix_mojibake(text: str) -> str:
    try:
        return text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

def scrape_article(url: str) -> dict:
    result = get_article_text(url)
    if result["status"] == "Dynamic Needed":
        result = scrape_with_playwright(url)
    return result or {"status": "❌ Failed to scrape", "title": "", "content": ""}

def scrape_chunk_safe(df: pd.DataFrame, output_csv: str, team: str, sleep_between: float = 0.5, logger=None):
    if os.path.exists(output_csv):
        os.remove(output_csv)

    total_rows = len(df)
    current_row = 0
    df["status"] = ""
    df["content"] = ""
    df["is_related"] = ""
    df["reasoning"] = ""

    for idx, row in df.iterrows():
        current_row += 1
        url = row.get("記事URL", "")
        try:
            result = scrape_article(url)
            title = row.get("記事タイトル", "") or result.get("title", "")
            content = fix_mojibake(result.get("content", ""))
            analysis_text = f"タイトル: {title}\n\n{content}"
            result_flag, reasoning = is_article_related(title, content, team)
            is_related, reason = article_check(analysis_text, team)
            status = detect_status(title, content)
            df.at[idx, "status"] = status
            df.at[idx, "content"] = content
            df.at[idx, "is_related"] = result_flag
            df.at[idx, "reasoning"] = reasoning
            time.sleep(sleep_between)
            if logger:
                logger.info(f"{team} [{current_row}/{total_rows}] {url} - {status}")
        except Exception as e:
            df.at[idx, "status"] = f"❌ Error: {str(e)}"
            df.at[idx, "content"] = ""
            if logger:
                logger.error(f"{team} [{current_row}/{total_rows}] {url} - Error: {e}")
        time.sleep(sleep_between)
        if idx % 10 == 0:
            print(f"Processed {current_row}/{total_rows} for team {team}")

    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    gc.collect()

def run_team_from_sheet(sheet_name: str, df: pd.DataFrame, base_filename: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log_file_path = os.path.join(LOG_DIR, f"{sheet_name}.log")
    logger = logging.getLogger(sheet_name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(log_file_path, encoding='utf-8')
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)

    output_file = os.path.join(OUTPUT_DIR, f"{os.path.splitext(base_filename)[0]}_{sheet_name}_output.csv")
    scrape_chunk_safe(df, output_file, team=sheet_name, logger=logger)

def main():
    parser = argparse.ArgumentParser(description="Scrape articles from all xlsx files in chunks folder.")
    args = parser.parse_args()

    excel_files = glob.glob(os.path.join(CHUNK_DIR, "*.xlsx"))
    if not excel_files:
        print("❌ No Excel files found in chunks/")
        return

    for file in excel_files:
        xls = pd.ExcelFile(file)
        for sheet_name in xls.sheet_names:
            print(f"📄 Processing sheet '{sheet_name}' in file '{file}'")
            df = xls.parse(sheet_name)
            run_team_from_sheet(sheet_name, df, os.path.basename(file))

    print("🎉 All teams from Excel files processed!")

if __name__ == "__main__":
    main()
