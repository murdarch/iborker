"""Options standard deviation analyzer."""

import asyncio
import math
from datetime import datetime
from enum import Enum
from typing import Annotated

import typer
from ib_insync import Contract, Future, FuturesOption, Index, Option
from pydantic import BaseModel

from iborker.connection import connect

app = typer.Typer(
    name="stdev",
    help="Options-based expected move calculator.",
    no_args_is_help=True,
)

# Common futures and their exchanges
FUTURES_EXCHANGES = {
    "ES": "CME",
    "NQ": "CME",
    "RTY": "CME",
    "YM": "CBOT",
    "CL": "NYMEX",
    "GC": "COMEX",
    "SI": "COMEX",
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZC": "CBOT",
    "ZS": "CBOT",
    "ZW": "CBOT",
}


class OptionChainParams(BaseModel):
    """Option chain parameters from IB."""

    exchange: str
    underlying_con_id: int
    trading_class: str
    multiplier: str
    expirations: list[str]
    strikes: list[float]


class ATMOption(BaseModel):
    """ATM option data."""

    symbol: str
    expiration: str
    strike: float
    right: str  # C or P
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    model_iv: float | None = None
    underlying_price: float | None = None


class OptionsChainResult(BaseModel):
    """Result of options chain fetch."""

    symbol: str
    exchange: str
    underlying_price: float
    atm_strike: float
    options: list[ATMOption]


class ExtractedIV(BaseModel):
    """Extracted implied volatility from options chain."""

    symbol: str
    expiration: str
    underlying_price: float
    atm_strike: float
    atm_iv: float  # Averaged IV from ATM call/put
    call_iv: float | None = None  # ATM call IV
    put_iv: float | None = None  # ATM put IV
    iv_source: str = "model"  # "model" or "mid_price"


def extract_iv(chain_result: OptionsChainResult) -> ExtractedIV:
    """Extract ATM implied volatility from options chain.

    Averages call and put IV at the ATM strike for a more stable reading.
    Uses IB model IV when available.

    Args:
        chain_result: Options chain result from fetch_options_chain()

    Returns:
        Extracted IV data with ATM volatility.

    Raises:
        ValueError: If no valid IV data found at ATM strike.
    """
    atm_strike = chain_result.atm_strike

    # Find ATM call and put
    atm_call: ATMOption | None = None
    atm_put: ATMOption | None = None

    for opt in chain_result.options:
        if opt.strike == atm_strike:
            if opt.right == "C":
                atm_call = opt
            elif opt.right == "P":
                atm_put = opt

    if atm_call is None and atm_put is None:
        raise ValueError(f"No ATM options found at strike {atm_strike}")

    # Extract IVs
    call_iv = atm_call.model_iv if atm_call else None
    put_iv = atm_put.model_iv if atm_put else None

    # Calculate averaged ATM IV
    valid_ivs = [iv for iv in [call_iv, put_iv] if iv is not None]
    if not valid_ivs:
        raise ValueError(
            f"No valid IV data for ATM options at strike {atm_strike}. "
            "Market may be closed or options not trading."
        )

    atm_iv = sum(valid_ivs) / len(valid_ivs)

    # Get expiration from first available option
    expiration = chain_result.options[0].expiration if chain_result.options else ""

    return ExtractedIV(
        symbol=chain_result.symbol,
        expiration=expiration,
        underlying_price=chain_result.underlying_price,
        atm_strike=atm_strike,
        atm_iv=atm_iv,
        call_iv=call_iv,
        put_iv=put_iv,
        iv_source="model",
    )


class Timeframe(str, Enum):
    """Timeframe for expected move calculation."""

    DAILY = "daily"
    WEEKLY = "weekly"
    EXPIRATION = "expiration"
    CUSTOM = "custom"


class ExpectedMove(BaseModel):
    """Expected price move based on implied volatility."""

    symbol: str
    underlying_price: float
    iv: float
    timeframe: str
    days: float
    expected_move: float  # 1 standard deviation move
    move_percent: float  # As percentage of underlying


class SigmaBand(BaseModel):
    """A single sigma band with upper/lower bounds."""

    sigma: int  # 1, 2, or 3
    probability: float  # 0.68, 0.95, 0.997
    lower: float
    upper: float


class SigmaBands(BaseModel):
    """Sigma bands around current price."""

    symbol: str
    underlying_price: float
    timeframe: str
    one_sigma: SigmaBand
    two_sigma: SigmaBand
    three_sigma: SigmaBand


# Probability for each sigma level (from normal distribution)
SIGMA_PROBABILITIES = {
    1: 0.6827,  # 68.27%
    2: 0.9545,  # 95.45%
    3: 0.9973,  # 99.73%
}


def calculate_sigma_bands(expected_move: ExpectedMove) -> SigmaBands:
    """Calculate 1σ, 2σ, and 3σ price bands around current price.

    Args:
        expected_move: Expected move data (contains 1σ move)

    Returns:
        Sigma bands with upper/lower bounds for each level.
    """
    price = expected_move.underlying_price
    move_1sigma = expected_move.expected_move

    bands = {}
    for sigma in [1, 2, 3]:
        move = move_1sigma * sigma
        bands[sigma] = SigmaBand(
            sigma=sigma,
            probability=SIGMA_PROBABILITIES[sigma],
            lower=price - move,
            upper=price + move,
        )

    return SigmaBands(
        symbol=expected_move.symbol,
        underlying_price=price,
        timeframe=expected_move.timeframe,
        one_sigma=bands[1],
        two_sigma=bands[2],
        three_sigma=bands[3],
    )


def calculate_days_to_expiration(expiration: str) -> float:
    """Calculate days to expiration from YYYYMMDD format.

    Args:
        expiration: Expiration date in YYYYMMDD format

    Returns:
        Days to expiration (can be fractional)
    """
    exp_date = datetime.strptime(expiration, "%Y%m%d")
    now = datetime.now()
    delta = exp_date - now
    # Include fractional days
    return max(delta.total_seconds() / 86400, 0)


def calculate_expected_move(
    extracted_iv: ExtractedIV,
    timeframe: Timeframe = Timeframe.EXPIRATION,
    custom_days: float | None = None,
) -> ExpectedMove:
    """Calculate expected price move from implied volatility.

    Uses the formula: ExpectedMove = Price × IV × √(DTE/365)

    Args:
        extracted_iv: Extracted IV data from options chain
        timeframe: Timeframe for calculation (daily, weekly, expiration, custom)
        custom_days: Number of days for custom timeframe

    Returns:
        Expected move data for 1 standard deviation.
    """
    # Determine days based on timeframe
    if timeframe == Timeframe.DAILY:
        days = 1.0
        tf_name = "1 day"
    elif timeframe == Timeframe.WEEKLY:
        days = 7.0
        tf_name = "1 week"
    elif timeframe == Timeframe.EXPIRATION:
        days = calculate_days_to_expiration(extracted_iv.expiration)
        tf_name = f"{days:.1f} days (to exp)"
    elif timeframe == Timeframe.CUSTOM:
        if custom_days is None:
            raise ValueError("custom_days required for CUSTOM timeframe")
        days = custom_days
        tf_name = f"{days:.1f} days"
    else:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    # Expected move formula: Price × IV × √(DTE/365)
    price = extracted_iv.underlying_price
    iv = extracted_iv.atm_iv
    expected_move = price * iv * math.sqrt(days / 365)
    move_percent = (expected_move / price) * 100

    return ExpectedMove(
        symbol=extracted_iv.symbol,
        underlying_price=price,
        iv=iv,
        timeframe=tf_name,
        days=days,
        expected_move=expected_move,
        move_percent=move_percent,
    )


async def get_underlying_price(ib, contract: Contract) -> float:
    """Get current price for a contract."""
    ticker = ib.reqMktData(contract, "", False, False)
    await asyncio.sleep(2)  # Wait for data
    ib.cancelMktData(contract)

    # Try last, then mid, then close
    if ticker.last and ticker.last > 0:
        return ticker.last
    if ticker.bid and ticker.ask:
        return (ticker.bid + ticker.ask) / 2
    if ticker.close and ticker.close > 0:
        return ticker.close
    raise ValueError(f"Could not get price for {contract.symbol}")


async def fetch_options_chain(
    symbol: str,
    exchange: str | None = None,
    num_strikes: int = 5,
) -> OptionsChainResult:
    """Fetch ATM options chain for a futures contract.

    Args:
        symbol: Futures symbol (e.g., ES, NQ, CL)
        exchange: Exchange name (auto-detected if not provided)
        num_strikes: Number of strikes above/below ATM to include

    Returns:
        Options chain result with ATM options.
    """
    if exchange is None:
        exchange = FUTURES_EXCHANGES.get(symbol)
        if exchange is None:
            raise ValueError(
                f"Unknown symbol: {symbol}. Provide --exchange or use: "
                f"{', '.join(FUTURES_EXCHANGES.keys())}"
            )

    contract = Future(symbol=symbol, exchange=exchange)

    async with connect() as ib:
        # Get contract details to find front month
        details = await ib.reqContractDetailsAsync(contract)
        if not details:
            raise ValueError(f"Could not find contract: {symbol} on {exchange}")

        # Sort by expiration and pick front month
        details.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
        fut_contract = details[0].contract

        # Get current underlying price
        underlying_price = await get_underlying_price(ib, fut_contract)

        # Get option chain parameters
        chains = await ib.reqSecDefOptParamsAsync(
            underlyingSymbol=fut_contract.symbol,
            futFopExchange=fut_contract.exchange,
            underlyingSecType="FUT",
            underlyingConId=fut_contract.conId,
        )

        if not chains:
            raise ValueError(f"No options chain found for {symbol}")

        # Use the first chain (usually the main exchange)
        chain = chains[0]

        # Find ATM strike
        strikes = sorted(chain.strikes)
        atm_strike = min(strikes, key=lambda s: abs(s - underlying_price))
        atm_idx = strikes.index(atm_strike)

        # Get strikes around ATM
        start_idx = max(0, atm_idx - num_strikes)
        end_idx = min(len(strikes), atm_idx + num_strikes + 1)
        selected_strikes = strikes[start_idx:end_idx]

        # Get nearest expiration
        expirations = sorted(chain.expirations)
        if not expirations:
            raise ValueError(f"No expirations found for {symbol} options")
        nearest_exp = expirations[0]

        # Build option contracts for ATM call and put
        options: list[ATMOption] = []
        option_contracts: list[FuturesOption] = []

        for strike in selected_strikes:
            for right in ["C", "P"]:
                opt = FuturesOption(
                    symbol=symbol,
                    lastTradeDateOrContractMonth=nearest_exp,
                    strike=strike,
                    right=right,
                    exchange=chain.exchange,
                    multiplier=chain.multiplier,
                    tradingClass=chain.tradingClass,
                )
                option_contracts.append(opt)
                options.append(
                    ATMOption(
                        symbol=symbol,
                        expiration=nearest_exp,
                        strike=strike,
                        right=right,
                        underlying_price=underlying_price,
                    )
                )

        # Qualify option contracts
        qualified_opts = await ib.qualifyContractsAsync(*option_contracts)

        # Request market data for qualified options
        tickers = []
        for opt in qualified_opts:
            if opt.conId:  # Only request if contract was qualified
                ticker = ib.reqMktData(opt, "", False, False)
                tickers.append((opt, ticker))

        # Wait for data
        await asyncio.sleep(3)

        # Update options with market data
        for opt_contract, ticker in tickers:
            # Find matching option in our list
            for opt in options:
                if (
                    opt.strike == opt_contract.strike
                    and opt.right == opt_contract.right
                    and opt.expiration == opt_contract.lastTradeDateOrContractMonth
                ):
                    opt.bid = ticker.bid if ticker.bid > 0 else None
                    opt.ask = ticker.ask if ticker.ask > 0 else None
                    opt.last = ticker.last if ticker.last > 0 else None
                    if ticker.modelGreeks:
                        opt.model_iv = ticker.modelGreeks.impliedVol
                    break

        # Cancel market data
        for opt_contract, _ in tickers:
            ib.cancelMktData(opt_contract)

        return OptionsChainResult(
            symbol=symbol,
            exchange=exchange,
            underlying_price=underlying_price,
            atm_strike=atm_strike,
            options=options,
        )


@app.command()
def chain(
    symbol: Annotated[str, typer.Argument(help="Futures symbol (e.g., ES, NQ, CL)")],
    exchange: Annotated[
        str | None, typer.Option("--exchange", "-e", help="Exchange (auto-detected)")
    ] = None,
    strikes: Annotated[
        int, typer.Option("--strikes", "-s", help="Number of strikes around ATM")
    ] = 3,
) -> None:
    """Fetch and display ATM options chain for a futures contract."""
    typer.echo(f"Fetching options chain for {symbol}...")

    try:
        result = asyncio.run(fetch_options_chain(symbol, exchange, strikes))
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(f"\n{result.symbol} @ {result.underlying_price:.2f}")
    typer.echo(f"ATM Strike: {result.atm_strike}")
    typer.echo(
        f"Expiration: {result.options[0].expiration if result.options else 'N/A'}"
    )
    typer.echo("-" * 60)
    typer.echo(f"{'Strike':>10} {'Type':>6} {'Bid':>10} {'Ask':>10} {'IV':>10}")
    typer.echo("-" * 60)

    for opt in sorted(result.options, key=lambda o: (o.strike, o.right)):
        bid = f"{opt.bid:.2f}" if opt.bid else "-"
        ask = f"{opt.ask:.2f}" if opt.ask else "-"
        iv = f"{opt.model_iv:.1%}" if opt.model_iv else "-"
        right = "Call" if opt.right == "C" else "Put"
        atm_marker = " *" if opt.strike == result.atm_strike else ""
        typer.echo(
            f"{opt.strike:>10.2f} {right:>6} {bid:>10} {ask:>10} {iv:>10}{atm_marker}"
        )


@app.command()
def iv(
    symbol: Annotated[str, typer.Argument(help="Futures symbol (e.g., ES, NQ, CL)")],
    exchange: Annotated[
        str | None, typer.Option("--exchange", "-e", help="Exchange (auto-detected)")
    ] = None,
) -> None:
    """Extract and display ATM implied volatility for a futures contract."""
    typer.echo(f"Fetching IV for {symbol}...")

    try:
        chain_result = asyncio.run(fetch_options_chain(symbol, exchange, num_strikes=1))
        extracted = extract_iv(chain_result)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(f"\n{extracted.symbol} ATM Implied Volatility")
    typer.echo("-" * 40)
    typer.echo(f"Underlying:    {extracted.underlying_price:.2f}")
    typer.echo(f"ATM Strike:    {extracted.atm_strike:.2f}")
    typer.echo(f"Expiration:    {extracted.expiration}")
    typer.echo("-" * 40)
    typer.echo(f"ATM IV:        {extracted.atm_iv:.2%}")
    if extracted.call_iv:
        typer.echo(f"  Call IV:     {extracted.call_iv:.2%}")
    if extracted.put_iv:
        typer.echo(f"  Put IV:      {extracted.put_iv:.2%}")
    typer.echo(f"Source:        {extracted.iv_source}")


@app.command()
def move(
    symbol: Annotated[str, typer.Argument(help="Futures symbol (e.g., ES, NQ, CL)")],
    exchange: Annotated[
        str | None, typer.Option("--exchange", "-e", help="Exchange (auto-detected)")
    ] = None,
    timeframe: Annotated[
        str,
        typer.Option(
            "--timeframe", "-t", help="Timeframe: daily, weekly, expiration, or number"
        ),
    ] = "expiration",
) -> None:
    """Calculate expected move based on ATM implied volatility."""
    typer.echo(f"Calculating expected move for {symbol}...")

    try:
        chain_result = asyncio.run(fetch_options_chain(symbol, exchange, num_strikes=1))
        extracted = extract_iv(chain_result)

        # Parse timeframe
        if timeframe == "daily":
            tf = Timeframe.DAILY
            custom = None
        elif timeframe == "weekly":
            tf = Timeframe.WEEKLY
            custom = None
        elif timeframe == "expiration":
            tf = Timeframe.EXPIRATION
            custom = None
        else:
            # Try to parse as number of days
            try:
                custom = float(timeframe)
                tf = Timeframe.CUSTOM
            except ValueError:
                typer.echo(
                    f"Invalid timeframe: {timeframe}. "
                    "Use daily, weekly, expiration, or a number.",
                    err=True,
                )
                raise typer.Exit(1) from None

        result = calculate_expected_move(extracted, tf, custom)
        bands = calculate_sigma_bands(result)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    typer.echo(f"\n{result.symbol} Expected Move & Sigma Bands")
    typer.echo("-" * 50)
    typer.echo(f"Underlying:    {result.underlying_price:.2f}")
    typer.echo(f"IV:            {result.iv:.2%}")
    typer.echo(f"Timeframe:     {result.timeframe}")
    typer.echo("-" * 50)

    # Display sigma bands
    typer.echo(f"{'Band':<8} {'Prob':>8} {'Lower':>12} {'Upper':>12}")
    typer.echo("-" * 50)
    for band in [bands.one_sigma, bands.two_sigma, bands.three_sigma]:
        typer.echo(
            f"{band.sigma}σ{' ' * 5} {band.probability:>7.1%} "
            f"{band.lower:>12.2f} {band.upper:>12.2f}"
        )


@app.command()
def analyze(
    symbol: Annotated[str, typer.Argument(help="Futures symbol (e.g., ES, NQ, CL)")],
    exchange: Annotated[
        str | None, typer.Option("--exchange", "-e", help="Exchange (auto-detected)")
    ] = None,
) -> None:
    """Full analysis: IV, expected moves, and sigma bands for multiple timeframes."""
    typer.echo(f"Analyzing {symbol}...")

    try:
        chain_result = asyncio.run(fetch_options_chain(symbol, exchange, num_strikes=1))
        extracted = extract_iv(chain_result)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    # Header
    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"  {extracted.symbol} Options Stdev Analysis")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"  Underlying:  {extracted.underlying_price:.2f}")
    typer.echo(f"  ATM Strike:  {extracted.atm_strike:.2f}")
    typer.echo(f"  ATM IV:      {extracted.atm_iv:.2%}")
    typer.echo(f"  Expiration:  {extracted.expiration}")
    typer.echo(f"{'=' * 60}\n")

    # Calculate for multiple timeframes
    timeframes = [
        (Timeframe.DAILY, None, "Daily"),
        (Timeframe.WEEKLY, None, "Weekly"),
        (Timeframe.EXPIRATION, None, "To Expiration"),
    ]

    for tf, custom, label in timeframes:
        move = calculate_expected_move(extracted, tf, custom)
        bands = calculate_sigma_bands(move)

        typer.echo(f"  {label} ({move.timeframe})")
        typer.echo(f"  {'-' * 56}")
        typer.echo(f"  {'Band':<6} {'Probability':>12} {'Lower':>14} {'Upper':>14}")
        typer.echo(f"  {'-' * 56}")
        for band in [bands.one_sigma, bands.two_sigma, bands.three_sigma]:
            typer.echo(
                f"  {band.sigma}σ{' ' * 4} {band.probability:>11.1%} "
                f"{band.lower:>14.2f} {band.upper:>14.2f}"
            )
        typer.echo()


async def fetch_spx_0dte_iv() -> tuple[float, float, float, str]:
    """Fetch SPX 0DTE options and extract ATM IV.

    Returns:
        Tuple of (spx_price, atm_strike, atm_iv, expiration)
    """
    spx = Index(symbol="SPX", exchange="CBOE")

    async with connect() as ib:
        # Qualify the index
        qualified = await ib.qualifyContractsAsync(spx)
        if not qualified:
            raise ValueError("Could not find SPX index")
        spx = qualified[0]

        # Get current SPX price
        ticker = ib.reqMktData(spx, "", False, False)
        await asyncio.sleep(2)
        ib.cancelMktData(spx)

        if ticker.last and ticker.last > 0:
            spx_price = ticker.last
        elif ticker.close and ticker.close > 0:
            spx_price = ticker.close
        else:
            raise ValueError("Could not get SPX price")

        # Get option chain parameters
        chains = await ib.reqSecDefOptParamsAsync(
            underlyingSymbol="SPX",
            futFopExchange="",
            underlyingSecType="IND",
            underlyingConId=spx.conId,
        )

        if not chains:
            raise ValueError("No SPX options chain found")

        # Find SMART or CBOE chain
        chain = None
        for c in chains:
            if c.exchange in ("SMART", "CBOE"):
                chain = c
                break
        if chain is None:
            chain = chains[0]

        # Find today's expiration (0DTE)
        today = datetime.now().strftime("%Y%m%d")
        expirations = sorted(chain.expirations)

        # Find closest expiration (today or next available)
        dte_exp = None
        for exp in expirations:
            if exp >= today:
                dte_exp = exp
                break

        if dte_exp is None:
            raise ValueError("No 0DTE or near-term SPX expiration found")

        # Find ATM strike
        strikes = sorted(chain.strikes)
        atm_strike = min(strikes, key=lambda s: abs(s - spx_price))

        # Build ATM call and put options (SPXW = weekly/0DTE options)
        options = []
        for right in ["C", "P"]:
            opt = Option(
                symbol="SPX",
                lastTradeDateOrContractMonth=dte_exp,
                strike=atm_strike,
                right=right,
                exchange="SMART",
                tradingClass="SPXW",
            )
            options.append(opt)

        # Qualify and get market data
        qualified_opts = await ib.qualifyContractsAsync(*options)

        tickers = []
        for opt in qualified_opts:
            if opt.conId:
                t = ib.reqMktData(opt, "", False, False)
                tickers.append((opt, t))

        await asyncio.sleep(3)

        # Extract IVs
        ivs = []
        for opt, t in tickers:
            if t.modelGreeks and t.modelGreeks.impliedVol:
                ivs.append(t.modelGreeks.impliedVol)
            ib.cancelMktData(opt)

        if not ivs:
            raise ValueError("Could not get IV from SPX 0DTE options")

        atm_iv = sum(ivs) / len(ivs)

        return spx_price, atm_strike, atm_iv, dte_exp


@app.command()
def spx0dte(
    fair_value: Annotated[
        float,
        typer.Option("--fv", "-f", help="ES-SPX fair value offset (ES = SPX + FV)"),
    ] = 10.0,
) -> None:
    """Calculate ES daily expected move using SPX 0DTE options IV."""
    typer.echo("Fetching SPX 0DTE options...")

    try:
        spx_price, atm_strike, atm_iv, expiration = asyncio.run(fetch_spx_0dte_iv())
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    # Convert to ES equivalent
    es_price = spx_price + fair_value

    # Calculate daily expected move (1 day)
    daily_move = es_price * atm_iv * math.sqrt(1 / 365)

    typer.echo("\nSPX 0DTE → ES Expected Move")
    typer.echo("=" * 50)
    typer.echo(f"  SPX Price:     {spx_price:.2f}")
    typer.echo(f"  SPX ATM:       {atm_strike:.0f}")
    typer.echo(f"  SPX 0DTE IV:   {atm_iv:.2%}")
    typer.echo(f"  Expiration:    {expiration}")
    typer.echo(f"  Fair Value:    {fair_value:+.1f}")
    typer.echo("=" * 50)
    typer.echo(f"  ES Equivalent: {es_price:.2f}")
    typer.echo("-" * 50)
    typer.echo(f"  {'Band':<6} {'Probability':>12} {'Lower':>12} {'Upper':>12}")
    typer.echo("-" * 50)

    for sigma, prob in [(1, 0.6827), (2, 0.9545), (3, 0.9973)]:
        move = daily_move * sigma
        lower = es_price - move
        upper = es_price + move
        typer.echo(f"  {sigma}σ{' ' * 4} {prob:>11.1%} {lower:>12.2f} {upper:>12.2f}")
