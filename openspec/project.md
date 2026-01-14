# Project Context

## Purpose

iborker is a collection of CLI and lightweight GUI tools for interacting with the Interactive Brokers API, focused on futures trading workflows.

### Planned Tools

1. **Historical Data Downloader** - Download futures market data at standard bar lengths (1, 5, 15, 30, 60 min)
2. **Click Trader** - Simple single-instrument GUI for quick order entry (set contracts, buy/sell/reverse/close)
3. **Options Stdev Analyzer** - Analyze options market to determine 1σ/2σ/3σ price movement ranges for futures
4. **Contract Lookup** (nice-to-have) - Translate between Globex/exchange contract codes and IB identifiers, query current margins

## Tech Stack

- **Python 3.12+** - Primary language
- **ib_insync** - High-level async wrapper for TWS/Gateway API
- **Typer** - CLI framework (modern, type-hint based)
- **Pydantic** - Data validation and configuration
- **ruff** - Linting and formatting (replaces black/isort/flake8)
- **pytest** - Testing framework

### GUI Stack (for Click Trader)
- TBD - likely **DearPyGui** or **PySimpleGUI** for lightweight needs

## Project Conventions

### Code Style

- Format with `ruff format`, lint with `ruff check`
- Type hints required for public functions
- Docstrings for modules and public APIs (Google style)
- snake_case for functions/variables, PascalCase for classes

### Architecture Patterns

- **Shared IB connection module** - Reusable connection/authentication logic
- **CLI as thin layer** - Business logic in separate modules, CLI just wires it up
- **Async-first** - Use ib_insync's async capabilities where beneficial
- **Configuration via environment/files** - No hardcoded credentials or connection details

### Testing Strategy

- pytest with fixtures for IB connection mocking
- Unit tests for data processing and calculations
- Integration tests against TWS paper trading (manual/CI-optional)
- Target: test business logic, not IB library internals

### Git Workflow

- `main` branch for stable releases
- Feature branches for development
- Conventional commits preferred (feat:, fix:, docs:, etc.)

## Domain Context

### Interactive Brokers Concepts

- **TWS/Gateway** - Trading Workstation or IB Gateway must be running locally for API access
- **Contract specification** - IB uses unique identifiers (conId) distinct from exchange symbols
- **Globex codes** - CME's standard futures symbols (ES, NQ, CL, GC, etc.)
- **Bar sizes** - Standard OHLCV data intervals; IB has specific supported durations

### Futures Trading Terms

- **Reverse** - Close current position and open opposite (e.g., long to short)
- **Margin** - Capital required to hold futures position (initial vs maintenance)
- **Standard deviation (σ)** - Statistical measure of expected price range from options implied volatility

## Important Constraints

- **IB API limits** - Rate limits on historical data requests, pacing violations
- **Market hours** - Data availability depends on exchange trading hours
- **Paper vs Live** - Test thoroughly on paper trading before live use
- **No financial advice** - Tools are for personal use; user assumes all trading risk

## External Dependencies

- **TWS or IB Gateway** - Must be running and configured for API access (default port 7497 for TWS paper, 4002 for Gateway paper)
- **Interactive Brokers account** - Required for API access
- **Market data subscriptions** - Some data requires paid subscriptions through IB
