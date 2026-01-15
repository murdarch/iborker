# iborker

CLI and GUI tools for Interactive Brokers futures trading.

## Requirements

- Python 3.12+
- Interactive Brokers TWS or IB Gateway running with API enabled
- TWS API port configured (default: 7497 for paper, 7496 for live)

## Installation

```bash
uv sync
```

## Configuration

Create a `.env` file in your working directory:

```bash
# Connection settings
IB_HOST=127.0.0.1
IB_PORT=7497              # 7497=paper, 7496=live
IB_TIMEOUT=10.0
IB_READONLY=false

# Client ID management (for running multiple tools simultaneously)
IB_CLIENT_ID_MODE=auto    # "auto" or "fixed"
IB_CLIENT_ID_START=1      # Base for auto-allocated IDs
IB_CLIENT_ID=1            # Used when mode="fixed"

# Account nicknames for Click Trader dropdown
IB_ACCOUNT_NICKNAMES={"U1234567": "Main", "U7654321": "IRA"}
```

## Tools

### Click Trader (GUI)

Fast order entry GUI for futures trading.

```bash
iborker-trader
```

**Features:**
- One-click buy/sell/flatten/reverse
- Auto-selects front month contract (just type "ES", "NQ", etc.)
- Points-based P&L display (per-contract, position-size agnostic)
- Multi-account support with nicknames
- Keyboard shortcuts for rapid order entry

**Keyboard Shortcuts:**
| Key | Action |
|-----|--------|
| Q | Focus quantity input |
| B | Highlight BUY |
| S | Highlight SELL |
| F | Highlight FLATTEN |
| R | Highlight REVERSE |
| Ctrl+Enter | Execute highlighted action |
| P | Toggle points/dollars P&L |

### Historical Data

Download OHLCV data for futures contracts.

```bash
# Download 1-minute bars for ES front month
iborker history download ES --bar-size "1 min" --duration "1 D"

# Download daily bars
iborker history download NQ --bar-size "1 day" --duration "1 Y"
```

### Contract Lookup

Look up contract details and margin requirements.

```bash
# Look up contract details
iborker contract lookup ES

# List known futures symbols
iborker contract list

# Query margin requirements
iborker contract margin ES --quantity 4
```

### Expected Move Calculator

Calculate expected price moves using options-implied volatility.

```bash
# Full analysis with sigma bands
iborker stdev analyze ES

# Quick daily expected move using SPX 0DTE options
iborker stdev spx0dte

# Get ATM implied volatility
iborker stdev iv ES

# Calculate expected move for specific timeframe
iborker stdev move ES --hours 24
```

## Supported Futures

The following contracts are pre-configured:

| Symbol | Name | Exchange | Multiplier |
|--------|------|----------|------------|
| ES | E-mini S&P 500 | CME | $50 |
| NQ | E-mini NASDAQ-100 | CME | $20 |
| YM | E-mini Dow | CBOT | $5 |
| RTY | E-mini Russell 2000 | CME | $50 |
| MES | Micro E-mini S&P 500 | CME | $5 |
| MNQ | Micro E-mini NASDAQ-100 | CME | $2 |
| CL | Crude Oil | NYMEX | $1000 |
| GC | Gold | COMEX | $100 |
| ZB | 30-Year Treasury Bond | CBOT | $1000 |
| ZN | 10-Year Treasury Note | CBOT | $1000 |

## License

MIT
