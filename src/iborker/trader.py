"""Click Trader GUI - Simple single-instrument trading interface."""

import asyncio
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import dearpygui.dearpygui as dpg
from ib_insync import IB, Contract, Future, MarketOrder, Position, Ticker

from iborker import __version__
from iborker.client_id import get_client_id, release_client_id
from iborker.config import settings
from iborker.contracts import FUTURES_DATABASE, resolve_symbol
from iborker.roll import RollState, get_roll_status


@dataclass
class TraderState:
    """Current state of the trader."""

    contract: Contract | None = None
    position: int = 0
    avg_cost: float = 0.0
    unrealized_pnl: float = 0.0
    quantity: int = 1
    connected: bool = False

    # Account
    account: str = ""
    accounts: list[str] | None = None

    # Market data
    bid: float = 0.0
    ask: float = 0.0
    last_price: float = 0.0
    prev_last_price: float = 0.0
    tick_direction: str = ""  # "up", "down", or ""

    # P&L tracking
    multiplier: float = 1.0
    pnl_mode: str = "points"  # "points" or "dollars"
    daily_realized_points: float = 0.0
    last_trade_date: str = ""

    # Keyboard state
    highlighted_action: str | None = None  # "buy", "sell", "flatten", "reverse"

    # Roll detection
    roll_check_enabled: bool = True
    roll_warning: str = ""  # Warning message if contract is rolling


class ClickTrader:
    """Single-instrument click trader with DearPyGui interface."""

    def __init__(self) -> None:
        self.state = TraderState()
        self.ib: IB | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        # Theme references (set in create_ui)
        self._buy_theme: int = 0
        self._sell_theme: int = 0
        self._highlight_theme: int = 0

    def _run_async(self, coro: Callable) -> None:
        """Run coroutine in the background event loop (fire and forget)."""
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _run_async_wait(self, coro: Callable, timeout: float = 5.0) -> None:
        """Run coroutine and wait for completion."""
        if self._loop is not None and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            try:
                future.result(timeout=timeout)
            except Exception:
                pass  # Ignore errors during cleanup

    def _start_event_loop(self) -> None:
        """Start asyncio event loop in background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _stop_event_loop(self) -> None:
        """Stop the background event loop."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=2.0)
            self._loop = None

    async def connect(self) -> None:
        """Connect to IB."""
        self.ib = IB()
        client_id = get_client_id("trader")
        try:
            await self.ib.connectAsync(
                host=settings.host,
                port=settings.port,
                clientId=client_id,
                timeout=settings.timeout,
                readonly=settings.readonly,
            )
            self.state.connected = True
            self._update_status(f"Connected (client {client_id})")
            if dpg.does_item_exist("connect_btn"):
                dpg.configure_item("connect_btn", label="Disconnect")

            # Get available accounts and populate dropdown
            self.state.accounts = self.ib.managedAccounts()
            if self.state.accounts:
                self._populate_account_dropdown()  # This sorts and sets default

            # Subscribe to position updates
            self.ib.positionEvent += self._on_position
            self.ib.pnlSingleEvent += self._on_pnl

            # Auto-set contract from symbol input
            if dpg.does_item_exist("symbol_input"):
                symbol = dpg.get_value("symbol_input")
                exchange = dpg.get_value("exchange_input")
                if symbol:
                    await self.set_contract(symbol, exchange)

        except Exception as e:
            release_client_id("trader")
            self.ib = None  # Clean up failed connection
            self._update_status(f"Connection failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from IB."""
        if self.ib is not None:
            self.ib.disconnect()
            self.ib = None  # Prevent destructor from running after event loop closes
            release_client_id("trader")
            self.state.connected = False
            self._update_status("Disconnected")
            if dpg.does_item_exist("connect_btn"):
                dpg.configure_item("connect_btn", label="Connect")

    async def _resolve_contract(self, symbol: str, exchange: str) -> Contract | None:
        """Resolve symbol to a specific contract.

        If symbol is ambiguous (e.g., 'ES'), selects the front month.
        If symbol is specific (e.g., 'ESH6'), uses that contract.
        """
        symbol = symbol.upper().strip()

        # Try as a specific local symbol first (e.g., ESH6)
        contract = Future(localSymbol=symbol, exchange=exchange)
        qualified = await self.ib.qualifyContractsAsync(contract)
        if len(qualified) == 1:
            return qualified[0]

        # Try as base symbol - will return multiple contracts
        contract = Future(symbol=symbol, exchange=exchange)
        details = await self.ib.reqContractDetailsAsync(contract)

        if not details:
            self._update_status(f"Contract not found: {symbol}")
            return None

        # Filter to quarterly months (H=Mar, M=Jun, U=Sep, Z=Dec) and sort by expiry
        quarterly_codes = {"H", "M", "U", "Z"}
        today = date.today().strftime("%Y%m%d")

        quarterly_contracts = []
        for d in details:
            local = d.contract.localSymbol
            # Month code is second-to-last character (e.g., ESH6 -> H)
            if len(local) >= 2:
                month_code = local[-2]
                if month_code in quarterly_codes:
                    expiry = d.contract.lastTradeDateOrContractMonth
                    if expiry >= today:
                        quarterly_contracts.append((expiry, d.contract))

        if not quarterly_contracts:
            # Fallback: use nearest of any available contract
            all_contracts = [
                (d.contract.lastTradeDateOrContractMonth, d.contract)
                for d in details
                if d.contract.lastTradeDateOrContractMonth >= today
            ]
            if all_contracts:
                all_contracts.sort(key=lambda x: x[0])
                return all_contracts[0][1]
            self._update_status(f"No active contracts for: {symbol}")
            return None

        # Sort by expiry and return the front month
        quarterly_contracts.sort(key=lambda x: x[0])
        front_month = quarterly_contracts[0][1]
        self._update_status(f"Using front month: {front_month.localSymbol}")
        return front_month

    async def set_contract(self, symbol: str, exchange: str = "CME") -> None:
        """Set the trading contract.

        Accepts:
        - Base symbol (ES, NQ, etc.) - auto-selects based on roll status
        - Full local symbol (ESH6, NQM6, etc.) - uses specific contract
        """
        if self.ib is None or not self.state.connected:
            self._update_status("Not connected")
            return

        # Clear previous roll warning
        self.state.roll_warning = ""

        # Resolve symbol alias (6E -> EUR, etc.)
        resolved_symbol = resolve_symbol(symbol.upper())

        # Check roll status if enabled and symbol is in database
        if self.state.roll_check_enabled and resolved_symbol in FUTURES_DATABASE:
            self._update_status(f"Checking roll status for {resolved_symbol}...")
            try:
                roll_status = await get_roll_status(self.ib, resolved_symbol)

                if roll_status.state == RollState.ROLLING:
                    # Use the recommended contract based on OI ratio
                    if roll_status.ratio >= 0.5 and roll_status.back_contract:
                        selected_contract = roll_status.back_contract
                        local = selected_contract.localSymbol
                        self.state.roll_warning = (
                            f"ROLLING ({roll_status.ratio:.0%}) -> {local}"
                        )
                    else:
                        selected_contract = roll_status.front_contract
                        self.state.roll_warning = f"ROLLING ({roll_status.ratio:.0%})"
                elif roll_status.state == RollState.POST_ROLL:
                    selected_contract = roll_status.back_contract
                    self.state.roll_warning = ""
                else:
                    # Pre-roll or unknown - use front month
                    selected_contract = roll_status.front_contract
            except Exception as e:
                # Fall back to regular resolution on error
                self._update_status(f"Roll check failed: {e}")
                selected_contract = await self._resolve_contract(symbol, exchange)
        else:
            # Roll check disabled or symbol not in database
            selected_contract = await self._resolve_contract(symbol, exchange)

        if selected_contract:
            self.state.contract = selected_contract
            status_msg = f"Contract: {self.state.contract.localSymbol}"
            if self.state.roll_warning:
                status_msg += f" [{self.state.roll_warning}]"
            self._update_status(status_msg)

            # Get multiplier from database (use resolved contract's base symbol)
            base_symbol = self.state.contract.symbol.upper()
            if base_symbol in FUTURES_DATABASE:
                self.state.multiplier = FUTURES_DATABASE[base_symbol][2]
            elif self.state.contract.multiplier:
                self.state.multiplier = float(self.state.contract.multiplier)

            # Reset daily P&L on contract change
            self.state.daily_realized_points = 0.0
            self.state.last_trade_date = str(date.today())

            # Subscribe to market data with tick handler
            self.ib.pendingTickersEvent += self._on_tick
            self.ib.reqMktData(self.state.contract)

            # Request PnL updates for selected account
            self.ib.reqPnLSingle(
                account=self.state.account,
                modelCode="",
                conId=self.state.contract.conId,
            )
        else:
            self._update_status(f"Contract not found: {symbol}")

    async def place_order(self, action: str, quantity: int) -> None:
        """Place a market order."""
        if self.ib is None or self.state.contract is None:
            self._update_status("No contract selected")
            return

        # Capture pre-trade state for realized P&L calculation
        prev_position = self.state.position
        prev_avg_cost = self.state.avg_cost

        order = MarketOrder(action=action, totalQuantity=quantity)
        order.account = self.state.account
        trade = self.ib.placeOrder(self.state.contract, order)
        self._update_status(f"Order placed: {action} {quantity}")

        # Wait for fill
        while not trade.isDone():
            await asyncio.sleep(0.1)

        if trade.orderStatus.status == "Filled":
            fill_price = trade.orderStatus.avgFillPrice
            self._update_status(f"Filled: {action} {quantity} @ {fill_price}")

            # Calculate realized P&L (per-contract) for closed portion
            self._calculate_realized_pnl(
                prev_position, prev_avg_cost, action, quantity, fill_price
            )
        else:
            self._update_status(f"Order status: {trade.orderStatus.status}")

    async def buy(self) -> None:
        """Buy at market."""
        await self.place_order("BUY", self.state.quantity)

    async def sell(self) -> None:
        """Sell at market."""
        await self.place_order("SELL", self.state.quantity)

    async def reverse(self) -> None:
        """Reverse position (close + open opposite)."""
        if self.state.position == 0:
            self._update_status("No position to reverse")
            return

        # Close current + open opposite
        qty = abs(self.state.position) + self.state.quantity
        action = "BUY" if self.state.position < 0 else "SELL"
        await self.place_order(action, qty)

    async def flatten(self) -> None:
        """Close all positions."""
        if self.state.position == 0:
            self._update_status("No position to flatten")
            return

        action = "SELL" if self.state.position > 0 else "BUY"
        await self.place_order(action, abs(self.state.position))

    def _on_position(self, position: Position) -> None:
        """Handle position update."""
        # Filter by account and contract
        if position.account != self.state.account:
            return
        if not self.state.contract:
            return
        if position.contract.conId != self.state.contract.conId:
            return

        self.state.position = int(position.position)
        # IB returns avgCost as price * multiplier for futures, normalize it
        if self.state.multiplier > 0:
            self.state.avg_cost = position.avgCost / self.state.multiplier
        else:
            self.state.avg_cost = position.avgCost
        self._update_display()

    def _on_pnl(self, pnl) -> None:
        """Handle PnL update."""
        self.state.unrealized_pnl = pnl.unrealizedPnL or 0.0
        self._update_display()

    def _calculate_realized_pnl(
        self,
        prev_position: int,
        prev_avg_cost: float,
        action: str,
        quantity: int,
        fill_price: float,
    ) -> None:
        """Calculate and accumulate realized P&L (per-contract) for closed portion."""
        if prev_position == 0:
            # Opening new position, no realized P&L
            return

        # Calculate per-contract realized P&L for closed portion
        if prev_position > 0 and action == "SELL":
            # Closing long: realized = exit - entry
            realized_points = fill_price - prev_avg_cost
            self.state.daily_realized_points += realized_points
        elif prev_position < 0 and action == "BUY":
            # Closing short: realized = entry - exit
            realized_points = prev_avg_cost - fill_price
            self.state.daily_realized_points += realized_points

    def _on_tick(self, tickers: set[Ticker]) -> None:
        """Handle tick updates for market data."""
        for ticker in tickers:
            if not self.state.contract:
                continue
            if ticker.contract.conId != self.state.contract.conId:
                continue

            # Update bid/ask
            if ticker.bid is not None:
                self.state.bid = ticker.bid
            if ticker.ask is not None:
                self.state.ask = ticker.ask

            # Update last price and track direction
            if ticker.last is not None and ticker.last > 0:
                self.state.prev_last_price = self.state.last_price
                self.state.last_price = ticker.last

                if self.state.prev_last_price > 0:
                    if ticker.last > self.state.prev_last_price:
                        self.state.tick_direction = "up"
                    elif ticker.last < self.state.prev_last_price:
                        self.state.tick_direction = "down"

            self._update_display()

    def _update_status(self, message: str) -> None:
        """Update status bar."""
        if dpg.does_item_exist("status_text"):
            dpg.set_value("status_text", message)

    def _update_display(self) -> None:
        """Update position, price, and PnL display."""
        # Position display
        if dpg.does_item_exist("position_text"):
            pos_str = f"{self.state.position:+d}" if self.state.position else "FLAT"
            dpg.set_value("position_text", pos_str)

        # Market price display (bid if long, ask if short, last if flat)
        if dpg.does_item_exist("market_price_text"):
            if self.state.position > 0:
                price = self.state.bid
                label = "Bid"
            elif self.state.position < 0:
                price = self.state.ask
                label = "Ask"
            else:
                price = self.state.last_price
                label = "Last"

            price_str = f"{price:.2f}" if price > 0 else "---"
            dpg.set_value("market_price_text", f"{label}: {price_str}")

        # Tick direction indicator (ASCII for font compatibility)
        if dpg.does_item_exist("tick_indicator"):
            if self.state.tick_direction == "up":
                dpg.set_value("tick_indicator", "^")
                dpg.configure_item("tick_indicator", color=(0, 255, 0))
            elif self.state.tick_direction == "down":
                dpg.set_value("tick_indicator", "v")
                dpg.configure_item("tick_indicator", color=(255, 0, 0))
            else:
                dpg.set_value("tick_indicator", " ")

        # P&L display
        self._update_pnl_display()

    def _update_pnl_display(self) -> None:
        """Update P&L values based on current mode."""
        if not dpg.does_item_exist("pnl_unrealized"):
            return

        # Calculate unrealized P&L in points
        unrealized_points = 0.0
        if self.state.position != 0 and self.state.last_price > 0:
            if self.state.position > 0:
                unrealized_points = self.state.last_price - self.state.avg_cost
            else:
                unrealized_points = self.state.avg_cost - self.state.last_price

        # Cumulative = daily realized + current unrealized
        cumulative_points = self.state.daily_realized_points + unrealized_points

        if self.state.pnl_mode == "points":
            unrealized_str = f"{unrealized_points:+.2f} pts"
            cumulative_str = f"{cumulative_points:+.2f} pts"
        else:
            # Dollar mode
            mult = self.state.multiplier
            unrealized_dollars = unrealized_points * mult * abs(self.state.position)
            cumulative_dollars = cumulative_points * mult
            unrealized_str = f"${unrealized_dollars:+,.2f}"
            cumulative_str = f"${cumulative_dollars:+,.2f}"

        dpg.set_value("pnl_unrealized", unrealized_str)
        dpg.set_value("pnl_cumulative", cumulative_str)

        # Color based on values
        pnl_items = [
            ("pnl_unrealized", unrealized_points),
            ("pnl_cumulative", cumulative_points),
        ]
        for tag, value in pnl_items:
            if dpg.does_item_exist(tag):
                if value > 0:
                    dpg.configure_item(tag, color=(0, 255, 0))
                elif value < 0:
                    dpg.configure_item(tag, color=(255, 0, 0))
                else:
                    dpg.configure_item(tag, color=(255, 255, 255))

    def _toggle_pnl_mode(self) -> None:
        """Toggle between points and dollars P&L display."""
        if self.state.pnl_mode == "points":
            self.state.pnl_mode = "dollars"
        else:
            self.state.pnl_mode = "points"
        self._update_pnl_display()

    def _on_quantity_change(self, sender, value) -> None:
        """Handle quantity input change."""
        self.state.quantity = max(1, int(value))

    def _on_connect_click(self) -> None:
        """Handle connect/disconnect button click."""
        if self.state.connected:
            self._run_async(self.disconnect())
        else:
            self._run_async(self.connect())

    def _get_account_display_name(self, account_id: str) -> str:
        """Get display name for account (nickname if configured, else ID)."""
        return settings.account_nicknames.get(account_id, account_id)

    def _get_account_id_from_display(self, display_name: str) -> str:
        """Map display name back to account ID."""
        # Check if display_name is a nickname
        for acct_id, nickname in settings.account_nicknames.items():
            if nickname == display_name:
                return acct_id
        # Otherwise it's the raw account ID
        return display_name

    def _populate_account_dropdown(self) -> None:
        """Populate account dropdown with available accounts.

        Order: accounts with nicknames first (in config order), then remaining.
        """
        if not dpg.does_item_exist("account_combo"):
            return
        if not self.state.accounts:
            return

        # Sort: nicknamed accounts in config order, then others
        nicknamed = [
            acct
            for acct in settings.account_nicknames.keys()
            if acct in self.state.accounts
        ]
        others = [acct for acct in self.state.accounts if acct not in nicknamed]
        sorted_accounts = nicknamed + others

        # Update state.accounts to use this order and set default
        self.state.accounts = sorted_accounts
        if sorted_accounts:
            # Set first sorted account as default if not already set
            if not self.state.account or self.state.account not in sorted_accounts:
                self.state.account = sorted_accounts[0]

        display_names = [
            self._get_account_display_name(acct) for acct in sorted_accounts
        ]
        dpg.configure_item("account_combo", items=display_names)
        dpg.set_value(
            "account_combo", self._get_account_display_name(self.state.account)
        )

    def _on_account_change(self, sender, app_data) -> None:
        """Handle account selection change."""
        # Map display name back to account ID
        self.state.account = self._get_account_id_from_display(app_data)
        # Reset position and P&L for new account
        self.state.position = 0
        self.state.avg_cost = 0.0
        self.state.daily_realized_points = 0.0
        self._update_display()
        self._update_status(f"Account: {app_data}")

    def _on_set_contract_click(self) -> None:
        """Handle set contract button click."""
        symbol = dpg.get_value("symbol_input")
        exchange = dpg.get_value("exchange_input")
        if symbol:
            self._run_async(self.set_contract(symbol, exchange))

    def _on_buy_click(self) -> None:
        """Handle buy button click."""
        self._run_async(self.buy())

    def _on_sell_click(self) -> None:
        """Handle sell button click."""
        self._run_async(self.sell())

    def _on_reverse_click(self) -> None:
        """Handle reverse button click."""
        self._run_async(self.reverse())

    def _on_flatten_click(self) -> None:
        """Handle flatten button click."""
        self._run_async(self.flatten())

    def _on_key_press(self, sender, app_data) -> None:
        """Handle keyboard shortcuts."""
        key_code = app_data  # DearPyGui passes key code in app_data

        # DearPyGui key constants
        key_q = dpg.mvKey_Q
        key_b = dpg.mvKey_B
        key_s = dpg.mvKey_S
        key_f = dpg.mvKey_F
        key_r = dpg.mvKey_R
        key_p = dpg.mvKey_P
        key_enter = dpg.mvKey_Return

        # Check for Ctrl modifier (left or right)
        ctrl_pressed = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(
            dpg.mvKey_RControl
        )

        if key_code == key_q:
            # Focus quantity input
            dpg.focus_item("quantity_input")
            return

        # Handle action shortcuts (B, S, F, R)
        action_map = {
            key_b: ("buy", "buy_btn"),
            key_s: ("sell", "sell_btn"),
            key_f: ("flatten", "flatten_btn"),
            key_r: ("reverse", "reverse_btn"),
        }

        if key_code in action_map:
            action, btn_tag = action_map[key_code]
            # Unfocus quantity input so keystroke doesn't go into it
            dpg.focus_item(btn_tag)
            self._highlight_action(action, btn_tag)
            return

        # P toggles P&L mode
        if key_code == key_p:
            dpg.focus_item("main_window")  # Unfocus quantity input
            self._toggle_pnl_mode()
            return

        # Ctrl+Enter executes highlighted action
        if key_code == key_enter and ctrl_pressed:
            self._execute_highlighted_action()
            return

    def _highlight_action(self, action: str, btn_tag: str) -> None:
        """Highlight a button for pending execution."""
        # Clear previous highlight
        self._clear_highlight()

        # Set new highlight
        self.state.highlighted_action = action
        dpg.bind_item_theme(btn_tag, self._highlight_theme)

    def _clear_highlight(self) -> None:
        """Clear button highlight and restore original themes."""
        if self.state.highlighted_action:
            # Restore original themes
            if self.state.highlighted_action == "buy":
                dpg.bind_item_theme("buy_btn", self._buy_theme)
            elif self.state.highlighted_action == "sell":
                dpg.bind_item_theme("sell_btn", self._sell_theme)
            elif self.state.highlighted_action == "flatten":
                dpg.bind_item_theme("flatten_btn", 0)  # Default theme
            elif self.state.highlighted_action == "reverse":
                dpg.bind_item_theme("reverse_btn", 0)  # Default theme

            self.state.highlighted_action = None

    def _execute_highlighted_action(self) -> None:
        """Execute the currently highlighted action."""
        action = self.state.highlighted_action
        if not action:
            return

        # Clear highlight BEFORE executing to prevent double-execution
        # if user accidentally taps Ctrl+Enter multiple times
        self._clear_highlight()

        if action == "buy":
            self._on_buy_click()
        elif action == "sell":
            self._on_sell_click()
        elif action == "flatten":
            self._on_flatten_click()
        elif action == "reverse":
            self._on_reverse_click()

    def create_ui(self) -> None:
        """Create the DearPyGui interface."""
        dpg.create_context()

        with dpg.window(tag="main_window"):
            # Connection section
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Connect",
                    tag="connect_btn",
                    callback=self._on_connect_click,
                    width=100,
                )
                dpg.add_text("Disconnected", tag="status_text")

            # Account selection (populated after connect)
            with dpg.group(horizontal=True):
                dpg.add_text("Account:")
                dpg.add_combo(
                    tag="account_combo",
                    items=[],
                    default_value="",
                    callback=self._on_account_change,
                    width=150,
                )

            dpg.add_separator()

            # Contract selection
            with dpg.group(horizontal=True):
                dpg.add_input_text(
                    label="Symbol",
                    tag="symbol_input",
                    default_value="ES",
                    width=80,
                )
                dpg.add_input_text(
                    label="Exchange",
                    tag="exchange_input",
                    default_value="CME",
                    width=80,
                )
                dpg.add_button(
                    label="Go",
                    callback=self._on_set_contract_click,
                )

            dpg.add_separator()

            # Position display
            with dpg.group(horizontal=True):
                dpg.add_text("Position:")
                dpg.add_text("FLAT", tag="position_text")

            # P&L display (clickable to toggle mode)
            with dpg.group(horizontal=True):
                dpg.add_text("Unreal:")
                dpg.add_text("+0.00 pts", tag="pnl_unrealized")
                dpg.add_spacer(width=10)
                dpg.add_text("Daily:")
                dpg.add_text("+0.00 pts", tag="pnl_cumulative")
                dpg.add_spacer(width=10)
                dpg.add_button(
                    label="$/pts",
                    callback=lambda: self._toggle_pnl_mode(),
                    width=50,
                )

            dpg.add_separator()

            # Quantity input
            dpg.add_input_int(
                label="Quantity [Q]",
                tag="quantity_input",
                default_value=1,
                min_value=1,
                max_value=100,
                callback=self._on_quantity_change,
                width=100,
            )

            # Market price display with tick indicator
            with dpg.group(horizontal=True):
                dpg.add_text("Last: ---", tag="market_price_text")
                dpg.add_text(" ", tag="tick_indicator")

            dpg.add_spacer(height=10)

            # Order buttons with keyboard shortcuts
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="BUY [B]",
                    tag="buy_btn",
                    callback=self._on_buy_click,
                    width=100,
                    height=50,
                )
                dpg.add_button(
                    label="SELL [S]",
                    tag="sell_btn",
                    callback=self._on_sell_click,
                    width=100,
                    height=50,
                )

            dpg.add_spacer(height=10)

            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="REVERSE [R]",
                    tag="reverse_btn",
                    callback=self._on_reverse_click,
                    width=100,
                    height=40,
                )
                dpg.add_button(
                    label="FLATTEN [F]",
                    tag="flatten_btn",
                    callback=self._on_flatten_click,
                    width=100,
                    height=40,
                )

            # Shortcut hint
            dpg.add_text(
                "Shortcuts: Q=qty, B/S/F/R + Ctrl+Enter",
                color=(150, 150, 150),
            )

            # Version and author
            with dpg.group(horizontal=True):
                dpg.add_text(f"v{__version__} by", color=(100, 100, 100))
                dpg.add_button(
                    label="murdarch",
                    tag="author_link",
                    callback=lambda: webbrowser.open("https://x.com/murd_arch"),
                    small=True,
                )

        # Link theme (no background, looks like hyperlink)
        with dpg.theme(tag="_link_theme"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (100, 100, 100))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
        dpg.bind_item_theme("author_link", "_link_theme")

        # Themes for buttons
        with dpg.theme() as buy_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 100, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 150, 0))
        dpg.bind_item_theme("buy_btn", buy_theme)
        self._buy_theme = buy_theme

        with dpg.theme() as sell_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (150, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (200, 0, 0))
        dpg.bind_item_theme("sell_btn", sell_theme)
        self._sell_theme = sell_theme

        # Highlight theme for selected action
        with dpg.theme() as highlight_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (200, 200, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (255, 255, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 2)
        self._highlight_theme = highlight_theme

        # Register keyboard handler
        with dpg.handler_registry():
            dpg.add_key_press_handler(callback=self._on_key_press)

        dpg.create_viewport(title="iborker Click Trader", width=350, height=400)

        # Set window icons
        icon_dir = Path(__file__).parent
        icon_small = icon_dir / "icon-32.png"
        icon_large = icon_dir / "icon-64.png"
        if icon_small.exists():
            dpg.set_viewport_small_icon(str(icon_small))
        if icon_large.exists():
            dpg.set_viewport_large_icon(str(icon_large))

        dpg.setup_dearpygui()
        dpg.set_primary_window("main_window", True)

    def run(self) -> None:
        """Run the trader GUI."""
        # Start background event loop for async IB operations
        self._thread = threading.Thread(target=self._start_event_loop, daemon=True)
        self._thread.start()

        self.create_ui()
        dpg.show_viewport()

        try:
            dpg.start_dearpygui()
        finally:
            # Cleanup - disconnect if connected, then stop event loop
            if self.ib is not None:
                self._run_async_wait(self.disconnect())
            self._stop_event_loop()
            dpg.destroy_context()


def main(no_roll_check: bool = False) -> None:
    """Entry point for click trader.

    Args:
        no_roll_check: Disable automatic roll detection when selecting contracts.
    """
    trader = ClickTrader()
    if no_roll_check:
        trader.state.roll_check_enabled = False
    trader.run()


def cli() -> None:
    """CLI entry point with argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="iborker Click Trader - Simple futures trading GUI"
    )
    parser.add_argument(
        "--no-roll-check",
        action="store_true",
        help="Disable automatic roll detection (default: enabled)",
    )
    args = parser.parse_args()
    main(no_roll_check=args.no_roll_check)


if __name__ == "__main__":
    cli()
