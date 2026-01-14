# Change: Add Client ID Management

## Why
IB TWS/Gateway only allows one active connection per client_id. When multiple iborker tools (CLI commands, click trader GUI) try to use the same hardcoded client_id=1, connections fail. Users need a way to configure a client_id floor and have iborker automatically assign unique IDs to each tool/process.

## What Changes
- Add `client_id_start` configuration option to set the floor/base client ID
- Implement automatic client ID allocation per tool type (CLI, trader GUI, etc.)
- Add lock file mechanism to prevent client ID collisions between concurrent processes
- Update all connection points to use the new client ID management system

## Impact
- Affected specs: ib-connection (new capability)
- Affected code:
  - `src/iborker/config.py` - Add client_id_start setting
  - `src/iborker/connection.py` - Implement ID allocation
  - `src/iborker/trader.py` - Use allocated ID
  - CLI commands - Use allocated IDs per command type
