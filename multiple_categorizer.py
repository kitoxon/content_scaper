from dotenv import load_dotenv
load_dotenv()
import pandas as pd
import time
import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
import backoff
import argparse
import glob
# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("article_categorizer.log"), logging.StreamHandler()]
)
logger = logging.getLogger()

# OpenAI API
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
@backoff.on_exception(backoff.expo, Exception, max_tries=5)
def safe_gpt_request(title, memo):
    return is_related_to_team(title, memo)
# Category classification logic
def is_related_to_team(title: str, memo: str,) -> dict:
    system_prompt = f"""
    あなたは日本のプロ野球を専門とするスポーツ記者アシスタントです。

    以下に示す記事のタイトルと本文を読み、記事がどのカテゴリに最も適切に属するかを判断してください。選択できるカテゴリは1つのみです。

    ＜基本＞
    タイトルの文言で判断
    　→タイトルでわからないものは本文確認

    ＜カテゴリ＞
    ・1軍球場
    ・2軍球場
    ・事業施策
    ・監督
    ・選手特集
    ・チーム施策
    ・試合結果
    ・佐々木朗希選手
    ・その他

    ＜優先順位＞
    ①1軍球場移転系→「1軍球場」
    　※選手、監督のコメントが入っていても1軍球場に入れてOK
    　※行政系、選挙系のタイトルに含まれる場合があるので注意
    ZOZOマリンスタジアム

    ②2軍球場移転系→「2軍球場」
    　※選手、監督のコメントが入っていても1軍球場に入れてOK
    　※行政系、選挙系のタイトルに含まれる場合があるので注意
    ロッテ浦和球場

    ③千葉ロッテ主催イベント、2軍施設移転系→「事業施策」
    　※他球団イベントは「その他」

    ④吉井監督談話系→「監督」
    　※選手名が入ってる場合も吉井監督談があれば「監督」
    　※他チーム監督は無視

    ⑤千葉ロッテ選手名→「選手特集」　
    　※下記のようにタイトルに選手名が入ってなくても選手話題である場合は「選手特集」へ
    　　それっぽいタイトルのものは記事内容を確認して千葉ロッテ選手が入ってれば該当
    　　「19歳捕手の活躍」➡寺地選手のこと
    　　「白熱する新人王争い」➡西川選手話題
    　※予告先発や登録抹消等事務的な情報は基本該当しないが、選手のコメントや詳細な選手の説明等があれば「選手特集」でＯＫ

    ⑥千葉ロッテ選手の登録抹消、一軍登録情報、スタッフ情報、強化器具導入等→「チーム施策」
    　※記事の内容を確認し選手のコメントや詳細な選手の説明等があれば「選手特集」へ

    ⑦試合結果に関するもの→「試合結果」
    　※主に対戦相手として千葉ロッテが登場する、事務的なスコア情報などが該当
    　　千葉ロッテ選手名がタイトルに入っていれば「選手関連」
    　※予告先発等未来の試合情報は「その他」

    ⑧佐々木朗希選手、メジャーリーグ系→「佐々木朗希選手」
    　※ロッテ選手、監督の談話に部分的に入るのみであれば対象外

    ⑨予告先発等未来の試合情報、他球団情報（単なる対戦相手としてロッテが登場）→「その他」
    　※音楽イベント等非野球記事であれば内容確認
    　　➡ZOZOマリンスタジアム関連であれば「その他」でＯＫ
    　　　それも関係なければロッテ関連記事ではないので削除



    【出力フォーマット】
    カテゴリ: <<カテゴリ名>>
    理由: <<分類した理由を簡潔に日本語で説明>>

    記事タイトル: {title}

    記事内容: {memo}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0,
        )
        time.sleep(0.5)
        raw = response.choices[0].message.content.strip()
        raw_lines = raw.splitlines()
        cat_line = next((l for l in raw_lines if "カテゴリ" in l), "")
        reason_line = next((l for l in raw_lines if "理由" in l), "")
        category = cat_line.split(":", 1)[-1].strip() if ":" in cat_line else "不明"
        reason = reason_line.split(":", 1)[-1].strip() if ":" in reason_line else "理由の取得に失敗"
        return {
            "category": category,
            "category_reason": reason
        }
    except Exception as e:
        logger.error(f"GPT error: {e}")
        return {"category": "不明", "category_reason": "GPTエラー"}

# Process a single CSV file
def process_file(input_path: str, max_rows: int = None):
    try:
        df = pd.read_csv(input_path, encoding="utf-8")

        df = df.iloc[7000:]

        if max_rows:
            df = df.head(max_rows)

        logger.info(f"Loaded {len(df)} articles from {input_path}")
        results = []
        for idx, row in df.iterrows():
            title = row.get('記事タイトル', '')
            memo = row.get('content', '')
            logger.info(f"Processing {os.path.basename(input_path)} [{idx+1}/{len(df)}]")

            meta = safe_gpt_request(title, memo)
            results.append({
                "category": meta["category"],
                "category_reason": meta["category_reason"]
            })

        df["カテゴリ"] = [r["category"] for r in results]
        df["カテゴリ理由"] = [r["category_reason"] for r in results]
        output_path = input_path.replace(".csv", "_categorized1.csv")
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        logger.info(f"✅ Saved categorized data to {output_path}")
    except Exception as e:
        logger.error(f"❌ Failed to process {input_path}: {e}")

# Main runner for folder
def run_on_folder(folder_path: str, max_workers: int = 2, max_rows: int = None):
    # Find all CSVs starting with 'lotte_'
    csv_files = glob.glob(os.path.join(folder_path, "lotte_5_18~5_24_output.csv"))


    # Combine: run others first, then the deferred file last
    file_order = sorted(csv_files, key=os.path.getmtime)

    logger.info(f"Found {len(file_order)} CSV files to process in {folder_path}...")

    # Use ThreadPoolExecutor but submit the deferred file LAST
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_file, path, max_rows) for path in file_order]
        for future in as_completed(futures):
            pass  # processing is logged inside

# Usage
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=str, default="outputs")
    parser.add_argument("--max_rows", type=int, default=None)
    args = parser.parse_args()

    run_on_folder(args.folder, max_workers=2, max_rows=args.max_rows)
