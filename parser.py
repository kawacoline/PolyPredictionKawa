import os
import json
import dateparser
from typing import Dict, List, Optional
from pydantic import BaseModel
from google import genai
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=env_path)

class PredictionData(BaseModel):
    home_team: str
    away_team: str
    competition: str
    date_str: str
    picks: List[str]

def parse_prediction_message(message: str) -> Dict:
    """
    Parses a prediction message to extract event details and picks using Gemini 3.5 Flash.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY environment variable is required.")
    valid_keys = [gemini_key]

    prompt = f"""
Extract the match details and the user's betting picks from the following prediction message.
Ensure you accurately extract the home team, away team, competition, date string, and list of picks.
CRITICAL: You MUST expand any abbreviations, acronyms, or short names into their FULL official team or country names (e.g., convert "USA" to "United States", "BIH" to "Bosnia and Herzegovina").
The picks should just be the name of the pick, e.g. "USA Win", "Over 2.5", "BTTS Yes". Remove any emojis from the extracted picks.

Message:
{message}
"""

    last_error = None
    for api_key in valid_keys:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PredictionData,
                    temperature=0.0
                )
            )
            data = json.loads(response.text)
            break # Successfully parsed
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "Quota" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "API key not valid" in err_msg:
                last_error = e
                continue # Try the next key
            raise # Re-raise if it's a different type of error (like schema error)
    else:
        # If the loop finishes without breaking, all keys failed
        raise last_error

    
    data = json.loads(response.text)
    
    parsed = {
        "home_team": data.get("home_team"),
        "away_team": data.get("away_team"),
        "competition": data.get("competition"),
        "date_str": data.get("date_str"),
        "parsed_date": None,
        "picks": data.get("picks", [])
    }
    
    if parsed.get("date_str"):
        parsed["parsed_date"] = dateparser.parse(parsed["date_str"])
        
    return parsed
