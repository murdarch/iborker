"""Contract lookup and symbol translation utilities."""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from ib_insync import Future
from pydantic import BaseModel

from iborker.connection import connect

app = typer.Typer(
    name="contract",
    help="Contract lookup and symbol translation.",
    no_args_is_help=True,
)

# Common Globex/exchange futures symbols
# Format: symbol -> (exchange, name, multiplier, tick_size, liquid_months)
# liquid_months: "HMUZ" = quarterly, "ALL" = monthly, "HKNUZ" = ag months
FUTURES_DATABASE: dict[str, tuple[str, str, float, float, str]] = {
    # CME Equity Index (quarterly)
    "ES": ("CME", "E-mini S&P 500", 50.0, 0.25, "HMUZ"),
    "NQ": ("CME", "E-mini NASDAQ-100", 20.0, 0.25, "HMUZ"),
    "RTY": ("CME", "E-mini Russell 2000", 50.0, 0.10, "HMUZ"),
    "YM": ("CBOT", "E-mini Dow ($5)", 5.0, 1.0, "HMUZ"),
    "MES": ("CME", "Micro E-mini S&P 500", 5.0, 0.25, "HMUZ"),
    "MNQ": ("CME", "Micro E-mini NASDAQ-100", 2.0, 0.25, "HMUZ"),
    "MYM": ("CBOT", "Micro E-mini Dow", 0.5, 1.0, "HMUZ"),
    "M2K": ("CME", "Micro E-mini Russell 2000", 5.0, 0.10, "HMUZ"),
    # CME FX (quarterly) - IB uses currency codes, not Globex codes
    "EUR": ("CME", "Euro FX (6E)", 125000.0, 0.00005, "HMUZ"),
    "JPY": ("CME", "Japanese Yen (6J)", 12500000.0, 0.0000005, "HMUZ"),
    "GBP": ("CME", "British Pound (6B)", 62500.0, 0.0001, "HMUZ"),
    "AUD": ("CME", "Australian Dollar (6A)", 100000.0, 0.0001, "HMUZ"),
    "CAD": ("CME", "Canadian Dollar (6C)", 100000.0, 0.00005, "HMUZ"),
    "CHF": ("CME", "Swiss Franc (6S)", 125000.0, 0.0001, "HMUZ"),
    # NYMEX Energy (monthly)
    "CL": ("NYMEX", "Crude Oil", 1000.0, 0.01, "ALL"),
    "NG": ("NYMEX", "Natural Gas", 10000.0, 0.001, "ALL"),
    "RB": ("NYMEX", "RBOB Gasoline", 42000.0, 0.0001, "ALL"),
    "HO": ("NYMEX", "Heating Oil", 42000.0, 0.0001, "ALL"),
    "MCL": ("NYMEX", "Micro Crude Oil", 100.0, 0.01, "ALL"),
    # COMEX Metals (monthly)
    "GC": ("COMEX", "Gold", 100.0, 0.10, "ALL"),
    "SI": ("COMEX", "Silver", 5000.0, 0.005, "ALL"),
    "HG": ("COMEX", "Copper", 25000.0, 0.0005, "ALL"),
    "MGC": ("COMEX", "Micro Gold", 10.0, 0.10, "ALL"),
    # CBOT Grains (ag months: Mar, May, Jul, Sep, Dec)
    "ZC": ("CBOT", "Corn", 50.0, 0.25, "HKNUZ"),
    "ZS": ("CBOT", "Soybeans", 50.0, 0.25, "HKNUZ"),
    "ZW": ("CBOT", "Wheat", 50.0, 0.25, "HKNUZ"),
    "ZM": ("CBOT", "Soybean Meal", 100.0, 0.10, "HKNUZ"),
    "ZL": ("CBOT", "Soybean Oil", 60000.0, 0.01, "HKNUZ"),
    # CBOT Treasuries (quarterly)
    "ZB": ("CBOT", "30-Year T-Bond", 1000.0, 0.03125, "HMUZ"),
    "UB": ("CBOT", "Ultra T-Bond", 1000.0, 0.03125, "HMUZ"),
    "ZN": ("CBOT", "10-Year T-Note", 1000.0, 0.015625, "HMUZ"),
    "ZF": ("CBOT", "5-Year T-Note", 1000.0, 0.0078125, "HMUZ"),
    "ZT": ("CBOT", "2-Year T-Note", 2000.0, 0.0078125, "HMUZ"),
    # Crypto (monthly)
    "MBT": ("CME", "Micro Bitcoin", 0.1, 5.0, "ALL"),
}


class ContractInfo(BaseModel):
    """Detailed contract information."""

    symbol: str
    local_symbol: str
    exchange: str
    name: str
    con_id: int
    multiplier: float
    tick_size: float
    currency: str
    last_trade_date: str | None = None


@dataclass
class MarginInfo:
    """Margin requirements for a contract."""

    symbol: str
    initial_margin: float
    maintenance_margin: float
    currency: str = "USD"


def get_known_symbols() -> list[str]:
    """Return list of known Globex symbols."""
    return sorted(FUTURES_DATABASE.keys())


# Aliases for Globex codes to IB symbols
SYMBOL_ALIASES = {
    "6E": "EUR",
    "6J": "JPY",
    "6B": "GBP",
    "6A": "AUD",
    "6C": "CAD",
    "6S": "CHF",
}


def resolve_symbol(symbol: str) -> str:
    """Resolve a symbol alias to its canonical IB symbol."""
    symbol = symbol.upper()
    return SYMBOL_ALIASES.get(symbol, symbol)


def get_symbol_info(symbol: str) -> tuple[str, str, float, float, str] | None:
    """Get static info for a symbol from the database.

    Returns:
        Tuple of (exchange, name, multiplier, tick_size, liquid_months) or None.
    """
    symbol = resolve_symbol(symbol.upper())
    return FUTURES_DATABASE.get(symbol)


# Month code to number mapping
MONTH_CODES = {
    "F": "01",
    "G": "02",
    "H": "03",
    "J": "04",
    "K": "05",
    "N": "07",
    "M": "06",
    "Q": "08",
    "U": "09",
    "V": "10",
    "X": "11",
    "Z": "12",
}


def get_liquid_months(symbol: str) -> set[str]:
    """Get the set of liquid month codes for a symbol.

    Returns:
        Set of month numbers (e.g., {"03", "06", "09", "12"} for quarterly).
    """
    info = get_symbol_info(symbol)
    if not info:
        return set(MONTH_CODES.values())  # Default to all months

    liquid_months = info[4]
    if liquid_months == "ALL":
        return set(MONTH_CODES.values())

    return {MONTH_CODES[code] for code in liquid_months if code in MONTH_CODES}


def get_front_month_code() -> str:
    """Get the likely front month contract code based on current date."""
    now = datetime.now()
    month_codes = "FGHJKMNQUVXZ"  # Jan-Dec

    # Simple heuristic: current month if before 15th, next month otherwise
    if now.day < 15:
        month_idx = now.month - 1
    else:
        month_idx = now.month % 12

    year = now.year % 10
    if now.day >= 15 and now.month == 12:
        year = (now.year + 1) % 10

    return f"{month_codes[month_idx]}{year}"


async def resolve_front_month(ib, symbol: str, exchange: str = "CME") -> Future | None:
    """Resolve a symbol to its front month contract.

    Args:
        ib: Connected IB instance
        symbol: Base symbol (ES, NQ, etc.) or specific contract (ESH6)
        exchange: Exchange name

    Returns:
        Qualified front month contract, or None if not found.
    """
    from datetime import date

    symbol = symbol.upper().strip()

    # Try as specific local symbol first (e.g., ESH6)
    contract = Future(localSymbol=symbol, exchange=exchange)
    qualified = await ib.qualifyContractsAsync(contract)
    if len(qualified) == 1:
        return qualified[0]

    # Try as base symbol - get all contracts and find front month
    contract = Future(symbol=symbol, exchange=exchange)
    details = await ib.reqContractDetailsAsync(contract)

    if not details:
        return None

    # Filter to quarterly months (H=Mar, M=Jun, U=Sep, Z=Dec)
    quarterly_codes = {"H", "M", "U", "Z"}
    today = date.today().strftime("%Y%m%d")

    quarterly_contracts = []
    for d in details:
        local = d.contract.localSymbol
        if len(local) >= 2:
            month_code = local[-2]
            if month_code in quarterly_codes:
                expiry = d.contract.lastTradeDateOrContractMonth
                if expiry >= today:
                    quarterly_contracts.append((expiry, d.contract))

    if not quarterly_contracts:
        # Fallback: nearest available contract
        all_contracts = [
            (d.contract.lastTradeDateOrContractMonth, d.contract)
            for d in details
            if d.contract.lastTradeDateOrContractMonth >= today
        ]
        if all_contracts:
            all_contracts.sort(key=lambda x: x[0])
            return all_contracts[0][1]
        return None

    quarterly_contracts.sort(key=lambda x: x[0])
    return quarterly_contracts[0][1]


async def lookup_contract(
    symbol: str, exchange: str | None = None
) -> ContractInfo | None:
    """Look up contract details from IB.

    Args:
        symbol: Globex symbol (e.g., ES, NQ, CL)
        exchange: Exchange override (auto-detected from database if not provided)

    Returns:
        Contract info if found, None otherwise.
    """
    # Get exchange from database if not provided
    if exchange is None:
        info = get_symbol_info(symbol)
        if info:
            exchange = info[0]
        else:
            exchange = "CME"  # Default fallback

    contract = Future(symbol=symbol, exchange=exchange)

    async with connect("contracts") as ib:
        qualified = await ib.qualifyContractsAsync(contract)

        if not qualified:
            return None

        c = qualified[0]
        info = get_symbol_info(symbol)
        name = info[1] if info else symbol

        return ContractInfo(
            symbol=symbol,
            local_symbol=c.localSymbol,
            exchange=c.exchange,
            name=name,
            con_id=c.conId,
            multiplier=float(c.multiplier) if c.multiplier else 0.0,
            tick_size=float(c.minTick) if c.minTick else 0.0,
            currency=c.currency,
            last_trade_date=c.lastTradeDateOrContractMonth,
        )


async def get_margin(symbol: str, exchange: str | None = None) -> MarginInfo | None:
    """Get margin requirements for a contract using whatIfOrder.

    Submits a simulated BUY order to get margin impact from IB.
    Requires a funded account with trading permissions.

    Args:
        symbol: Globex symbol (e.g., ES, NQ, CL)
        exchange: Exchange override (auto-detected if not provided)

    Returns:
        MarginInfo with initial and maintenance margin, or None if unavailable.
    """
    from ib_insync import MarketOrder

    if exchange is None:
        info = get_symbol_info(symbol)
        if info:
            exchange = info[0]
        else:
            exchange = "CME"

    contract = Future(symbol=symbol, exchange=exchange)

    async with connect("contracts") as ib:
        qualified = await ib.qualifyContractsAsync(contract)

        if not qualified:
            return None

        c = qualified[0]

        # Use whatIfOrder to get margin requirements
        # This simulates placing an order without actually submitting it
        order = MarketOrder("BUY", 1)

        try:
            order_state = await ib.whatIfOrderAsync(c, order)
        except Exception:
            # whatIfOrder may fail on some account types or contracts
            return None

        if order_state is None:
            return None

        # Parse margin values - they come as strings with currency
        init_margin = _parse_margin_value(order_state.initMarginChange)
        maint_margin = _parse_margin_value(order_state.maintMarginChange)

        if init_margin is None:
            return None

        return MarginInfo(
            symbol=symbol,
            initial_margin=init_margin,
            maintenance_margin=maint_margin or init_margin,
            currency="USD",
        )


def _parse_margin_value(value: str | None) -> float | None:
    """Parse margin value string from IB (e.g., '12345.67' or '12,345.67')."""
    if not value:
        return None
    try:
        # Remove commas and currency symbols
        cleaned = value.replace(",", "").replace("$", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


# Cache file for offline lookups
CACHE_FILE = Path.home() / ".iborker" / "contract_cache.json"


def save_to_cache(info: ContractInfo) -> None:
    """Save contract info to local cache."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    cache = {}
    if CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text())

    cache[info.symbol] = info.model_dump()
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def load_from_cache(symbol: str) -> ContractInfo | None:
    """Load contract info from local cache."""
    if not CACHE_FILE.exists():
        return None

    cache = json.loads(CACHE_FILE.read_text())
    if symbol in cache:
        return ContractInfo(**cache[symbol])
    return None


@app.command()
def lookup(
    symbol: Annotated[str, typer.Argument(help="Globex symbol (e.g., ES, NQ, CL)")],
    exchange: Annotated[
        str | None, typer.Option("--exchange", "-e", help="Exchange override")
    ] = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Use cached data only")
    ] = False,
) -> None:
    """Look up contract details for a futures symbol."""
    symbol = symbol.upper()

    # Try cache first if offline mode
    if offline:
        info = load_from_cache(symbol)
        if info:
            _display_contract(info, cached=True)
        else:
            typer.echo(f"No cached data for {symbol}", err=True)
            raise typer.Exit(1)
        return

    # Check static database first
    static = get_symbol_info(symbol)
    if static:
        typer.echo(f"Static info: {static[1]} on {static[0]}")
        typer.echo(f"  Multiplier: {static[2]}, Tick: {static[3]}")
        typer.echo()

    # Query IB for live data
    typer.echo(f"Querying IB for {symbol}...")

    try:
        info = asyncio.run(lookup_contract(symbol, exchange))
    except Exception as e:
        typer.echo(f"Error connecting to IB: {e}", err=True)

        # Fall back to cache
        info = load_from_cache(symbol)
        if info:
            typer.echo("Using cached data:")
            _display_contract(info, cached=True)
            return

        raise typer.Exit(1) from e

    if info:
        _display_contract(info)
        save_to_cache(info)
    else:
        typer.echo(f"Contract not found: {symbol}", err=True)
        raise typer.Exit(1)


@app.command("list")
def list_symbols(
    exchange: Annotated[
        str | None, typer.Option("--exchange", "-e", help="Filter by exchange")
    ] = None,
) -> None:
    """List known futures symbols."""
    symbols = get_known_symbols()

    if exchange:
        exchange = exchange.upper()
        symbols = [s for s in symbols if FUTURES_DATABASE[s][0] == exchange]

    typer.echo(f"Known symbols ({len(symbols)}):\n")

    # Group by exchange
    by_exchange: dict[str, list[str]] = {}
    for sym in symbols:
        exch = FUTURES_DATABASE[sym][0]
        if exch not in by_exchange:
            by_exchange[exch] = []
        by_exchange[exch].append(sym)

    for exch in sorted(by_exchange.keys()):
        typer.echo(f"{exch}:")
        for sym in sorted(by_exchange[exch]):
            name = FUTURES_DATABASE[sym][1]
            typer.echo(f"  {sym:6} - {name}")
        typer.echo()


@app.command()
def margin(
    symbol: Annotated[str, typer.Argument(help="Globex symbol (e.g., ES, NQ, CL)")],
    exchange: Annotated[
        str | None, typer.Option("--exchange", "-e", help="Exchange override")
    ] = None,
) -> None:
    """Query margin requirements for a futures contract.

    Uses IB's whatIfOrder to get current margin requirements.
    Requires an active IB connection with trading permissions.
    """
    symbol = symbol.upper()

    # Show static info first
    static = get_symbol_info(symbol)
    if static:
        typer.echo(f"{static[1]} ({symbol}) on {static[0]}")
    else:
        typer.echo(f"Querying margin for {symbol}...")

    try:
        info = asyncio.run(get_margin(symbol, exchange))
    except Exception as e:
        typer.echo(f"Error connecting to IB: {e}", err=True)
        raise typer.Exit(1) from e

    if info:
        typer.echo()
        typer.echo("Margin Requirements (per contract):")
        typer.echo("=" * 40)
        typer.echo(f"Initial Margin:     ${info.initial_margin:,.2f}")
        typer.echo(f"Maintenance Margin: ${info.maintenance_margin:,.2f}")
    else:
        typer.echo("Margin data unavailable", err=True)
        typer.echo("(Requires funded account with trading permissions)", err=True)
        raise typer.Exit(1)


def _display_contract(info: ContractInfo, cached: bool = False) -> None:
    """Display contract info in a formatted way."""
    cache_note = " (cached)" if cached else ""
    typer.echo(f"\n{info.name}{cache_note}")
    typer.echo("=" * 40)
    typer.echo(f"Symbol:       {info.symbol}")
    typer.echo(f"Local Symbol: {info.local_symbol}")
    typer.echo(f"Exchange:     {info.exchange}")
    typer.echo(f"Con ID:       {info.con_id}")
    typer.echo(f"Multiplier:   {info.multiplier}")
    typer.echo(f"Tick Size:    {info.tick_size}")
    typer.echo(f"Currency:     {info.currency}")
    if info.last_trade_date:
        typer.echo(f"Expiry:       {info.last_trade_date}")
