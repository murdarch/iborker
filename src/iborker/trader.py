"""Click Trader GUI - Simple single-instrument trading interface."""

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import dearpygui.dearpygui as dpg
from ib_insync import IB, Contract, Future, MarketOrder, Position, Ticker

from iborker.client_id import get_client_id, release_client_id
from iborker.config import settings
from iborker.contracts import FUTURES_DATABASE


@dataclass
class TraderState:
    """Current state of the trader."""

    contract: Contract | None = None
    position: int = 0
    avg_cost: float = 0.0
    unrealized_pnl: float = 0.0
    quantity: int = 1
    connected: bool = False

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

            # Subscribe to position updates
            self.ib.positionEvent += self._on_position
            self.ib.pnlSingleEvent += self._on_pnl

        except Exception as e:
            release_client_id("trader")
            self._update_status(f"Connection failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from IB."""
        if self.ib is not None:
            self.ib.disconnect()
            release_client_id("trader")
            self.state.connected = False
            self._update_status("Disconnected")

    async def set_contract(self, symbol: str, exchange: str = "CME") -> None:
        """Set the trading contract."""
        if self.ib is None or not self.state.connected:
            self._update_status("Not connected")
            return

        contract = Future(symbol=symbol, exchange=exchange)
        qualified = await self.ib.qualifyContractsAsync(contract)

        if qualified:
            self.state.contract = qualified[0]
            self._update_status(f"Contract: {self.state.contract.localSymbol}")

            # Get multiplier from database
            symbol_upper = symbol.upper()
            if symbol_upper in FUTURES_DATABASE:
                self.state.multiplier = FUTURES_DATABASE[symbol_upper][2]
            elif self.state.contract.multiplier:
                self.state.multiplier = float(self.state.contract.multiplier)

            # Reset daily P&L on contract change
            self.state.daily_realized_points = 0.0
            self.state.last_trade_date = str(date.today())

            # Subscribe to market data with tick handler
            self.ib.pendingTickersEvent += self._on_tick
            self.ib.reqMktData(self.state.contract)

            # Request PnL updates
            self.ib.reqPnLSingle(
                account=self.ib.wrapper.accounts[0] if self.ib.wrapper.accounts else "",
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
        if self.state.contract and position.contract.conId == self.state.contract.conId:
            self.state.position = int(position.position)
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

        # Tick direction indicator
        if dpg.does_item_exist("tick_indicator"):
            if self.state.tick_direction == "up":
                dpg.set_value("tick_indicator", "▲")
                dpg.configure_item("tick_indicator", color=(0, 255, 0))
            elif self.state.tick_direction == "down":
                dpg.set_value("tick_indicator", "▼")
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
        """Handle connect button click."""
        self._run_async(self.connect())

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

    def _on_key_press(self, sender, key_code) -> None:
        """Handle keyboard shortcuts."""
        # Key codes for letters (DearPyGui uses ASCII-like codes)
        key_q = ord("Q")
        key_b = ord("B")
        key_s = ord("S")
        key_f = ord("F")
        key_r = ord("R")
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
            self._highlight_action(action, btn_tag)
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

        if action == "buy":
            self._on_buy_click()
        elif action == "sell":
            self._on_sell_click()
        elif action == "flatten":
            self._on_flatten_click()
        elif action == "reverse":
            self._on_reverse_click()

        self._clear_highlight()

    def create_ui(self) -> None:
        """Create the DearPyGui interface."""
        dpg.create_context()

        with dpg.window(tag="main_window"):
            # Connection section
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Connect", callback=self._on_connect_click, width=100
                )
                dpg.add_text("Disconnected", tag="status_text")

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
                    label="Set Contract",
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
            # Cleanup - wait for disconnect to complete before stopping loop
            if self.state.connected:
                self._run_async_wait(self.disconnect())
            self._stop_event_loop()
            dpg.destroy_context()


def main() -> None:
    """Entry point for click trader."""
    trader = ClickTrader()
    trader.run()


if __name__ == "__main__":
    main()
