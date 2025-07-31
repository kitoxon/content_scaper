import google.generativeai as genai
import logging
from typing import Tuple

logger = logging.getLogger()
import time
def setup_gemini_api(api_key: str) -> None:
    genai.configure(api_key=api_key)

def check_article_relation(text: str, team_name: str) -> Tuple[bool, str]:
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

    記事：
    {text[:8000]}  # Limit to 8000 chars to stay within token limits
    """

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
        return None, f"API error: {str(e)}"

def article_check(text: str, team: str):
    setup_gemini_api("AIzaSyAAr8-qr3C5gZe3KHWuINYPjF2XWiuhhD0")
    time.sleep(0.5)
    return check_article_relation(text, team)
