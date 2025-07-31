from openai import OpenAI
client = OpenAI(api_key='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')

def is_article_related(text, team, max_retries: int = 2):
    if not text or not isinstance(text, str) or len(text.strip()) == 0:
           return None, "❌ 入力テキストが空または無効です。"
    prompt = f"""
    以下の記事が、日本のプロ野球チーム「{team}」に関連しているかどうかを判定してください。

    ✅ 判定基準：

    - 野球の試合、選手、監督、チーム運営、スポンサー活動など、「{team}」に関係する内容が含まれている場合 → "yes"

    - 試合の対戦相手として「{team}」が登場する場合（例：○○対{team}、△△が{team}と対戦） → "yes"

    - 他球団の試合や選手に関する記事でも、その中に「{team}」との関係性（対戦・移籍・コメント等）がある場合 → "yes"

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
            if attempt == max_retries:
                return None, f"API error after {max_retries + 1} attempts: {str(e)}"
