# Implementation Tasks

## 1. Market Data State
- [ ] 1.1 Add bid, ask, last_price, prev_last_price to TraderState
- [ ] 1.2 Subscribe to streaming market data (reqMktData) and handle tickPrice events
- [ ] 1.3 Track tick direction (up/down/unchanged) based on last price changes

## 2. Market Price Display
- [ ] 2.1 Add price display widget between quantity input and BUY/SELL buttons
- [ ] 2.2 Implement position-aware price logic (bid if long, ask if short, last if flat)
- [ ] 2.3 Add tick direction indicator (▲/▼) with green/red coloring

## 3. Points-based P&L
- [ ] 3.1 Add contract multiplier lookup (from contracts.py FUTURES_DATABASE)
- [ ] 3.2 Calculate unrealized P&L in points: (current_price - avg_cost) * position / multiplier
- [ ] 3.3 Track daily realized P&L (reset on contract change or new day)
- [ ] 3.4 Add cumulative daily points display
- [ ] 3.5 Add P&L mode toggle (points vs $) with state persistence

## 4. P&L Display Update
- [ ] 4.1 Replace single P&L text with dual display (unrealized / cumulative)
- [ ] 4.2 Add toggle button or keyboard shortcut for $ vs points mode
- [ ] 4.3 Update _update_display() to format based on current mode

## 5. Keyboard Shortcuts
- [ ] 5.1 Register global key handler with dpg.set_key_callback or handler registry
- [ ] 5.2 Implement Q shortcut: focus quantity input, allow immediate editing
- [ ] 5.3 Implement B/S/F/R shortcuts: highlight corresponding button, require Ctrl+Enter to execute
- [ ] 5.4 Implement Ctrl+Enter: execute the currently highlighted action
- [ ] 5.5 Add visual feedback for highlighted button (outline or glow)

## 6. Testing
- [ ] 6.1 Verify market price updates correctly based on position
- [ ] 6.2 Verify P&L calculations match expected points values
- [ ] 6.3 Test keyboard shortcuts execute correct actions
- [ ] 6.4 Test Ctrl+Enter safety mechanism prevents accidental trades
