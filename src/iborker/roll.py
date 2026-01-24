"""Futures roll detection based on open interest analysis."""

import asyncio
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Annotated

import typer
from ib_insync import IB, Contract, Future

from iborker.connection import connect
from iborker.contracts import (
    FUTURES_DATABASE,
    get_liquid_months,
    get_symbol_info,
    resolve_symbol,
)

app = typer.Typer(
    name="roll",
    help="Futures roll detection and contract recommendations.",
    no_args_is_help=True,
)


class RollState(str, Enum):
    """Roll status categories based on OI ratio."""

    PRE_ROLL = "pre-roll"
    ROLLING = "rolling"
    POST_ROLL = "post-roll"
    UNKNOWN = "unknown"


@dataclass
class RollStatus:
    """Roll status for a futures symbol."""

    symbol: str
    state: RollState
    ratio: float  # deferred_oi / (front_oi + deferred_oi)
    front_contract: Contract | None
    back_contract: Contract | None
    front_oi: float
    back_oi: float
    recommendation: str

    @property
    def is_rolling(self) -> bool:
        """True if actively rolling (20-80% ratio)."""
        return self.state == RollState.ROLLING


# Thresholds for roll status
RATIO_PRE_ROLL = 0.20  # Below this = pre-roll
RATIO_CROSSOVER = 0.50  # Above this = recommend deferred
RATIO_POST_ROLL = 0.80  # Above this = post-roll


def calculate_roll_state(front_oi: float, back_oi: float) -> tuple[RollState, float]:
    """Calculate roll state from OI values.

    Args:
        front_oi: Open interest in front-month contract.
        back_oi: Open interest in deferred contract.

    Returns:
        Tuple of (RollState, ratio).
    """
    total = front_oi + back_oi
    if total == 0:
        return RollState.UNKNOWN, 0.0

    ratio = back_oi / total

    if ratio < RATIO_PRE_ROLL:
        return RollState.PRE_ROLL, ratio
    elif ratio >= RATIO_POST_ROLL:
        return RollState.POST_ROLL, ratio
    else:
        return RollState.ROLLING, ratio


async def get_contract_chain(
    ib: IB, symbol: str, exchange: str | None = None
) -> list[Contract]:
    """Get available contracts for a symbol, filtered to liquid months.

    Args:
        ib: Connected IB instance.
        symbol: Base symbol (ES, NQ, CL, etc.) or alias (6E, 6J, etc.).
        exchange: Exchange override (auto-detected if not provided).

    Returns:
        List of contracts sorted by expiration, filtered to liquid months.
    """
    symbol = resolve_symbol(symbol.upper())

    # Get exchange from database if not provided
    if exchange is None:
        info = get_symbol_info(symbol)
        if info:
            exchange = info[0]
        else:
            exchange = "CME"

    # Query all contracts for this symbol
    contract = Future(symbol=symbol, exchange=exchange)
    details = await ib.reqContractDetailsAsync(contract)

    if not details:
        return []

    # Get liquid months for filtering
    liquid_months = get_liquid_months(symbol)
    today = date.today().strftime("%Y%m%d")

    # Filter to liquid months and future expirations
    filtered = []
    for d in details:
        expiry = d.contract.lastTradeDateOrContractMonth
        if expiry < today:
            continue

        # Extract month from expiry (YYYYMMDD format)
        month = expiry[4:6]
        if month in liquid_months:
            filtered.append(d.contract)

    # Sort by expiration
    filtered.sort(key=lambda c: c.lastTradeDateOrContractMonth)
    return filtered


async def get_oi_snapshot(ib: IB, contracts: list[Contract]) -> dict[str, float]:
    """Fetch open interest for contracts via streaming market data.

    Args:
        ib: Connected IB instance.
        contracts: List of qualified contracts.

    Returns:
        Dict mapping localSymbol to OI value.
    """
    if not contracts:
        return {}

    # Request streaming market data with tick 588 for futures OI
    tickers = []
    for contract in contracts:
        ticker = ib.reqMktData(contract, genericTickList="588", snapshot=False)
        tickers.append((contract, ticker))

    # Wait for data to arrive
    await asyncio.sleep(2.5)

    # Collect OI values
    result = {}
    for contract, ticker in tickers:
        oi = ticker.futuresOpenInterest
        # Check for NaN
        if oi == oi:  # NaN check: NaN != NaN
            result[contract.localSymbol] = oi
        else:
            result[contract.localSymbol] = 0.0

        # Cancel subscription
        ib.cancelMktData(contract)

    return result


async def get_roll_status(ib: IB, symbol: str) -> RollStatus:
    """Get roll status for a futures symbol.

    Args:
        ib: Connected IB instance.
        symbol: Base symbol (ES, NQ, CL, etc.) or alias (6E, 6J, etc.).

    Returns:
        RollStatus with state, ratio, and recommendation.
    """
    symbol = resolve_symbol(symbol.upper())

    # Get contract chain
    chain = await get_contract_chain(ib, symbol)

    if len(chain) < 2:
        return RollStatus(
            symbol=symbol,
            state=RollState.UNKNOWN,
            ratio=0.0,
            front_contract=chain[0] if chain else None,
            back_contract=None,
            front_oi=0.0,
            back_oi=0.0,
            recommendation="Insufficient contracts",
        )

    front = chain[0]
    back = chain[1]

    # Qualify contracts
    await ib.qualifyContractsAsync(front, back)

    # Get OI snapshots
    oi_data = await get_oi_snapshot(ib, [front, back])

    front_oi = oi_data.get(front.localSymbol, 0.0)
    back_oi = oi_data.get(back.localSymbol, 0.0)

    # Calculate state
    state, ratio = calculate_roll_state(front_oi, back_oi)

    # Generate recommendation
    if state == RollState.PRE_ROLL:
        recommendation = f"Trade {front.localSymbol}"
    elif state == RollState.POST_ROLL:
        recommendation = f"Trade {back.localSymbol}"
    elif ratio >= RATIO_CROSSOVER:
        recommendation = f"Trade {back.localSymbol}"
    else:
        recommendation = f"Consider {back.localSymbol}"

    return RollStatus(
        symbol=symbol,
        state=state,
        ratio=ratio,
        front_contract=front,
        back_contract=back,
        front_oi=front_oi,
        back_oi=back_oi,
        recommendation=recommendation,
    )


async def get_active_contract(ib: IB, symbol: str) -> Contract | None:
    """Get the recommended active contract for trading.

    Returns the front-month if pre-roll, deferred if post-roll or
    ratio > 50%.

    Args:
        ib: Connected IB instance.
        symbol: Base symbol (ES, NQ, CL, etc.).

    Returns:
        Recommended contract, or None if unavailable.
    """
    status = await get_roll_status(ib, symbol)

    if status.state == RollState.UNKNOWN:
        return status.front_contract

    if status.state == RollState.POST_ROLL or status.ratio >= RATIO_CROSSOVER:
        return status.back_contract

    return status.front_contract


async def get_all_roll_statuses(ib: IB) -> list[RollStatus]:
    """Get roll status for all symbols in FUTURES_DATABASE.

    Args:
        ib: Connected IB instance.

    Returns:
        List of RollStatus for all symbols.
    """
    results = []

    for symbol in sorted(FUTURES_DATABASE.keys()):
        try:
            status = await get_roll_status(ib, symbol)
            results.append(status)
        except Exception:
            # Skip symbols that fail (e.g., no market data subscription)
            results.append(
                RollStatus(
                    symbol=symbol,
                    state=RollState.UNKNOWN,
                    ratio=0.0,
                    front_contract=None,
                    back_contract=None,
                    front_oi=0.0,
                    back_oi=0.0,
                    recommendation="Error fetching data",
                )
            )

    return results


# =============================================================================
# CLI Commands
# =============================================================================


def _format_oi(oi: float) -> str:
    """Format OI value with K/M suffix."""
    if oi >= 1_000_000:
        return f"{oi / 1_000_000:.1f}M"
    elif oi >= 1_000:
        return f"{oi / 1_000:.0f}K"
    else:
        return f"{oi:.0f}"


def _print_status_table(statuses: list[RollStatus]) -> None:
    """Print roll status table."""
    # Header
    typer.echo()
    typer.echo(
        f"{'Symbol':<8} {'Front':<8} {'Back':<8} {'Front OI':>10} {'Back OI':>10} "
        f"{'Ratio':>7} {'Status':<10} {'Recommendation'}"
    )
    typer.echo("-" * 90)

    for s in statuses:
        front = s.front_contract.localSymbol if s.front_contract else "-"
        back = s.back_contract.localSymbol if s.back_contract else "-"

        # Status indicator
        if s.state == RollState.ROLLING:
            status_str = "ROLLING"
        elif s.state == RollState.POST_ROLL:
            status_str = "post-roll"
        elif s.state == RollState.PRE_ROLL:
            status_str = "pre-roll"
        else:
            status_str = "unknown"

        back_oi = _format_oi(s.back_oi)
        typer.echo(
            f"{s.symbol:<8} {front:<8} {back:<8} {_format_oi(s.front_oi):>10} "
            f"{back_oi:>10} {s.ratio:>6.1%} {status_str:<10} {s.recommendation}"
        )


async def _status_impl(symbols: list[str]) -> None:
    """Implementation of status command."""
    async with connect("roll") as ib:
        statuses = []
        for symbol in symbols:
            typer.echo(f"Checking {symbol}...", nl=False)
            status = await get_roll_status(ib, symbol)
            statuses.append(status)
            typer.echo(" done")

        _print_status_table(statuses)


async def _today_impl() -> None:
    """Implementation of today command."""
    typer.echo(f"Checking {len(FUTURES_DATABASE)} symbols for active rolls...")

    async with connect("roll") as ib:
        statuses = await get_all_roll_statuses(ib)

    # Filter to rolling only
    rolling = [s for s in statuses if s.state == RollState.ROLLING]

    if not rolling:
        typer.echo("\nNo symbols actively rolling.")
        return

    typer.echo(f"\n{len(rolling)} of {len(statuses)} symbols actively rolling:")
    _print_status_table(rolling)


@app.command("status")
def status_cmd(
    symbols: Annotated[
        list[str] | None,
        typer.Argument(help="Symbols to check (e.g., ES NQ CL ZC)"),
    ] = None,
) -> None:
    """Show roll status for futures symbols.

    Displays open interest ratio between front-month and deferred contracts
    to help determine which contract to trade.

    Examples:
        iborker roll status ES NQ CL
        iborker roll status ZC ZS ZW
    """
    if not symbols:
        typer.echo("Provide symbols to check, e.g.: iborker roll status ES NQ CL")
        raise typer.Exit(1)

    # Resolve aliases (6E -> EUR, etc.) and validate
    resolved = [resolve_symbol(s.upper()) for s in symbols]
    unknown = [s for s in resolved if s not in FUTURES_DATABASE]
    if unknown:
        typer.echo(f"Unknown symbols: {', '.join(unknown)}", err=True)
        raise typer.Exit(1)

    symbols = resolved

    try:
        asyncio.run(_status_impl(symbols))
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


@app.command("today")
def today_cmd() -> None:
    """Show symbols that are actively rolling.

    Checks all symbols in the database and displays only those
    with status 'rolling' (OI ratio between 20-80%).

    Use this before trading sessions to identify contracts
    that may need attention.
    """
    try:
        asyncio.run(_today_impl())
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e
