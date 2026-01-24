## ADDED Requirements

### Requirement: Roll Status Detection

The system SHALL detect the roll status of futures contracts by comparing open interest between the front-month and next-available liquid contract.

Roll status categories:
- **Pre-roll**: Deferred OI ratio < 20% → Trade front month
- **Rolling**: Deferred OI ratio 20-80% → Transitioning (recommend based on 50% threshold)
- **Post-roll**: Deferred OI ratio > 80% → Trade deferred month

#### Scenario: Pre-roll equity index futures
- **GIVEN** ES front-month has 1,875,000 OI and deferred has 10,000 OI
- **WHEN** roll status is requested for ES
- **THEN** status is "pre-roll" with ratio 0.5% and recommendation "Trade ESH6"

#### Scenario: Actively rolling agricultural futures
- **GIVEN** ZC front-month has 658,000 OI and deferred has 320,000 OI
- **WHEN** roll status is requested for ZC
- **THEN** status is "rolling" with ratio 33% and recommendation "Consider ZCK6"

#### Scenario: Post-roll energy futures
- **GIVEN** CL front-month has 50,000 OI and deferred has 400,000 OI
- **WHEN** roll status is requested for CL
- **THEN** status is "post-roll" with ratio 89% and recommendation "Trade CLJ6"

---

### Requirement: Active Contract Selection

The system SHALL provide a function to return the recommended contract for trading based on current roll status.

#### Scenario: Select front-month when pre-roll
- **GIVEN** ES deferred OI ratio is 0.5%
- **WHEN** active contract is requested for ES
- **THEN** the front-month contract (ESH6) is returned

#### Scenario: Select deferred when ratio exceeds 50%
- **GIVEN** ZC deferred OI ratio is 55%
- **WHEN** active contract is requested for ZC
- **THEN** the deferred contract (ZCK6) is returned

---

### Requirement: Liquid Month Filtering

The system SHALL filter contract chains to only include liquid trading months based on product type.

Liquid month patterns:
- **Quarterly** (ES, NQ, RTY, 6E, etc.): H (Mar), M (Jun), U (Sep), Z (Dec)
- **Monthly** (CL, NG, GC, SI): All months
- **Agricultural** (ZC, ZS, ZW): H (Mar), K (May), N (Jul), U (Sep), Z (Dec)

#### Scenario: Filter equity futures to quarterlies
- **GIVEN** IB returns ES contracts for Jan, Feb, Mar, Jun, Sep, Dec
- **WHEN** contract chain is fetched for ES
- **THEN** only Mar, Jun, Sep, Dec contracts are included

#### Scenario: Filter corn to trading months
- **GIVEN** IB returns ZC contracts for all 12 months
- **WHEN** contract chain is fetched for ZC
- **THEN** only Mar, May, Jul, Sep, Dec contracts are included

---

### Requirement: CLI Roll Status Command

The system SHALL provide a CLI command to display roll status for futures symbols.

Output columns: Symbol, Front, Back, OI Ratio, Status, Recommendation

#### Scenario: Check multiple symbols
- **WHEN** user runs `iborker roll status ES NQ CL ZC`
- **THEN** output shows roll status table for all four symbols

#### Scenario: Show only rolling symbols
- **WHEN** user runs `iborker roll today`
- **THEN** output shows only symbols with status "rolling"

---

### Requirement: Roll-Aware Trader Integration

The system SHALL provide an option for the Click Trader to use roll-aware contract selection.

#### Scenario: Trader uses roll-aware selection
- **GIVEN** ZC deferred OI ratio is 55%
- **WHEN** user enters "ZC" in trader with roll-aware mode enabled
- **THEN** trader resolves to ZCK6 (deferred) instead of ZCH6 (front)
