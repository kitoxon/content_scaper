import pandas as pd
import google.generativeai as genai
import os
import time
import argparse
import logging
import glob
from typing import Tuple, Dict, Any
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed

import re
# Set up logging

client = OpenAI(api_key='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')

CHUNKS_FOLDER = "chunks"
OUTPUT_FOLDER = "checked_outputs"
LOGS_FOLDER = "logs"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(LOGS_FOLDER, exist_ok=True)


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
    for pattern in patterns:
        text = re.sub(pattern, '', cleaned, flags=re.MULTILINE)
    return text

def check_article_relation_openai(text: str, team_name: str, max_retries: int = 2) -> Tuple[bool, str]:
    if not text or not isinstance(text, str) or len(text.strip()) == 0:
           return None, "❌ 入力テキストが空または無効です。"
    prompt = f"""
    以下の記事が、日本のプロ野球チーム「{team_name}」に関連しているかどうかを判定してください。

    ✅ 判定基準：

    - 野球の試合、選手、監督、チーム運営、スポンサー活動など、「{team_name}」に関係する内容が含まれている場合 → "yes"

    - 試合の対戦相手として「{team_name}」が登場する場合（例：○○対{team_name}、△△が{team_name}と対戦） → "yes"

    - 他球団の試合や選手に関する記事でも、その中に「{team_name}」との関係性（対戦・移籍・コメント等）がある場合 → "yes"

    ❌ 無関係と判断するケース：

    - 同名の企業やブランドに関する話題（例：「ロッテ株式会社」「阪神電鉄」「中日新聞」など）

    - チーム名と同じ単語が出てきても、プロ野球の内容と関係ない場合 → "no"

    - 海外の同名グループや商業施設（例：ロッテ百貨店、阪神梅田本店、ソフトバンクのスマホ事業 など）

    📌 メモ：
    記事本文がない場合は、記事タイトルからできる限り判断してください。

    🔁 出力形式：

    必ず以下の形式で返答してください：

    yes または no（必ずこの2語のいずれかで始める）
    その判断理由を簡潔に日本語で説明してください（1〜2文）


    記事：
    {text[:8000]}
    """


    for attempt in range(max_retries + 1):
        try:
            # Create the model and generate content
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
            )
            result_text = response.choices[0].message.content.strip()

            # Parse the response
            if result_text.lower().startswith("yes"):
                return True, result_text
            elif result_text.lower().startswith("no"):
                return False, result_text
            else:
                # Try to interpret based on Japanese phrasing
                if "関連" in result_text and "ありません" not in result_text and "ない" not in result_text:
                    return True, result_text
                elif "関連" in result_text and ("ありません" in result_text or "ない" in result_text):
                    return False, result_text
                else:
                    return None, "Can't decide: " + result_text

        except Exception as e:
            print(f"⚠️ GPT error on article: {team_name[:30]} – {e}")
            if attempt == max_retries:
                return None, f"API error after {max_retries + 1} attempts: {str(e)}"


def process_article(row: Dict[Any, Any]) -> Dict[str, Any]:
    """Process a single article row and determine if it's related to the team."""
    result = {
        "is_related": None,
        "final_content": "",
        "reason": "",
    }

    title = row.get('記事タイトル', '')
    content = row.get('content', '')
    team = row.get('チーム', '')

    # Skip if no team specified
    if not team:
        result["is_related"] = None
        result["reason"] = "No team specified"
        return result

    # Case 1: We have content to analyze
    if isinstance(content, str) and len(content.strip()) > 20:  # Check if content is non-empty
        # cleaned_content = clean_article_text(content)
        # result["final_content"] = cleaned_content

        # Use combined title and content for analysis
        analysis_text = f"タイトル: {title}\n\n{content}"
        is_related, reason = check_article_relation_openai(analysis_text, team)

        result["is_related"] = is_related
        result["reason"] = reason
    else:
        if title:
            is_related, reason = check_article_relation_openai(f"タイトル: {title}", team)

            result["is_related"] = is_related
            result["reason"] = reason
        else:
            result["is_related"] = None
            result["reason"] = "No title, content, or URL available"

    return result


def process_file(filename: str):
    filepath = os.path.join(CHUNKS_FOLDER, filename)
    output_path = os.path.join(OUTPUT_FOLDER, filename)
    log_path = os.path.join(LOGS_FOLDER, filename.replace(".csv", ".log"))
    df = pd.read_csv(filepath)
    df['is_related'] = None
    df['reason'] = ''
    # df['final_content'] = ''

    # Process each article

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"📄 Processing file: {filename}\n")
        log_file.write(f"📊 Total rows: {len(df)}\n")
        for idx, row in df.iterrows():
            title = str(row.get('記事タイトル', ''))[:30]
            log_file.write(f"\n📰 [{idx+1}/{len(df)}] タイトル: {title}\n")

            try:
                result = process_article(row)
                is_related = result["is_related"]
                reason = result["reason"]

                df.at[idx, 'is_related'] = is_related
                df.at[idx, 'reason'] = reason

                log_file.write(f"   🔍 判定: {is_related} / 理由: {reason}\n")

                if (idx + 1) % 100 == 0:
                    df.to_csv(output_path, index=False, encoding='utf-8-sig')
                    log_file.write(f"💾 中間保存しました ({idx+1}件処理)\n")

                time.sleep(1)

            except Exception as e:
                error_msg = f"❌ エラー (行 {idx}): {str(e)}"
                log_file.write(error_msg + "\n")
                df.at[idx, 'reason'] = error_msg

        # Final save
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        log_file.write(f"\n✅ Finished: {output_path}\n")

        related_count = (df['is_related'] == True).sum()
        not_related_count = (df['is_related'] == False).sum()
        undecided_count = len(df) - related_count - not_related_count

        log_file.write("📋 Summary:\n")
        log_file.write(f"  Related to teams: {related_count}\n")
        log_file.write(f"  Not related: {not_related_count}\n")
        log_file.write(f"  Couldn't decide: {undecided_count}\n")

    return f"📝 Log saved for {filename}"
# === 🚀 Run in parallel ===
all_files = [f for f in os.listdir(CHUNKS_FOLDER) if f.endswith(".csv")]
with ThreadPoolExecutor(max_workers=6) as executor:
    futures = {executor.submit(process_file, file): file for file in all_files}
    for future in as_completed(futures):
        print(future.result())
