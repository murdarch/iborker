# Tasks: Add Futures Roll Detection

## 1. Data Model & Core Logic

- [ ] 1.1 Add missing symbols to `FUTURES_DATABASE`: UB (Ultra T-Bond), MBT (Micro Bitcoin)
- [ ] 1.2 Add `liquid_months` field to `FUTURES_DATABASE` entries ("HMUZ", "ALL", "HKNUZ")
- [ ] 1.3 Create `RollStatus` dataclass (status, ratio, front_contract, back_contract, front_oi, back_oi)
- [ ] 1.4 Implement `get_contract_chain(symbol)` - fetch expirations, filter to liquid months
- [ ] 1.5 Implement `get_oi_snapshot(contracts)` - streaming reqMktData with tick 588

## 2. Roll Detection Logic

- [ ] 2.1 Implement `calculate_roll_status(front_oi, back_oi)` with threshold constants
- [ ] 2.2 Implement `get_roll_status(symbol)` - main API combining chain + OI
- [ ] 2.3 Implement `get_active_contract(symbol)` - returns recommended contract
- [ ] 2.4 Implement batch `get_all_roll_statuses()` - check entire FUTURES_DATABASE

## 3. CLI Commands

- [ ] 3.1 Create `roll` Typer subcommand group in `cli.py`
- [ ] 3.2 Implement `iborker roll status [SYMBOLS...]` - table output with status/ratio/recommendation
- [ ] 3.3 Implement `iborker roll today` - check ALL symbols in FUTURES_DATABASE, show only "rolling" ones

## 4. Integration

- [ ] 4.1 Add `--roll-aware` flag to trader contract resolution
- [ ] 4.2 Update trader to use `get_active_contract()` when flag enabled

## 5. Testing

- [ ] 5.1 Unit tests for ratio calculation and threshold logic
- [ ] 5.2 Integration test with TWS (fetch real OI, verify contract chain filtering)
