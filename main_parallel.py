import os
import time
import glob
import gc
import logging
import argparse
import unicodedata
import jaconv
import re
import pandas as pd
import concurrent.futures
from difflib import get_close_matches

from scraper import get_article_text
from determine_content import check_article_relation_openai
from calculate_weight import estimate_weight
from dynamic_scraper import scrape_with_playwright

# Constants
LOGIN_INDICATORS = ["ログイン", "会員限定", "有料", "登録してください"]
NOT_FOUND_INDICATORS = ["404", "ページが見つかりません", "記事が存在しません", "not found"]
DEFAULT_TEAMS = ["china", "giants", "hanshin", "rakuten", "seibu", "yakult", "hawks", "hiroshima", "nippon", "oryx", "dena", "lotte"]
CHUNKSIZE = 100
LOG_DIR = "logs_july"
OUTPUT_DIR = "outputs_july"
CHUNK_DIR = "chunks_july"
MAX_TEST_ROWS = 100

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Utility Functions
def detect_status(title: str, content: str) -> str:
    combined = (title or "") + (content or "")
    if any(keyword in combined for keyword in LOGIN_INDICATORS):
        return "🔒 Login Required"
    if any(keyword in combined.lower() for keyword in NOT_FOUND_INDICATORS):
        return "❌ Article Not Found"
    if not content.strip():
        return "❌ No Content"
    return "✅ Success"

def fix_mojibake(text: str) -> str:
    try:
        return text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

def normalize_title(title: str) -> str:
    title = title.strip()
    title = jaconv.z2h(title, kana=False, digit=True, ascii=True)  # half-width normalize
    title = unicodedata.normalize("NFKC", title)  # normalize symbols
    title = title.replace("　", " ")  # full-width space to ASCII space
    return title
def extract_team_keywords_from_excel(file_path: str) -> list:
    df = pd.read_excel(file_path, header=None)
    keyword_str = df.iloc[0, 2]
    keywords = re.findall(r"\(\d+\)\s*([^,]+)", keyword_str)
    return [kw.strip() for kw in keywords]
def match_team_from_keywords(team_keywords: list, csv_path) -> list:
    df = pd.read_csv(csv_path)
    matched = set()

    for col in df.columns:
        if col in team_keywords:
            matched.add(col)
        else:
            aliases = df[col].dropna().astype(str).tolist()
            for alias in aliases:
                if any(kw in alias for kw in team_keywords):
                    matched.add(col)
                    break

    return list(matched)
def match_ng_team_keywords(team_keywords: list, csv_path) -> list:
    df = pd.read_csv(csv_path)
    matched_keywords = []

    for team in team_keywords:
        if team in df.columns:
            matched_keywords.extend(df[team].dropna().tolist())

    return matched_keywords
def scrape_article(url: str) -> dict:
    result = get_article_text(url)
    if result["status"] == "Dynamic Needed":
        result = scrape_with_playwright(url)
    return result or {"status": "❌ Failed to scrape", "title": "", "content": ""}

# Main Processing Function
def scrape_chunk_safe(input_file: str, output_csv: str, sleep_between: float = 0.5, logger=None):
    # if os.path.exists(output_csv):
    #     os.remove(output_csv)
    total_rows = pd.read_excel(input_file, usecols=[0], header=2).shape[0]

    current_row = 0
    score_cache = {}
    team_keywords = extract_team_keywords_from_excel(input_file)
    keyword_csv_path = "web_keywords.csv"
    ng_keyword_csv_path = "ng_team_keywords.csv"
    matched_teams = match_team_from_keywords(team_keywords, keyword_csv_path)
    ng_matched_teams = match_ng_team_keywords(matched_teams, ng_keyword_csv_path)

    df = pd.read_excel(input_file, header=2)
    # Step 1: Load previous progress
    resume_index = 0

    if os.path.exists(output_csv):
        try:
            prev_df = pd.read_csv(output_csv, encoding="utf-8-sig")
            resume_index = len(prev_df)
            if logger:
                logger.info(f"🔁 Resuming from row {resume_index}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load existing output: {e}")

    df = df.iloc[resume_index:]  # Step 2: Skip processed rows
    chunk_size = 1000
    for i in range(0, len(df), chunk_size):
        chunk = df.iloc[i:i+chunk_size].copy()
        chunk = chunk.assign(
            status="", content="", 重みスコア=None, 算出メディア価値=None,
            GPT出力内容=None, タイトルのみで評価したか=None, is_related="", reasoning=""
        )

        for idx, row in chunk.iterrows():
            current_row += 1
            url = row.get("記事URL", "")
            ad_value = float(row["広告換算値"])

            try:
                result = scrape_article(url)
                title = row.get("記事タイトル", "") or result.get("title", "")
                content = fix_mojibake(result.get("content", ""))
                normalized_title = normalize_title(title)
                analysis_text = f"タイトル: {normalized_title}\n\n{content}"
                if logger:
                    logger.info(f"🔢 Row {resume_index + current_row}/{total_rows} | 📰 {normalized_title}")


                if normalized_title in score_cache:
                    weight, feedback, fallback = score_cache[normalized_title]
                    logger.info("🔁 Used cached score")
                else:
                    similar = get_close_matches(normalized_title, score_cache.keys(), n=1, cutoff=0.95)
                    if similar:
                        weight, feedback, fallback = score_cache[similar[0]]
                        logger.info(f"⚠️ Used similar title: {similar[0]}")
                    else:
                        weight, feedback, fallback = estimate_weight(normalized_title, content)
                        score_cache[normalized_title] = (weight, feedback, fallback)
                        logger.info("💬 Scored via GPT")
                        time.sleep(1)

                chunk.at[idx, "重みスコア"] = weight
                chunk.at[idx, "算出メディア価値"] = round(ad_value * weight)
                chunk.at[idx, "GPT出力内容"] = feedback
                chunk.at[idx, "タイトルのみで評価したか"] = fallback
                chunk.at[idx, "status"] = detect_status(title, content)
                chunk.at[idx, "content"] = content
                is_related, reason = check_article_relation_openai(analysis_text, matched_teams[0], team_keywords, ng_matched_teams)
                time.sleep(1)
                chunk.at[idx, "is_related"] = is_related
                chunk.at[idx, "reason"] = reason
            except Exception as e:
                chunk.at[idx, "status"] = f"❌ Error: {e}"
                chunk.at[idx, "content"] = ""
                if logger:
                    logger.error(f"Error at row {current_row}: {e}")

            time.sleep(sleep_between)

        mode = 'a' if os.path.exists(output_csv) else 'w'
        chunk.to_csv(output_csv, index=False, encoding="utf-8-sig", mode=mode, header=(mode == 'w'))
        del chunk
        gc.collect()

# Orchestration
def run_team(team: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log_path = os.path.join(LOG_DIR, f"{team}.log")
    logger = logging.getLogger(team)
    if not logger.handlers:
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(file_handler)

    input_files = glob.glob(os.path.join(CHUNK_DIR, f"{team}_*.xlsx"))
    for input_file in input_files:
        part_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(OUTPUT_DIR, f"{part_name}_output.csv")
        scrape_chunk_safe(input_file, output_file, logger=logger)

def main(teams):
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        executor.map(run_team, teams)
    print("🎉 All teams scraping completed!")

# Entry Point
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape articles for specified teams.")
    parser.add_argument("--teams", nargs="+", default=DEFAULT_TEAMS, help="List of team names to scrape")
    args = parser.parse_args()
    main(args.teams)
