import pandas as pd
from openai import OpenAI
import os
import re
from tqdm import tqdm
import jaconv
import unicodedata
from difflib import get_close_matches
from concurrent.futures import ThreadPoolExecutor, as_completed

# === 🔐 OpenAI Setup ===
client = OpenAI(api_key='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')  # or replace with your actual key

# === 📁 Folder Setup ===
CHUNKS_FOLDER = "chunks"
OUTPUT_FOLDER = "output"
LOGS_FOLDER = "logs"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(LOGS_FOLDER, exist_ok=True)

def normalize_title(title: str) -> str:
    title = title.strip()

    # Normalize full-width to half-width for ASCII & digits
    title = jaconv.z2h(title, kana=False, digit=True, ascii=True)

    # Unicode normalization to collapse similar symbols (like − vs -)
    title = unicodedata.normalize("NFKC", title)

    # Replace full-width space with ASCII space
    title = title.replace("　", " ")

    return title
# === 📦 Fallback Detection ===
def is_garbage_content(text: str) -> bool:
    if not text or len(text.strip()) < 100:
        return True
    garbage_keywords = ["ご購読", "会員登録", "天気", "お悔やみ", "写真販売", "新着", "動画"]
    nav_count = sum(k in text for k in garbage_keywords)
    if nav_count > 10:
        return True
    if text.count("。") < 3 and text.count("\n") < 2:
        return True
    kanji_count = len(re.findall(r'[一-龥]', text))
    if kanji_count / max(len(text), 1) < 0.05:
        return True
    return False

# === 🧠 Prompt Generation ===
def build_prompt(title: str, content: str, fallback: bool = False) -> str:
    if fallback:
        return f"""以下は日本のスポーツ記事のタイトルです：
「{title}」

このタイトルから、以下の4項目を推定してください。
出力形式は例に従ってください。スコアは必ず最初に決定し、指定された選択肢の中から1つを選んでください。

【スコアの選択肢】：0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0

【出力形式の例】：
例1：
1. 試合結果
2. 高
3. 2.0
4. スター選手の活躍で話題性が非常に高い

例2：
1. 試合結果
2. 低
3. 0.6
4. 選手の知名度・注目度が低いため

【出力対象のタイトル】：
「{title}」

出力フォーマットに従って、次の4項目を推定してください：
1. 記事の内容カテゴリ（例：試合結果、インタビュー、雑記など）
2. 一般の関心度（高・中・低）
3. メディア価値の重みスコア（上記の選択肢から1つだけ）
4. スコアの理由（3のスコアに合う簡潔な理由。30文字以内）"""

    else:
        return f"""以下は日本のスポーツ記事のタイトルと本文です：

タイトル：
「{title}」

本文（一部）：
{content[:2000]}

この内容に基づいて、以下の4項目を推定してください。
スコアは必ず先に決定し、指定された選択肢の中から1つを選んでください。

【スコアの選択肢】：0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0

【出力形式の例】：
1. 試合結果
2. 高
3. 2.0
4. スター選手の活躍で話題性が非常に高い

【出力対象のタイトルと本文】：
1. 記事の内容カテゴリ（例：試合結果、インタビュー、雑記など）
2. 一般の関心度（高・中・低）
3. メディア価値の重みスコア（上記の選択肢から1つだけ）
4. スコアの理由（3のスコアに合う簡潔な理由。30文字以内）"""


# === 🔁 GPT Weight Estimation ===
def estimate_weight(title: str, content: str):
    fallback = is_garbage_content(content)
    prompt = build_prompt(title, content, fallback=fallback)

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "あなたは日本のスポーツメディア分析の専門家です。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        reply = response.choices[0].message.content.strip()

        # Try multiple regex patterns in order of expected reliability
        patterns = [
            r'3\.\s*([0-9]+\.\d+)',  # Most structured format
            r'メディア価値の重みスコア[：:]\s*([0-9]+\.\d+)',  # Alt format
            r'スコア[：:]\s*([0-9]+\.\d+)'  # Looser fallback
        ]

        match = None
        for pattern in patterns:
            match = re.search(pattern, reply)
            if match:
                break

        if match:
            weight = float(match.group(1))
            weight = round(weight, 1)
        else:
            weight = 1.0  # Fallback to neutral value if parsing fails

        return weight, reply, fallback

    except Exception as e:
        print(f"⚠️ GPT error on article: {title[:30]} – {e}")
        return 1.0, "error", fallback



# === 🎯 Single file processor ===
def process_file(filename: str):
    filepath = os.path.join(CHUNKS_FOLDER, filename)
    df = pd.read_csv(filepath)
    df_filtered = df.copy()

    score_cache = {}
    logs = []

    # === File-level logging ===
    logs.append(f"📄 Processing file: {filename}")
    logs.append(f"📊 Total rows: {len(df_filtered)}")
    df_filtered["重みスコア"] = None
    df_filtered["算出メディア価値"] = None
    df_filtered["GPT出力内容"] = None
    df_filtered["タイトルのみで評価したか"] = None

    out_name = os.path.splitext(filename)[0]
    output_path = os.path.join(OUTPUT_FOLDER, f"{out_name}_scored.csv")
    log_path = os.path.join(LOGS_FOLDER, f"{out_name}.log")

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"📄 Processing file: {filename}\n")
        log_file.write(f"📊 Total rows: {len(df_filtered)}\n\n")

        for idx in df_filtered.index:
            try:
                row = df_filtered.loc[idx]
                raw_title = str(row["記事タイトル"])
                normalized_title = normalize_title(raw_title)
                content = str(row.get("content", ""))
                price = float(row["広告換算値"])

                log_file.write(f"🔢 Row {idx + 1}/{len(df_filtered)}\n")
                log_file.write(f"📰 Title: {normalized_title}\n")

                if normalized_title in score_cache:
                    weight, feedback, fallback = score_cache[normalized_title]
                    log_file.write("🔁 Reused cached score\n")
                else:
                    close_matches = get_close_matches(normalized_title, score_cache.keys(), n=1, cutoff=0.95)
                    if close_matches:
                        similar_title = close_matches[0]
                        weight, feedback, fallback = score_cache[similar_title]
                        log_file.write(f"⚠️ Using score from similar title: {similar_title}\n")
                    else:
                        weight, feedback, fallback = estimate_weight(normalized_title, content)
                        score_cache[normalized_title] = (weight, feedback, fallback)
                        log_file.write("💬 Scored via GPT\n")

                log_file.write(f"✅ Score: {weight} ({'fallback' if fallback else 'content'})\n\n")

                df_filtered.at[idx, "重みスコア"] = weight
                df_filtered.at[idx, "算出メディア価値"] = round(price * weight)
                df_filtered.at[idx, "GPT出力内容"] = feedback
                df_filtered.at[idx, "タイトルのみで評価したか"] = fallback

            except Exception as e:
                log_file.write(f"❌ Error on row {idx}: {e}\n\n")

        df_filtered.to_csv(output_path, index=False, encoding="utf-8-sig")

    return f"✅ Finished {filename}"

# === 🚀 Run in parallel ===
all_files = [f for f in os.listdir(CHUNKS_FOLDER) if f.endswith(".csv")]
with ThreadPoolExecutor(max_workers=6) as executor:
    futures = {executor.submit(process_file, file): file for file in all_files}
    for future in as_completed(futures):
        print(future.result())
