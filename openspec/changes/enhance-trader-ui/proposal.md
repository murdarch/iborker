# Change: Enhance Click Trader UI

## Why
The click trader needs better market awareness and faster execution for active trading. Users need to see the executable price before clicking, understand P&L in points (standard for futures), and use keyboard shortcuts for rapid order entry without mouse interaction.

## What Changes
- **Market Price Display**: Show bid (if long), ask (if short), or last (if flat) between quantity and order buttons, with tick direction indicator (▲ green / ▼ red)
- **Points-based P&L**: Default to points-per-contract display with daily cumulative points for the selected contract; toggle to traditional $ view
- **Keyboard Shortcuts**: Q (quantity), B (buy), S (sell), F (flatten), R (reverse) with Ctrl+Enter to execute order buttons

## Impact
- Affected specs: click-trader (new capability spec)
- Affected code:
  - `src/iborker/trader.py` - All UI and state changes
  - `src/iborker/contracts.py` - May need multiplier lookup for points calculation
