import os
import requests
import json
import re
import concurrent.futures
import logging
from decimal import Decimal
from typing import List, Dict, Optional
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.constants import POLYGON
from py_clob_client_v2.order_builder.constants import BUY
from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=env_path)

# Credentials
HOST = "https://clob.polymarket.com"
CHAIN_ID = POLYGON
PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")
FUNDER_ADDRESS = os.getenv("POLY_FUNDER_ADDRESS")

API_KEY = os.getenv("POLY_API_KEY")
API_SECRET = os.getenv("POLY_API_SECRET")
API_PASSPHRASE = os.getenv("POLY_API_PASSPHRASE")

BUILDER_CODE = os.getenv("BUILDER_CODE")

logger = logging.getLogger('polymarket')

api_creds = None
if API_KEY and API_SECRET and API_PASSPHRASE:
    from py_clob_client_v2 import ApiCreds
    api_creds = ApiCreds(
        api_key=API_KEY,
        api_secret=API_SECRET,
        api_passphrase=API_PASSPHRASE
    )

def get_client() -> ClobClient:
    client = ClobClient(
        HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        creds=api_creds,
        signature_type=3,
        funder=FUNDER_ADDRESS
    )
    if not api_creds:
        # Step 1: obtain API credentials using your wallet (L1 auth)
        derived_creds = client.create_or_derive_api_key()
        # Step 2: initialize a fully-authenticated client (L1 + L2)
        client = ClobClient(
            HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            creds=derived_creds,
            signature_type=3,
            funder=FUNDER_ADDRESS
        )
    return client

def fetch_events_page(offset: int) -> List[Dict]:
    url = "https://gamma-api.polymarket.com/events"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 100,
        "offset": offset
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching offset {offset}: {e}")
    return []

def search_events(home_team: str, away_team: str, competition: str = None) -> List[Dict]:
    """
    Search for events on Polymarket matching the teams using the public-search API.
    """
    matched_events = []
    
    def clean_words(team_name: str) -> List[str]:
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', team_name.lower())
        words = cleaned.split()
        return [w for w in words if w not in ['and', 'fc', 'club', 'team']]

    def is_match(team_name: str, t: str) -> bool:
        words = clean_words(team_name)
        if not words: return False
        return all(word in t for word in words)

    def check_event_match(event: Dict, home: str, away: str) -> bool:
        title = event.get('title', '').lower()
        if is_match(home, title) and is_match(away, title):
            return True
            
        teams = event.get('teams', [])
        if teams:
            team_names = []
            for t in teams:
                team_names.append(t.get('name', '').lower())
                team_names.append(t.get('abbreviation', '').lower())
                if 'alias' in t: team_names.append(t.get('alias', '').lower())
            
            home_matched = any(is_match(home, name) for name in team_names)
            away_matched = any(is_match(away, name) for name in team_names)
            if home_matched and away_matched:
                return True
        return False

    found_slugs = set()
    
    # Map common competitions to Tag IDs
    COMPETITION_TO_TAG = {
        "world cup": 102232,
        "premier league": 82,
        "la liga": 780,
        "champions league": 104343,
        "nba": 745,
        "nfl": 1186,
        "nhl": 899,
        "soccer": 100350
    }
    
    tag_id = 100350 # Default to general soccer tag
    if competition:
        comp_lower = competition.lower()
        if comp_lower in COMPETITION_TO_TAG:
            tag_id = COMPETITION_TO_TAG[comp_lower]
            
    # Fetch events using Tag ID (Strategy 2 in Docs)
    offset = 0
    while True:
        params = {"active": "true", "closed": "false", "limit": 100, "offset": offset, "tag_id": tag_id}
        try:
            resp = requests.get("https://gamma-api.polymarket.com/events", params=params, timeout=10)
            if resp.status_code == 200:
                events = resp.json()
                if not events or not isinstance(events, list): break
                
                for event in events:
                    if check_event_match(event, home_team, away_team):
                        if not any(e.get("id") == event.get("id") for e in matched_events):
                            matched_events.append(event)
                        slug = event.get('seriesSlug')
                        if slug:
                            found_slugs.add(slug)
                        series = event.get('series', [])
                        if series and len(series) > 0 and series[0].get('slug'):
                            found_slugs.add(series[0].get('slug'))
                
                if len(events) < 100: break
                offset += 100
            else:
                break
        except Exception as e:
            logger.error(f"Error fetching events by tag: {e}")
            break

    # Fetch any additional events from the same series if we found slugs (Strategy 1 in Docs)
    for series_slug in found_slugs:
        # We only need active events now since closed=false is default per new docs
        offset = 0
        while True:
            params = {"active": "true", "limit": 100, "offset": offset, "series_slug": series_slug}
            try:
                resp = requests.get("https://gamma-api.polymarket.com/events", params=params, timeout=10)
                if resp.status_code == 200:
                    series_events = resp.json()
                    if not series_events or not isinstance(series_events, list): break
                    
                    for event in series_events:
                        if not any(e.get("id") == event.get("id") for e in matched_events):
                            if check_event_match(event, home_team, away_team):
                                matched_events.append(event)
                            
                    if len(series_events) < 100: break
                    offset += 100
                else:
                    break
            except Exception as e:
                logger.error(f"Error fetching series {series_slug}: {e}")
                break
                    
    return matched_events

def map_pick_to_market_and_outcome(events: List[Dict], pick: str):
    """
    Given a list of events and a parsed pick (e.g. 'Norway Win', 'Over 2.5', 'BTTS Yes', 'Draw'),
    find the corresponding market and outcome (Yes/No or Team).
    Returns (market, outcome_index, side)
    """
    pick = pick.lower()
    
    markets = []
    team_synonyms = []
    for e in events:
        markets.extend(e.get('markets', []))
        for t in e.get('teams', []):
            syns = set()
            if t.get('name'): syns.add(t.get('name').lower())
            if t.get('abbreviation'): syns.add(t.get('abbreviation').lower())
            if t.get('alias'): syns.add(t.get('alias').lower())
            if syns: team_synonyms.append(syns)
        
    # Helper for robust name matching
    def is_match(team_name: str, t: str) -> bool:
        team_name_lower = team_name.lower().strip()
        words = team_name_lower.split()
        
        # Direct word check
        if all(word in t for word in words):
            return True
            
        # Synonym check
        for syns in team_synonyms:
            if any(syn == team_name_lower or all(w in syn for w in words) for syn in syns):
                if any(syn in t for syn in syns):
                    return True
                    
        return False
    
    # 1. Match Winner (1X2)
    if "win" in pick or "draw" in pick:
        for market in markets:
            title = market.get('question', '').lower()
            outcomes = json.loads(market.get('outcomes', '[]'))
            outcomes_lower = [o.lower() for o in outcomes]
            
            # Check if it's a draw market
            if "draw" in pick:
                if "draw" in title:
                    yes_idx = outcomes_lower.index("yes") if "yes" in outcomes_lower else 0
                    return market, yes_idx, BUY
            else:
                # Find which team is supposed to win
                pick_team = pick.replace(' win', '').strip()
                if is_match(pick_team, title) and "win" in title and "draw" not in title:
                    yes_idx = outcomes_lower.index("yes") if "yes" in outcomes_lower else 0
                    return market, yes_idx, BUY
                        
    # 2. Over/Under 2.5
    if "over" in pick or "under" in pick:
        for market in markets:
            title = market.get('question', '').lower()
            if ("over" in title or "o/u" in title) and "2.5" in title:
                # Exclude 1st half, 2nd half, corners, and team-specific totals
                if "half" in title or "corners" in title:
                    continue
                # If it's a team specific total it usually has the team name right before O/U
                if "united states o/u" in title or "bosnia and herzegovina o/u" in title:
                    # Generic way to avoid team-specific O/U:
                    # The general market is "Home vs Away: O/U 2.5"
                    pass # We'll just try to exclude them below
                
                # A good heuristic for the main match O/U 2.5 is that it's exactly the match string + ": o/u 2.5"
                if ": o/u 2.5" not in title and "over/under 2.5 goals" not in title:
                    if "o/u 2.5" in title and ":" in title:
                        # might be "Team O/U 2.5"
                        parts = title.split(":")
                        if len(parts) > 1 and parts[1].strip() != "o/u 2.5":
                            continue

                outcomes = json.loads(market.get('outcomes', '[]'))
                outcomes_lower = [o.lower() for o in outcomes]
                for i, outcome in enumerate(outcomes_lower):
                    if ("over" in pick and "yes" in outcome) or ("under" in pick and "no" in outcome):
                        return market, i, BUY
                    if ("over" in pick and "over" in outcome) or ("under" in pick and "under" in outcome):
                        return market, i, BUY

    # 3. Both Teams to Score (BTTS)
    if "btts" in pick or "both teams to score" in pick:
        for market in markets:
            title = market.get('question', '').lower()
            if "both teams to score" in title or "btts" in title:
                outcomes = json.loads(market.get('outcomes', '[]'))
                outcomes_lower = [o.lower() for o in outcomes]
                want_yes = "yes" in pick
                for i, outcome in enumerate(outcomes_lower):
                    if want_yes and "yes" in outcome:
                        return market, i, BUY
                    elif not want_yes and "no" in outcome:
                        return market, i, BUY

    return None, None, None

def place_order(market_condition_id: str, token_id: str, size: float):
    """
    Places an order on Polymarket for the given token.
    We will use Market Order logic if possible, or an aggressive limit order.
    """
    client = get_client()
    
    try:
        # Fetch market to get tick size
        market = client.get_market(market_condition_id)
        tick_size = str(market.get("minimum_tick_size", "0.01"))
        neg_risk = market.get("neg_risk", False)
        
        # We will fetch the order book to find the best ask
        # Wait, the SDK has market order? 
        # Actually GTC is Good Till Canceled (Limit Order), FOK is Fill Or Kill, IOC is Immediate Or Cancel.
        # Polymarket supports FOK or IOC for market-like orders.
        # Let's get the orderbook
        book = client.get_order_book(token_id)
        if not book or not book.get('asks'):
            logger.warning("No liquidity to buy.")
            return False, "No liquidity"
            
        best_ask = book['asks'][0]['price']
        # We'll place an order at best_ask or slightly worse to ensure fill
        price = best_ask
        
        logger.info(f"Placing order for token {token_id} at price {price}, size {size}")
        
        response = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=float(price),
                size=float(size),
                side=BUY,
                builder_code=BUILDER_CODE if BUILDER_CODE else ""
            ),
            options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
            order_type=OrderType.FOK, # Fill Or Kill
        )
        return True, response
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return False, str(e)

def check_status() -> bool:
    """
    Check if Polymarket credentials are valid.
    """
    client = get_client()
    try:
        ok = client.get_ok()
        return ok == "OK"
    except Exception:
        return False

def get_active_orders() -> List[Dict]:
    """
    Get open orders for the user.
    """
    client = get_client()
    try:
        from py_clob_client_v2 import OpenOrderParams
        orders = client.get_open_orders(OpenOrderParams())
        return orders if orders else []
    except Exception as e:
        logger.error(f"Error getting open orders: {e}")
        return []

