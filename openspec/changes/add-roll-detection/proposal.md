# Change: Add Futures Roll Detection

## Why

Futures traders get caught out by contract rolls when front-month volume/liquidity shifts to the next contract. The only reliable signal is when open interest migrates from the expiring contract to the deferred month. TWS auto-roll doesn't work as expected, and CME's "Pace of the Roll" tool requires manual checking.

## What Changes

- **New CLI command** `iborker roll`:
  - `iborker roll status [SYMBOLS...]` - Show roll status for futures (OI ratio, recommendation)
  - `iborker roll today` - Highlight any symbols actively rolling

- **New library module** `src/iborker/roll.py` exposing:
  - `get_roll_status(symbol)` - Returns roll state (pre-roll, rolling, post-roll) with OI data
  - `get_active_contract(symbol)` - Returns the "right" contract to trade

- **Integration with iborker-trader** - Use `get_active_contract()` for smarter contract selection

## Technical Approach

Point-in-time OI check via IB API:
1. Fetch OI for front-month and next contract using `reqMktData` with generic tick 588
2. Calculate ratio: `deferred_OI / (front_OI + deferred_OI)`
3. Thresholds: <20% = pre-roll, 20-80% = rolling, >80% = post-roll
4. Simple session cache to avoid repeated API calls

No historical tracking - just "what's active right now" each time you check.

## Impact

- Affected specs: None (new capability)
- Affected code:
  - `src/iborker/contracts.py` - Add liquid month patterns
  - `src/iborker/trader.py` - Optional roll-aware contract selection
  - `src/iborker/cli.py` - New `roll` subcommand group
