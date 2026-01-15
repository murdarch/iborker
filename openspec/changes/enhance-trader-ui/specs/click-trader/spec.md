## ADDED Requirements

### Requirement: Market Price Display
The trader SHALL display the executable market price between the quantity input and order buttons, showing the price relevant to the user's current position.

#### Scenario: Long position shows bid price
- **WHEN** user has a long position (position > 0)
- **THEN** display the current bid price (price to sell at market)

#### Scenario: Short position shows ask price
- **WHEN** user has a short position (position < 0)
- **THEN** display the current ask price (price to buy at market)

#### Scenario: Flat position shows last price
- **WHEN** user has no position (position == 0)
- **THEN** display the last traded price

### Requirement: Tick Direction Indicator
The trader SHALL display a visual indicator showing the direction of the last price movement.

#### Scenario: Price uptick indicator
- **WHEN** last price increases from previous tick
- **THEN** display green up triangle (▲) next to the price

#### Scenario: Price downtick indicator
- **WHEN** last price decreases from previous tick
- **THEN** display red down triangle (▼) next to the price

#### Scenario: Price unchanged indicator
- **WHEN** last price equals previous tick
- **THEN** display no triangle or neutral indicator

### Requirement: Points-based P&L Display
The trader SHALL display P&L in points-per-contract as the default mode, with unrealized and daily cumulative values.

#### Scenario: Unrealized P&L in points
- **WHEN** user has a position and P&L mode is "points"
- **THEN** display unrealized P&L as: (current_price - avg_entry_price) in points
- **AND** label it clearly as unrealized

#### Scenario: Daily cumulative P&L in points
- **WHEN** P&L mode is "points"
- **THEN** display cumulative daily P&L (realized + unrealized) for the current contract
- **AND** reset cumulative to zero on contract change or new trading day

#### Scenario: Dollar P&L mode
- **WHEN** user toggles to dollar mode
- **THEN** display P&L in USD (points * multiplier * position)

### Requirement: P&L Display Mode Toggle
The trader SHALL provide a way to toggle between points and dollar P&L display.

#### Scenario: Toggle via UI
- **WHEN** user clicks the P&L display area or toggle button
- **THEN** switch between points and dollar mode
- **AND** persist the preference for the session

### Requirement: Keyboard Shortcuts
The trader SHALL support keyboard shortcuts for rapid order entry without mouse interaction.

#### Scenario: Quantity shortcut (Q)
- **WHEN** user presses Q key
- **THEN** focus the quantity input field
- **AND** select all text for immediate editing

#### Scenario: Buy shortcut (B)
- **WHEN** user presses B key
- **THEN** highlight the BUY button visually
- **AND** require Ctrl+Enter to execute the buy order

#### Scenario: Sell shortcut (S)
- **WHEN** user presses S key
- **THEN** highlight the SELL button visually
- **AND** require Ctrl+Enter to execute the sell order

#### Scenario: Flatten shortcut (F)
- **WHEN** user presses F key
- **THEN** highlight the FLATTEN button visually
- **AND** require Ctrl+Enter to execute the flatten order

#### Scenario: Reverse shortcut (R)
- **WHEN** user presses R key
- **THEN** highlight the REVERSE button visually
- **AND** require Ctrl+Enter to execute the reverse order

#### Scenario: Execute highlighted action (Ctrl+Enter)
- **WHEN** a button is highlighted via keyboard shortcut
- **AND** user presses Ctrl+Enter
- **THEN** execute the highlighted action
- **AND** clear the highlight after execution
