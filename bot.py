import os
import sys
import json
import logging
import uuid

# Force UTF-8 for console output to avoid emoji crashes on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from typing import Dict
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, Application
from telegram.error import NetworkError
import psutil
import threading
import time

def watch_parent():
    try:
        parent = psutil.Process(os.getpid()).parent()
        while True:
            if parent is None or not parent.is_running():
                os._exit(0)
            time.sleep(5)
    except Exception:
        pass
        
threading.Thread(target=watch_parent, daemon=True).start()

from parser import parse_prediction_message
from polymarket_service import search_events, map_pick_to_market_and_outcome, place_order, check_status, get_active_orders
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=env_path)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("main_bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# In-memory storage for settings (could be moved to a DB)
# Stores default bet size per chat_id
user_settings = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_settings:
        user_settings[chat_id] = {"bet_size": 2.0}
    username = update.effective_user.username
    logger.info(f"User @{username} (ID: {chat_id}) triggered /start command.")
    welcome_text = (
        "Welcome to the Polymarket Prediction Bot! 📈\n\n"
        "Just forward a prediction message from @ThePrediBot here, and I will automatically "
        "find the match on Polymarket and place the bets for you.\n\n"
        "Use /settings to configure your bet size.\n"
        "Use /status to check connection.\n"
        "Use /bets to view active orders."
    )
    await context.bot.send_message(chat_id=chat_id, text=welcome_text)

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    logger.info(f"User @{username} (ID: {chat_id}) triggered /settings command.")
    keyboard = [
        [InlineKeyboardButton("$2", callback_data="size_2"), InlineKeyboardButton("$5", callback_data="size_5")],
        [InlineKeyboardButton("$10", callback_data="size_10"), InlineKeyboardButton("$25", callback_data="size_25")],
        [InlineKeyboardButton("$50", callback_data="size_50"), InlineKeyboardButton("$100", callback_data="size_100")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id, text="Select your default bet size per pick:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    username = query.from_user.username
    
    logger.info(f"User @{username} (ID: {chat_id}) clicked button: {data}")
    
    if data.startswith("size_"):
        new_size = float(data.split("_")[1])
        if chat_id not in user_settings:
            user_settings[chat_id] = {}
        user_settings[chat_id]["bet_size"] = new_size
        logger.info(f"Updated default bet size to ${new_size} for user {chat_id}")
        await query.edit_message_text(text=f"Default bet size updated to ${new_size}.")
        
    elif data == "menu_settings":
        await settings(update, context)
    elif data == "menu_status":
        await status_cmd(update, context)
    elif data == "menu_bets":
        await bets_cmd(update, context)
        
    elif data.startswith("bet|"):
        _, pred_id, pick_idx = data.split("|")
        pick_idx = int(pick_idx)
        
        preds = context.user_data.get("predictions", {})
        if pred_id not in preds:
            await query.edit_message_text(text="This prediction has expired or couldn't be found.")
            return
            
        pred_data = preds[pred_id]
        pick = pred_data["parsed"]["picks"][pick_idx]
        
        await query.edit_message_text(text=f"Executing bet for: {pick}...")
        await execute_bets(context, chat_id, pred_data["events"], [pick])
        
    elif data.startswith("bet_all|"):
        _, pred_id = data.split("|")
        
        preds = context.user_data.get("predictions", {})
        if pred_id not in preds:
            await query.edit_message_text(text="This prediction has expired or couldn't be found.")
            return
            
        pred_data = preds[pred_id]
        picks = pred_data["parsed"]["picks"]
        
        await query.edit_message_text(text="Executing ALL bets...")
        await execute_bets(context, chat_id, pred_data["events"], picks)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username if update.effective_user else "unknown"
    logger.info(f"User @{username} (ID: {chat_id}) triggered /status command.")
    await context.bot.send_message(chat_id=chat_id, text="Checking Polymarket connectivity...")
    ok = check_status()
    if ok:
        await context.bot.send_message(chat_id=chat_id, text="Connected to Polymarket.")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Failed to connect to Polymarket.")

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("Status", callback_data="menu_status")],
        [InlineKeyboardButton("Active Bets", callback_data="menu_bets")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text("Main Menu:", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text="Main Menu:", reply_markup=reply_markup)

async def bets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    logger.info(f"User @{username} (ID: {chat_id}) triggered /bets command.")
    await context.bot.send_message(chat_id=chat_id, text="Fetching active orders...")
    orders = get_active_orders()
    if not orders:
        await context.bot.send_message(chat_id=chat_id, text="No active orders found.\n\nYou can view your full portfolio here: https://polymarket.com/portfolio")
    else:
        lines = [f"Found {len(orders)} active orders:"]
        for o in orders[:10]: # limit to 10
            lines.append(f"- Order ID: {o.get('id')}, Size: {o.get('size')}, Side: {o.get('side')}")
        if len(orders) > 10:
            lines.append("... and more.")
        lines.append("\nView your full portfolio here: https://polymarket.com/portfolio")
        await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    
    logger.info(f"User @{username} (ID: {chat_id}) sent text message:\n{msg}")
    
    if "MATCH PREDICTION" not in msg:
        # Not a prediction message, ignore or reply
        return

    logger.info(f"User @{username} (ID: {chat_id}) triggered prediction parsing.")
    await context.bot.send_message(chat_id=chat_id, text="Parsing prediction...")
    
    try:
        parsed = parse_prediction_message(msg)
        logger.info(f"Parsed prediction: {parsed}")
    except Exception as e:
        logger.error(f"Failed to parse message: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"Failed to parse message: {e}")
        return

    home = parsed.get("home_team")
    away = parsed.get("away_team")
    picks = parsed.get("picks", [])

    if not home or not away:
        await context.bot.send_message(chat_id=chat_id, text="Could not extract teams from the message.")
        return

    await context.bot.send_message(chat_id=chat_id, text=f"Searching Polymarket for: {home} vs {away}")
    logger.info(f"Searching Polymarket for: {home} vs {away}")
    
    events = search_events(home, away, competition=parsed.get('competition'))
    if not events:
        logger.warning(f"No matching events found on Polymarket for {home} vs {away}")
        await context.bot.send_message(chat_id=chat_id, text="No matching events found on Polymarket.")
        return
        
    logger.info(f"Found {len(events)} matching events for {home} vs {away}")
    
    pred_id = str(uuid.uuid4())[:8]
    if "predictions" not in context.user_data:
        context.user_data["predictions"] = {}
        
    context.user_data["predictions"][pred_id] = {
        "parsed": parsed,
        "events": events
    }
    
    keyboard = []
    for i, pick in enumerate(picks):
        keyboard.append([InlineKeyboardButton(f"Bet: {pick}", callback_data=f"bet|{pred_id}|{i}")])
        
    if picks:
        keyboard.append([InlineKeyboardButton("Bet on ALL", callback_data=f"bet_all|{pred_id}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id, 
        text=f"Found {len(events)} Events matching {home} vs {away}.\nSelect which picks to bet on:",
        reply_markup=reply_markup
    )

async def execute_bets(context: ContextTypes.DEFAULT_TYPE, chat_id: int, events: list, picks: list):
    response_lines = []
    bet_size = user_settings.get(chat_id, {}).get("bet_size", 2.0)
    
    for pick in picks:
        market, outcome_idx, side = map_pick_to_market_and_outcome(events, pick)
        if market and outcome_idx is not None:
            clob_token_ids = json.loads(market.get('clobTokenIds', '[]'))
            if outcome_idx < len(clob_token_ids):
                token_id = clob_token_ids[outcome_idx]
                condition_id = market.get('conditionId')
                
                logger.info(f"Mapped pick '{pick}' to market '{market.get('question')}', token {token_id}")
                response_lines.append(f"-> Placing {side} for '{pick}' on market '{market.get('question')}' ($ {bet_size})...")
                
                success, order_resp = place_order(condition_id, token_id, bet_size)
                if success:
                    logger.info(f"Order success: {order_resp}")
                    response_lines.append(f"   Success! Order ID: {order_resp.get('orderID', 'Unknown')}")
                else:
                    logger.error(f"Order failed: {order_resp}")
                    response_lines.append(f"   Failed: {order_resp}")
            else:
                logger.warning(f"Pick '{pick}': Token ID not found in market {market.get('question')}")
                response_lines.append(f"-> Pick '{pick}': Token ID not found.")
        else:
            logger.warning(f"Pick '{pick}': No matching market found")
            response_lines.append(f"-> Pick '{pick}': No matching market found on Polymarket.")
            
    if response_lines:
        await context.bot.send_message(chat_id=chat_id, text="\n".join(response_lines))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and handle specific network exceptions quietly."""
    if isinstance(context.error, NetworkError):
        logger.warning(f"Network error occurred (usually temporary): {context.error}")
    else:
        logger.error("Exception while handling an update:", exc_info=context.error)

async def post_init(application: Application):
    logger.info("Setting bot commands...")
    commands = [
        BotCommand("start", "Show welcome message"),
        BotCommand("menu", "Open the main menu"),
        BotCommand("settings", "Configure bet sizes"),
        BotCommand("status", "Check Polymarket connection"),
        BotCommand("bets", "View active orders")
    ]
    await application.bot.set_my_commands(commands)

if __name__ == '__main__':
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set.")
    
    application = ApplicationBuilder().token(token).post_init(post_init).build()
    
    start_handler = CommandHandler('start', start)
    menu_handler = CommandHandler('menu', menu_cmd)
    settings_handler = CommandHandler('settings', settings)
    status_handler = CommandHandler('status', status_cmd)
    bets_handler = CommandHandler('bets', bets_cmd)
    button_handler = CallbackQueryHandler(button_callback)
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    
    application.add_handler(start_handler)
    application.add_handler(menu_handler)
    application.add_handler(settings_handler)
    application.add_handler(status_handler)
    application.add_handler(bets_handler)
    application.add_handler(button_handler)
    application.add_handler(message_handler)
    
    # Register error handler
    application.add_error_handler(error_handler)
    
    logger.info("Bot is starting...")
    application.run_polling()
