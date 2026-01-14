"""Historical data download functionality."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from ib_insync import Future
from pydantic import BaseModel

from iborker.connection import connect

app = typer.Typer(
    name="history",
    help="Download historical market data.",
    no_args_is_help=True,
)

# IB bar size mappings
BAR_SIZES = {
    1: "1 min",
    5: "5 mins",
    15: "15 mins",
    30: "30 mins",
    60: "1 hour",
}


class BarData(BaseModel):
    """OHLCV bar data."""

    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    average: float
    bar_count: int


async def fetch_historical_data(
    symbol: str,
    exchange: str,
    bar_size: int,
    duration: str,
    end_date: datetime | None = None,
) -> list[BarData]:
    """Fetch historical bars from IB.

    Args:
        symbol: Futures symbol (e.g., ES, NQ, CL)
        exchange: Exchange name (e.g., CME, NYMEX)
        bar_size: Bar size in minutes (1, 5, 15, 30, 60)
        duration: Duration string (e.g., "1 D", "1 W", "1 M")
        end_date: End date for data (default: now)

    Returns:
        List of bar data.
    """
    if bar_size not in BAR_SIZES:
        valid = list(BAR_SIZES.keys())
        raise ValueError(f"Invalid bar size: {bar_size}. Must be one of {valid}")

    contract = Future(symbol=symbol, exchange=exchange)

    async with connect("history") as ib:
        # Qualify the contract to get full details
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            raise ValueError(f"Could not find contract: {symbol} on {exchange}")

        contract = qualified[0]

        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime=end_date or "",
            durationStr=duration,
            barSizeSetting=BAR_SIZES[bar_size],
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
        )

        return [
            BarData(
                date=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                average=bar.average,
                bar_count=bar.barCount,
            )
            for bar in bars
        ]


def export_csv(bars: list[BarData], output: Path) -> None:
    """Export bars to CSV format."""
    with output.open("w") as f:
        f.write("date,open,high,low,close,volume,average,bar_count\n")
        for bar in bars:
            f.write(
                f"{bar.date.isoformat()},{bar.open},{bar.high},{bar.low},"
                f"{bar.close},{bar.volume},{bar.average},{bar.bar_count}\n"
            )


def export_parquet(bars: list[BarData], output: Path) -> None:
    """Export bars to Parquet format."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as err:
        msg = "pyarrow required for Parquet export. Install with: uv add pyarrow"
        raise ImportError(msg) from err

    table = pa.Table.from_pylist([bar.model_dump() for bar in bars])
    pq.write_table(table, output)


@app.command()
def download(
    symbol: Annotated[str, typer.Argument(help="Futures symbol (e.g., ES, NQ, CL)")],
    exchange: Annotated[str, typer.Option("--exchange", "-e", help="Exchange")] = "CME",
    bar_size: Annotated[
        int, typer.Option("--bar-size", "-b", help="Bar size in minutes")
    ] = 5,
    duration: Annotated[
        str, typer.Option("--duration", "-d", help="Duration (e.g., '1 D')")
    ] = "1 D",
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output file path")
    ] = None,
    output_format: Annotated[
        str, typer.Option("--format", "-f", help="Output format (csv, parquet)")
    ] = "csv",
) -> None:
    """Download historical OHLCV data for a futures contract."""
    typer.echo(f"Downloading {symbol} {bar_size}min bars from {exchange}...")

    try:
        bars = asyncio.run(fetch_historical_data(symbol, exchange, bar_size, duration))
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(f"Downloaded {len(bars)} bars")

    if not bars:
        typer.echo("No data returned")
        raise typer.Exit(1)

    # Determine output path
    if output is None:
        output = Path(f"{symbol}_{bar_size}min.{output_format}")

    # Export
    if output_format == "csv":
        export_csv(bars, output)
    elif output_format == "parquet":
        export_parquet(bars, output)
    else:
        typer.echo(f"Unknown format: {output_format}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Saved to {output}")
