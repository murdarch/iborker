"""Click Trader GUI - Simple single-instrument trading interface."""

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass

import dearpygui.dearpygui as dpg
from ib_insync import IB, Contract, Future, MarketOrder, Position

from iborker.client_id import get_client_id, release_client_id
from iborker.config import settings


@dataclass
class TraderState:
    """Current state of the trader."""

    contract: Contract | None = None
    position: int = 0
    avg_cost: float = 0.0
    unrealized_pnl: float = 0.0
    last_price: float = 0.0
    quantity: int = 1
    connected: bool = False


class ClickTrader:
    """Single-instrument click trader with DearPyGui interface."""

    def __init__(self) -> None:
        self.state = TraderState()
        self.ib: IB | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def _run_async(self, coro: Callable) -> None:
        """Run coroutine in the background event loop."""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(coro, self._loop)

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

            # Subscribe to market data
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

        order = MarketOrder(action=action, totalQuantity=quantity)
        trade = self.ib.placeOrder(self.state.contract, order)
        self._update_status(f"Order placed: {action} {quantity}")

        # Wait for fill
        while not trade.isDone():
            await asyncio.sleep(0.1)

        if trade.orderStatus.status == "Filled":
            price = trade.orderStatus.avgFillPrice
            self._update_status(f"Filled: {action} {quantity} @ {price}")
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

    def _update_status(self, message: str) -> None:
        """Update status bar."""
        if dpg.does_item_exist("status_text"):
            dpg.set_value("status_text", message)

    def _update_display(self) -> None:
        """Update position and PnL display."""
        if dpg.does_item_exist("position_text"):
            pos_str = f"{self.state.position:+d}" if self.state.position else "FLAT"
            dpg.set_value("position_text", pos_str)

        if dpg.does_item_exist("pnl_text"):
            pnl = self.state.unrealized_pnl
            dpg.set_value("pnl_text", f"${pnl:,.2f}")

            # Color based on P&L
            if pnl > 0:
                dpg.configure_item("pnl_text", color=(0, 255, 0))
            elif pnl < 0:
                dpg.configure_item("pnl_text", color=(255, 0, 0))
            else:
                dpg.configure_item("pnl_text", color=(255, 255, 255))

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
                dpg.add_spacer(width=20)
                dpg.add_text("P&L:")
                dpg.add_text("$0.00", tag="pnl_text")

            dpg.add_separator()

            # Quantity input
            dpg.add_input_int(
                label="Quantity",
                tag="quantity_input",
                default_value=1,
                min_value=1,
                max_value=100,
                callback=self._on_quantity_change,
                width=100,
            )

            dpg.add_spacer(height=10)

            # Order buttons
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="BUY",
                    tag="buy_btn",
                    callback=self._on_buy_click,
                    width=100,
                    height=50,
                )
                dpg.add_button(
                    label="SELL",
                    tag="sell_btn",
                    callback=self._on_sell_click,
                    width=100,
                    height=50,
                )

            dpg.add_spacer(height=10)

            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="REVERSE",
                    callback=self._on_reverse_click,
                    width=100,
                    height=40,
                )
                dpg.add_button(
                    label="FLATTEN",
                    callback=self._on_flatten_click,
                    width=100,
                    height=40,
                )

        # Theme for buy/sell buttons
        with dpg.theme() as buy_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 100, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (0, 150, 0))
        dpg.bind_item_theme("buy_btn", buy_theme)

        with dpg.theme() as sell_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (150, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (200, 0, 0))
        dpg.bind_item_theme("sell_btn", sell_theme)

        dpg.create_viewport(title="iborker Click Trader", width=350, height=350)
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
            # Cleanup
            self._run_async(self.disconnect())
            self._stop_event_loop()
            dpg.destroy_context()


def main() -> None:
    """Entry point for click trader."""
    trader = ClickTrader()
    trader.run()


if __name__ == "__main__":
    main()
