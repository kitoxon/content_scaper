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

CHUNKS_FOLDER = "teams_split_with_keywords/"
OUTPUT_FOLDER = "newspaper_output"
LOGS_FOLDER = "news_paper_logs"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(LOGS_FOLDER, exist_ok=True)




def check_article_relation_openai(article_title: str, text: str, team_name: str, max_retries: int = 2) -> Tuple[bool, str]:
    if not text or not isinstance(text, str) or len(text.strip()) == 0:
           return None, "❌ 入力テキストが空または無効です。"
    prompt = f"""
    以下の記事が、日本のプロ野球チーム「{team_name}」に関連しているかどうかを判定してください。

    ■ 入力情報：
    - 記事タイトル：{article_title}
    - キーワード：{text}

    ■ 判定基準：

    ✅ 関連あり（"yes"）と判断するケース：
    - 記事が「{team_name}」に関連する野球の試合・選手・監督・スポンサー活動・チーム運営などに言及している場合
    - 「{team_name}」が対戦相手として登場する場合（例：「○○対{team_name}」「{team_name}との試合」など）
    - 他球団に関する話題でも、「{team_name}」との関係（コメント、移籍、過去の対戦など）が含まれている場合

    ❌ 関連なし（"no"）と判断するケース：
    - 同名の企業や商業施設（例：「ロッテ百貨店」「阪神電鉄」「中日新聞」など）に関する記事
    - 「{team_name}」と同じ単語が登場していても、プロ野球と無関係な話題の場合
    - スマホ事業、イベント、観光施設など、野球とは無関係な内容

    ■ 注意事項：
    - 本文がない場合は「記事タイトル」と「キーワード」からできる限り判断してください。
    - 出力は**以下のフォーマット**で必ず返してください：

    【出力形式】
    yes または no
    その理由を簡潔な日本語で1〜2文で説明してください。

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

    title = row.get('記事名', '')
    content = row.get('keyword1', '')
    content1 = row.get('keyword2', '')
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
        analysis_text = f"{content}\n{content1}"

        is_related, reason = check_article_relation_openai(title, analysis_text, team)

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
            title = str(row.get('記事名', ''))[:30]
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
