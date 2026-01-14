# Implementation Tasks

## 1. Configuration
- [x] 1.1 Add `client_id_start` to IBSettings (default: 1)
- [x] 1.2 Add `client_id_mode` option: "auto" (default) or "fixed"
- [ ] 1.3 Document configuration in project.md

## 2. Client ID Allocation
- [x] 2.1 Create `src/iborker/client_id.py` module
- [x] 2.2 Implement tool-type to offset mapping (CLI=0, trader=10, stdev=20, etc.)
- [x] 2.3 Add lock file mechanism for concurrent process safety
- [x] 2.4 Implement `get_client_id(tool: str) -> int` function

## 3. Integration
- [x] 3.1 Update `connection.py` to accept tool identifier
- [x] 3.2 Update `trader.py` to use "trader" tool ID
- [x] 3.3 Update `history.py` to use "history" tool ID
- [x] 3.4 Update `contracts.py` to use "contracts" tool ID
- [x] 3.5 Update `stdev.py` to use "stdev" tool ID

## 4. Testing
- [ ] 4.1 Add unit tests for client ID allocation
- [ ] 4.2 Test concurrent process scenarios
- [ ] 4.3 Verify trader and CLI can run simultaneously
