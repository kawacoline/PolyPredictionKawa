# 📈 PolyPrediction — Automated NLP Prediction Market Execution Engine

[![Python Version](https://img.shields.io/badge/Python-3.9%2B-blue.svg?logo=python)](https://python.org)
[![Market Platform](https://img.shields.io/badge/Exchange-Polymarket%20CLOB-purple.svg)](https://polymarket.com)
[![Network](https://img.shields.io/badge/Network-Polygon%20PoS-8247E5.svg?logo=polygon)](https://polygon.technology)
[![Bot Framework](https://img.shields.io/badge/Interface-Telegram%20Bot%20API-blue.svg?logo=telegram)](https://telegram.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**PolyPrediction** is an autonomous trade execution engine bridging unstructured natural-language sports predictions with decentralized prediction markets (**Polymarket**). 

The system consumes forwarded prediction messages from Telegram channels, dynamically parses complex match entities and betting picks using heuristic NLP extraction, reconciles international team naming discrepancies against the Polymarket Gamma API, and submits cryptographically signed orders directly to the Polymarket Central Limit Order Book (CLOB).

---

## 🏛️ Pipeline Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        TELEGRAM INGESTION LAYER                        │
│   Receives raw forwarded match predictions from analytical channels    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Unstructured Text
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        HEURISTIC NLP PARSER                            │
│   • Extracts Home / Away clubs, Tournament, Match Timestamp            │
│   • Classifies wager types: 1X2 (Moneyline), Over/Under, BTTS          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Normalized Entities
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     GAMMA API ENTITY RESOLUTION                        │
│   • Fuzzy string reconciliation (e.g. "Congo DR" vs "DR Congo")        │
│   • Multi-market mapping: Resolves Condition IDs & Token IDs           │
│   • Resilient fallback if secondary lines (BTTS/O-U) are absent        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Verified Token Identifiers
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     CLOB ORDER EXECUTION (Web3)                        │
│   • EIP-712 Order Construction and Polygon cryptographic signing       │
│   • Automated Gasless execution via Polymarket Relayer                 │
│   • Interactive order confirmation & risk verification via Telegram    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Core Capabilities

- **Intelligent Entity Reconciliation**: Sports teams frequently suffer from inconsistent naming conventions across platforms. PolyPrediction uses concurrent string-similarity matching across the Gamma API index to accurately locate active markets.
- **Multi-Market Contract Resolution**: Automatically classifies and targets multiple betting outcomes from a single text dispatch:
  - **Match Winner (1X2 / Moneyline)**
  - **Total Goals (Over / Under 2.5)**
  - **Both Teams to Score (BTTS)**
- **Fault-Tolerant Execution**: If a specific sub-market is missing on Polymarket, the engine gracefully skips the unavailable outcome and places available bets without crashing.
- **Autonomous Supervisor & Live Updater**: Features a background watchdog process that monitors git revisions, seamlessly hot-reloading the application when updates are deployed.
- **Inline Telegram Settings Interface**: Control bankroll allocation, default stake sizing ($2, $5, $10, $50), and view open positions directly through interactive Telegram keyboards.

---

## 🛠️ Installation & Setup

### 1. Prerequisites
- **Python 3.9+**
- **Polygon (PoS) Wallet**: Funded with USDC.e on Polygon
- **Telegram Bot Token**: Created via [@BotFather](https://t.me/botfather)

### 2. Clone & Provision Environment
```bash
git clone https://github.com/kawacoline/PolyPredictionKawa.git
cd PolyPredictionKawa
setup.bat
```

*(On Linux / macOS)*:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file from the provided template:
```bash
copy .env.example .env
```

Fill in your API credentials:
```ini
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Polymarket Web3 Parameters
POLYMARKET_HOST=https://clob.polymarket.com
POLYMARKET_CHAIN_ID=137
POLYMARKET_KEY=your_polygon_private_key_here
POLYMARKET_FUNDER=your_polygon_public_wallet_address_here

DEFAULT_BET_AMOUNT=5.0
```

### 4. Running the Bot
Launch via the automated startup script:
```bash
start.bat
```

Or manually:
```bash
python bot.py
```

---

## 📱 Bot Command Interface

| Command | Action |
|---|---|
| `/start` | Displays interface status, active account connection, and guide |
| `/settings` | Opens inline keyboard to configure default bet sizing per pick |
| `/status` | Validates active Polymarket CLOB API connection and funder balance |
| `/bets` | Displays active orders and recent fills |

---

## 📁 Repository Structure

```
├── bot.py                  # Master Telegram bot controller & command dispatcher
├── parser.py               # NLP heuristic extraction and prediction classifier
├── polymarket_service.py   # Gamma API resolution and CLOB order router
├── updater.py              # Autonomous supervisor and continuous deployment loop
├── requirements.txt        # Production dependencies
├── setup.bat / start.bat   # Automated Windows environment scripts
└── .env.example            # Sanitized environment template
```

---

## 👨‍💻 Author

**Hazael**  
*Full Stack Software Engineer & Web3 Automation Specialist*  
- **GitHub**: [@kawacoline](https://github.com/kawacoline)  
- **Email**: kawacoline@gmail.com  
- **Portfolio**: [hazael.dev](https://github.com/kawacoline)

---

## ⚖️ Disclaimer

*This project is distributed strictly for educational, research, and algorithmic demonstration purposes. Trading prediction markets involves monetary risk. Always wager responsibly.*
