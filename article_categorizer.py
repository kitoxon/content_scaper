from openai import OpenAI
import json
import re
from typing import Optional, Any
import pandas as pd
import time
import logging
# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("article_categorizer.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()
api_key = "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"
client = OpenAI(api_key=api_key)

def is_related_to_team(title: str, memo: str) -> dict:
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
    ・試合結果/1軍
    ・試合結果/2軍
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

    ⑦試合結果に関するもの→「試合結果/1軍」
    　※主に対戦相手として千葉ロッテが登場する、1軍戦の事務的なスコア情報などが該当
    　　千葉ロッテ選手名がタイトルに入っていれば「選手関連」
    　※予告先発等未来の試合情報は「その他」
    ⑧試合結果に関するもの→「試合結果/2軍」
    　※主に対戦相手として千葉ロッテが登場する、2軍戦の事務的なスコア情報などが該当
    　　千葉ロッテ選手名がタイトルに入っていれば「選手関連」
    　※予告先発等未来の試合情報は「その他」
    ⑨佐々木朗希選手、メジャーリーグ系→「佐々木朗希選手」
    　※ロッテ選手、監督の談話に部分的に入るのみであれば対象外

    ⑩予告先発等未来の試合情報、他球団情報（単なる対戦相手としてロッテが登場）→「その他」
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
            messages=[
                {"role": "system", "content": system_prompt},
            ],
            temperature=0,
        )
        time.sleep(0.5)
        raw = response.choices[0].message.content.strip()

        # パース処理
        category_match = re.search(r"カテゴリ[:：]\s*(.+)", raw)
        reason_match = re.search(r"理由[:：]\s*(.+)", raw)

        return {
            "category": category_match.group(1).strip() if category_match else "不明",
            "category_reason": reason_match.group(1).strip() if reason_match else "理由の取得に失敗"
        }

    except Exception as e:
        print(f"[ERROR] GPT check failed: {e}")
        return {
            "category": "不明",
            "category_reason": "GPTエラー"
        }

def main(input_csv: str, output_csv: str, max_rows: int = None):
    df = pd.read_csv(input_csv, encoding='utf-8')
    if max_rows:
        df = df.head(max_rows)

    results = []
    logger.info(f"Loaded {len(df)} articles from {input_csv}")
    total_articles = len(df)
    for idx, row in df.iterrows():
        title = row.get('記事タイトル', '')
        memo = row.get('content', '')
        is_related = row.get('is_related')
        logger.info(f"Processing article {idx+1}/{total_articles}: {(title or '')[:30]}...")

        if not title or is_related is not True:
            continue

        print(f"[{idx+1}/{len(df)}] 分類中: {title}")
        meta_data = is_related_to_team(title, memo)

        result_row = {
            "memo": memo,
            "title": title,
            "category": meta_data.get("category", ""),
            "category_reason": meta_data.get("category_reason", "")
        }

        results.append(result_row)

    output_df = pd.DataFrame(results)
    output_df.to_csv(output_csv, index=False, encoding='utf-8-sig')
    logger.info(f"✅ Finished file: {input_csv}\n")

if __name__ == "__main__":
    INPUT_CSV = "lotte.csv"
    OUTPUT_CSV = "lotte_categorized.csv"
    MAX_ROWS = None
    main(INPUT_CSV, OUTPUT_CSV, MAX_ROWS)
