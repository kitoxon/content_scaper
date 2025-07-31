import os
import glob
import pandas as pd
from scraper import get_article_text
from dynamic_scraper import scrape_with_playwright
import logging

# === CONFIG ===
INPUT_DIR = "outputs"
OUTPUT_DIR = "fixed_outputs"
LOG_PATH = "rescrape_mojibake.log"
TEXT_COLUMNS = ["content"]
URL_COLUMN = "記事URL"
GARBLED_MARKERS = ["ã", "�", "å", "ç", "é"]

# Setup logging
logging.basicConfig(
    filename=LOG_PATH,
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

def is_garbled(text):
    return isinstance(text, str) and any(x in text for x in GARBLED_MARKERS)

def re_scrape(url):
    result = get_article_text(url)
    if result["status"] == "Dynamic Needed":
        result = scrape_with_playwright(url)
    return result

os.makedirs(OUTPUT_DIR, exist_ok=True)
files = glob.glob(os.path.join(INPUT_DIR, "giants_tokyo_dome*.csv"))

for input_file in files:
    base_name = os.path.basename(input_file)
    output_file = os.path.join(OUTPUT_DIR, f"fixed_{base_name}")

    logging.info(f"🟡 Processing: {base_name}")
    df = pd.read_csv(input_file, encoding="utf-8-sig")

    garbled_mask = df[TEXT_COLUMNS].apply(lambda col: col.apply(is_garbled)).any(axis=1)
    df_garbled = df[garbled_mask].copy()
    df_clean = df[~garbled_mask].copy()

    for idx, row in df_garbled.iterrows():
        url = row.get(URL_COLUMN, "")
        if not url or not isinstance(url, str):
            continue
        result = re_scrape(url)
        df_garbled.at[idx, "content"] = result.get("content", "")
        status = result.get("status")
        logging.info(f"🔧 Repaired in {base_name}: {url} - {status}")

    df_fixed = pd.concat([df_clean, df_garbled]).sort_index()
    df_fixed.to_csv(output_file, index=False, encoding="utf-8-sig")
    logging.info(f"✅ Finished: {output_file}")

print("🎉 All Lotte files processed.")
