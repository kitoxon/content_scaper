from openai import OpenAI
import pandas as pd
import json
import logging
import sys
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('run_ps_ng.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

api_key = "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"
client = OpenAI(api_key=api_key)

def analyze_media_value(title: str, content: str, target_team: str) -> dict:
    system_prompt = f"""
    あなたは日本のプロ野球メディアにおける報道価値を評価する専門家です。

    以下の記事タイトルと本文をもとに、対象チーム「{target_team}」の試合結果（win, loss, draw）を判断し、
    その結果に基づいてメディア価値スコア（0〜10）を決定してください。

    本文がない場合はタイトルのみで判断してください。

    出力は次の形式の JSON にしてください：

    {{
    "result": "win",
    "media_value_score": 9,
    "reason": "劇的なサヨナラ勝ちが強調されており、注目度が非常に高いため高スコア。"
    }}"""
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
        ],
        temperature=0,
    )
    content = response.choices[0].message.content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "result": "",
            "media_value_score": 0,
            "reason": f"JSON解析失敗: {content}"
        }

def analyze_article(title: str, content: str, target_team: str, category: str):
    system_prompt = (
        f"""あなたは日本のプロ野球記事の感情分析を専門とするアナリストです。

        以下の記事について、感情分析を行ってください：

        **記事タイトル：** {title}
        **記事本文：** {content}
        **カテゴリ：** {category}  # 事業施策/1軍球場/2軍球場/その他
        **対象チーム：** 千葉ロッテマリーンズ

        ## 感情分析基準：

        ### カテゴリ別の判定ポイント：

        **「事業施策」の場合：**
        - ポジティブ：イベント成功、新施策発表、ファンサービス向上、収益改善等
        - ネガティブ：イベント中止、施策の問題、批判、経営難等

        **「1軍球場」の場合：**
        - ポジティブ：改修・改善、設備向上、利便性アップ、好評価等
        - ネガティブ：設備問題、移転反対、工事遅延、批判等

        **「2軍球場」の場合：**
        - ポジティブ：移転決定、新設備、地域歓迎、環境改善等
        - ネガティブ：移転問題、反対意見、設備不足、懸念等

        **「その他」の場合：**
        - ポジティブ：好試合予想、選手好調、期待感等
        - ネガティブ：不安要素、問題発生、批判的報道等
        ・「その他」：他球団イベント施策情報（始球式、プレゼントなど）はニュートラルへ
        ・「その他」：他球団選手情報はニュートラルへ
        ・その他：音楽イベントはニュートラルへ
        ・事業施策：ロッテイベント施策情報（始球式、プレゼントなど）は基本ポジティブへ
        　　　　　　※イベントへの批判があればネガティブ
        ・1軍球場／2軍球場：公式リリースっぽいものは基本ポジティブへ
        　　　　　　　　　　※ポジネガ両論併記した論評や知事の談話はニュートラルへ

        ## 判定：**ポジティブ／ネガティブ／ニュートラル**

        ## 出力形式（JSON）：
        ```json
        {{
          "sentiment": "ポジティブ|ネガティブ|ニュートラル",
          "confidence": 0.0-1.0,
          "reason": "判断理由を具体的に説明",
          "key_phrases": ["感情判断の根拠となった重要語句"]
        }}
        """
    )

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
        ],
        temperature=0,
    )
    content = response.choices[0].message.content.strip()
    cleaned = re.sub(r"```json|```", "", content).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "sentiment": "",
            "confidence": 0.0,
            "reason": f"JSON形式で出力されませんでした: {content}",
            "key_phrases": []
        }

if __name__ == "__main__":
    input_csv = "lotte_pos_neg_input1.csv"   # 🔁 Your input CSV filename
    output_csv = "lotte_pos_neg_output1.csv"
    target_team = "ロッテ"

    df = pd.read_csv(input_csv, encoding='utf-8')
    results = []

    for idx, row in df.iterrows():
        title = row.get('記事タイトル', '')
        content = str(row.get('content', '') or '')
        category = row.get('カテゴリ', '')
        if not title.strip():
            continue  # Skip empty titles

        logger.info("[%d/%d] 分析中: %s", idx+1, len(df), title)

        meta_data = analyze_article(title, content, target_team, category)

        result_row = {
            "title": title,
            "content": content,
            "sentiment": meta_data.get("sentiment", ""),
            "confidence": meta_data.get("confidence", ""),
            "reason": meta_data.get("reason", ""),
            "key_phrases": meta_data.get("key_phrases", [])
        }
        results.append(result_row)

    output_df = pd.DataFrame(results)
    output_df.to_csv(output_csv, index=False, encoding='utf-8-sig')
    logger.info("✅ 結果を保存しました: %s", output_csv)
