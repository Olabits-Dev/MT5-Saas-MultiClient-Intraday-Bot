# MT5 Multi-Client SaaS Intraday Bot

Professional MT5 bot with **Price Action + EMA + Breakout + Reversal + S/R + Volume filters**.

## Features

- Multi-client MT5 support
- Encrypted client storage (`clients.enc`)
- VPS-ready 24/7 operation
- Optional Telegram alerts
- Prop-firm style intraday trading

## Installation

1. Install Python 3.10+
2. Clone repository
3. Create virtual env:
   ```bash
   python -m venv myenv

Activate environment:

Windows:

myenv\Scripts\activate


Linux/macOS:

source myenv/bin/activate


Install dependencies:
pip install -r requirements.txt

Open MetaTrader 5 and log in to your account. Ensure AutoTrading is ON.

Usage
Run the bot:

bash
Copy code
python main.py
Trades are executed automatically based on the active session.

Logs are printed in the terminal.