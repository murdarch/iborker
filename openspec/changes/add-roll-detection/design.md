# Design: Futures Roll Detection

## Context

CME's "Pace of the Roll" tracks open interest migration from expiring front-month to deferred months. The crossover point (where deferred OI exceeds front-month OI) signals when to switch contracts.

**User pattern:** Check a couple times per week before trading sessions, not daily monitoring.

## Goals / Non-Goals

**Goals:**
- Point-in-time answer: "which contract should I trade right now?"
- Simple CLI check before trading sessions
- Integrate with trader for automatic contract selection

**Non-Goals:**
- Historical roll tracking or pace monitoring
- Data persistence or backfilling
- Real-time alerting

## Decisions

### 1. Use Open Interest Ratio as Primary Metric

**Decision:** Track `deferred_OI / (front_OI + deferred_OI)` ratio.

**Thresholds:**
- `ratio < 0.2` = Pre-roll → Trade front month
- `0.2 <= ratio < 0.5` = Early roll → Trade front month (with warning)
- `0.5 <= ratio < 0.8` = Late roll → Trade deferred month
- `ratio >= 0.8` = Post-roll → Trade deferred month

### 2. Data Fetching via IB API

**Verified approach:**
```python
ticker = ib.reqMktData(contract, genericTickList="588", snapshot=False)
await asyncio.sleep(2)  # Wait for data
oi = ticker.futuresOpenInterest  # Populated by tick type 86
```

**Key constraints:**
- Streaming mode required (snapshot=False) - snapshot mode errors with generic ticks
- Wait ~2 seconds for data, then cancel subscription
- OI data is as-of last trading day close

**Test results (2026-01-23):**
- ES: Front 1.87M OI, Back 10K OI (0.56% ratio, pre-roll)
- NQ: Front 256K OI, Back 875 OI (0.34% ratio, pre-roll)
- ZC: Front 658K OI, Back 320K OI (32.7% ratio, **actively rolling**)

### 3. Liquid Month Filtering

**Patterns stored in FUTURES_DATABASE:**
- **Quarterly** (ES, NQ, RTY, 6E, etc.): H/M/U/Z only
- **Monthly** (CL, NG, GC, SI): All months
- **Agricultural** (ZC, ZS, ZW): H/K/N/U/Z (Mar, May, Jul, Sep, Dec)

### 4. Simple Session Cache

**Decision:** In-memory cache during CLI execution, no persistence.

- Cache OI results for duration of command execution
- Avoids duplicate API calls when checking multiple symbols
- Fresh data each time you run the command

### 5. Module Structure

```
src/iborker/
├── roll.py              # Core roll detection logic
│   ├── RollStatus       # Dataclass: status, ratio, front/back contracts, OI values
│   ├── get_contract_chain()    # Fetch available expirations, filter to liquid
│   ├── get_oi_snapshot()       # Fetch OI via streaming reqMktData
│   ├── get_roll_status()       # Main API: returns RollStatus
│   └── get_active_contract()   # Returns recommended contract
└── cli.py
    └── roll_app         # Typer subcommand group
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| OI data stale (weekend/holiday) | Display data timestamp, user understands it's last close |
| API rate limits | Batch requests, short streaming window |
| Low OI on back month early in cycle | Use threshold (ratio < 0.2 = clearly pre-roll) |

## Decisions (continued)

### 6. `roll today` checks entire database

`iborker roll today` will check ALL symbols in FUTURES_DATABASE and show only those with status "rolling". This enables a quick pre-session check without remembering which symbols to query.

### 7. Missing symbols to add

Add to FUTURES_DATABASE before implementation:
- **UB** (CBOT, Ultra T-Bond, 1000.0, 0.03125) - quarterly HMUZ
- **MBT** (CME, Micro Bitcoin, 0.1, 5.0) - monthly ALL
