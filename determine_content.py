import pandas as pd
import google.generativeai as genai
import os
import time
import argparse
import logging
import glob
from typing import Tuple, Dict, Any
from openai import OpenAI
import re
# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("article_classifier.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()
client = OpenAI(api_key='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')


def setup_gemini_api(api_key: str) -> None:
    genai.configure(api_key=api_key)

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
def load_csv_data(file_path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(file_path, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding="cp932")

    logger.info(f"Loaded {len(df)} articles from {file_path}")
    return df
def extract_main_content(content: str) -> str:
    """Extract and clean the main article body from HTML or noisy content."""
    try:
        # Clean up the content
        cleaned_lines = []
        for line in content.splitlines():
            line = line.strip()
            if line:
                cleaned_lines.append(line)

        cleaned_content = '\n'.join(cleaned_lines)
        if cleaned_content and len(cleaned_content) > 10000:
            logger.info("🔍 Content is long, attempting to extract core article...")
            try:
                cleaned = clean_article_text(cleaned_content)
                if cleaned and len(cleaned) > 500:
                    logger.info(f"✅ Extracted core body length: {len(cleaned)}")
                    return cleaned
                else:
                    logger.warning("⚠️ Extracted content was too short, using original.")
            except Exception as e:
                logger.error(f"❌ Error in clean_article_text: {e}")

        return cleaned_content

    except Exception as e:
        logger.warning(f"Error cleaning content: {str(e)}")
        return content  # Return original content if cleaning fails
def check_article_relation_openai(text: str, team_name: str, team_keywords: list, ng_keywords: list, max_retries: int = 2) -> Tuple[bool, str]:
    if not text or not isinstance(text, str) or len(text.strip()) == 0:
           return None, "❌ 入力テキストが空または無効です。"
    prompt = f"""
    あなたは日本のプロ野球を専門とするスポーツ記者アシスタントです。

    以下の記事が、日本のプロ野球チーム「{team_name}」に関連しているかどうかを判定してください。

    ---

    ✅ 関連ありと判断する条件（"yes"）：
    - 記事に「{team_name}」に関する内容（試合、選手、監督、チーム運営、スポンサー活動など）が含まれている
    - 試合の対戦相手として「{team_name}」が登場している（例：「○○対{team_name}」、「△△が{team_name}と対戦」）
    - 他球団の話題でも「{team_name}」との関係（対戦歴、移籍、コメントなど）が明確に言及されている
    - 試合結果に関する記事で「{team_name}」が登場している
    - 記事にプロ野球に関する内容が含まれている場合

    ❌ 関連なしと判断する条件（"no"）：
    - 「{team_name}」と同名の企業・ブランドに関する話題（例：「ロッテ株式会社」「阪神電鉄」「楽天市場」など）
    - 記事の文脈がプロ野球に関係ないにもかかわらず、「{team_name}」という単語だけが登場している
    - 海外の同名施設・企業・イベントなどに関する内容（例：ロッテシネマ、阪神百貨店、楽天グループのEC事業など）

    ---

    📌 注意点：
    - 記事本文がない場合は、記事タイトルだけで判断してください。
    - 関連キーワードが登場していても、必ず文脈を確認した上で判断してください。

    ---

    🏷 チーム関連キーワード（関連性の判断に使用）：
    {team_keywords}
    ※ これらのキーワードが含まれている場合、対象球団に関する記事の可能性が高いです。

    🚫 除外キーワード（誤検出の防止に使用）：
    {ng_keywords}
    ※ これらは一般的に誤った用語です。それらが表示されている場合は、コンテキストが実際に野球に関連しているかどうかを注意深く確認してください。

    ---

    📄 記事内容：
    {text[:8000]}

    ---

    🔁 出力形式：
    - 最初に必ず「yes」または「no」で回答してください（英語の "yes" または "no" のみ）
    - その後、理由を簡潔な日本語で1～2文程度で説明してください

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
            logger.error(f"Error calling OpenAI API: {str(e)}")
            if attempt == max_retries:
                return None, f"API error after {max_retries + 1} attempts: {str(e)}"
def check_article_relation(text: str, team_name: str, max_retries: int = 2) -> Tuple[bool, str]:
    """
    Use Google Gemini API to determine if the article is related to the specified team.

    Returns:
        Tuple[bool, str]: (is_related, reason)
    """
    # Define the prompt
    prompt = f"""
    以下の記事が "{team_name}" というプロ野球チームに関連しているかどうかを判断してください。
    返答は "yes" または "no" で始め、その後に理由を簡潔に日本語で説明してください。
    記事が別の野球チームについてだけの場合は "no" と答えてください。
    注意：企業としての「ロッテ株式会社」や、お菓子・アイスクリーム・市場動向などスポーツ以外の話題に関する内容はすべて「no」としてください。
    チーム関連キーワード:

    記事：
    {text[:8000]}  # Limit to 8000 chars to stay within token limits

    """
    for attempt in range(max_retries + 1):
        try:
            # Create the model and generate content
            model = genai.GenerativeModel('gemini-2.5-flash-preview-04-17')
            response = model.generate_content(prompt)

            # Extract the text
            if hasattr(response, 'text'):
                # For newer versions of the library
                result_text = response.text
            else:
                # For older versions
                result_text = response.candidates[0].content.parts[0].text

            # Parse the response
            if result_text.lower().startswith("yes"):
                return True, result_text
            elif result_text.lower().startswith("no"):
                return False, result_text
            else:
                # If response doesn't start with yes/no, try to interpret
                if "関連" in result_text and "ありません" not in result_text and "ない" not in result_text:
                    return True, result_text
                elif "関連" in result_text and ("ありません" in result_text or "ない" in result_text):
                    return False, result_text
                else:
                    return None, "Can't decide: " + result_text

        except Exception as e:
            logger.error(f"Error calling Gemini API: {str(e)}")
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

def main():
    parser = argparse.ArgumentParser(description='Process articles to determine relation to Japanese baseball teams')
    # parser.add_argument('--api-key', '-k', required=True, help='Google Gemini API key')
    parser.add_argument('--limit', '-l', type=int, help='Limit number of articles to process')
    args = parser.parse_args()

    # Set up the Gemini API
    # setup_gemini_api(args.api_key)
    # input_dir = "fixed_outputs"
    # csv_files = glob.glob(os.path.join(input_dir, "*.csv"))
    # Load CSV data

    # for file_path in csv_files:
    file_path = "chunks/teams.csv"
    logger.info(f"\n📄 Processing file: {file_path}")

    df = load_csv_data(file_path)

    # Limit rows if specified
    if args.limit and args.limit > 0:
        df = df.iloc[:args.limit]

    # Create new columns for results
    df['is_related'] = None
    df['reason'] = ''
    # df['final_content'] = ''

    # Process each article
    total_articles = len(df)
    for idx, row in df.iterrows():
        logger.info(f"Processing article {idx+1}/{total_articles}: {row.get('記事タイトル', '')[:30]}...")

        try:
            result = process_article(row)

            # Update dataframe with results
            df.at[idx, 'is_related'] = result["is_related"]
            df.at[idx, 'reason'] = result["reason"]
            # df.at[idx, 'final_content'] = result["final_content"]

            # Save intermediate results every 10 articles
            if (idx + 1) % 100 == 0:
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
                logger.info(f"Saved intermediate results after {idx+1} articles")

            # Add a small delay to avoid rate limiting
            time.sleep(1)

        except Exception as e:
            logger.error(f"Error processing article {idx}: {str(e)}")

    df.to_csv(file_path, index=False, encoding='utf-8-sig')
    logger.info(f"✅ Finished file: {file_path}\n")

    # Print summary
    related_count = (df['is_related'] == True).sum()
    not_related_count = (df['is_related'] == False).sum()
    undecided_count = len(df) - related_count - not_related_count

    logger.info(f"Summary:")
    logger.info(f"  Total articles: {len(df)}")
    logger.info(f"  Related to teams: {related_count}")
    logger.info(f"  Not related: {not_related_count}")
    logger.info(f"  Couldn't decide: {undecided_count}")

if __name__ == "__main__":
    main()
