from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from aiocasambi import Casambi
from aiocasambi.error import AiocasambiException

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_API_KEY,
    CONF_NETWORK_UUID,
    CONF_NETWORK_PASSWORD,
)

_LOGGER = logging.getLogger(__name__)


class CasambiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Central coordinator that manages the aiocasambi client and pushes updates to HA."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.hass = hass
        self.config = config
        self.client: Optional[Casambi] = None
        # Latest known state per unit id
        self.units: dict[str, Any] = {}

    async def _ensure_connected(self) -> None:
        """Create the client if needed and connect (idempotent)."""
        if self.client is not None:
            return

        try:
            self.client = Casambi(
                api_key=self.config[CONF_API_KEY],
                email=self.config[CONF_EMAIL],
                network_uuid=self.config[CONF_NETWORK_UUID],
                network_password=self.config[CONF_NETWORK_PASSWORD],
            )
            await self.client.connect()  # opens OAuth + websocket
            _LOGGER.info("Connected to Casambi network %s", self.config[CONF_NETWORK_UUID])
            await self._async_setup_listeners()
        except AiocasambiException as err:
            _LOGGER.error("Failed to connect to Casambi: %s", err)
            raise

    async def _async_setup_listeners(self) -> None:
        """Subscribe to Casambi websocket events and map them to HA updates."""
        if not self.client:
            return

        async def handle_unit_changed(event: dict[str, Any]) -> None:
            """Unit state changed (on/off, level, color temp, etc.)."""
            unit_id = str(event.get("id"))
            if unit_id:
                self.units[unit_id] = event
            # Push new data to entities
            self.async_set_updated_data(self.units)

        async def handle_scene_changed(event: dict[str, Any]) -> None:
            """Scene activations/changes; we currently just trigger a refresh."""
            _LOGGER.debug("Scene changed: %s", event)
            self.async_set_updated_data(self.units)

        def _attach(event_name: str, cb: Callable[[dict[str, Any]], Awaitable[None]]):
            """Attach listener using whichever hook the client exposes."""
            try:
                # Preferred in newer aiocasambi versions
                self.client.on(event_name, cb)  # type: ignore[attr-defined]
                _LOGGER.debug("Attached listener using .on('%s', ...)", event_name)
                return
            except Exception:  # noqa: BLE001 - be defensive across versions
                pass

            # Fallback: method per event (e.g. on_unit_changed)
            try:
                getattr(self.client, f"on_{event_name}")(cb)  # type: ignore[attr-defined]
                _LOGGER.debug("Attached listener using .on_%s(...)", event_name)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Could not attach listener for %s: %s", event_name, err)

        _attach("unit_changed", handle_unit_changed)
        _attach("scene_changed", handle_scene_changed)

    async def _async_update_data(self) -> dict[str, Any]:
        """Initial load / manual refresh; fetch all units from Casambi."""
        await self._ensure_connected()
        assert self.client is not None
        try:
            units = await self.client.get_units()
            # Normalize into dict keyed by unit id for faster lookups
            self.units = {str(u.get("id")): u for u in units} if isinstance(units, list) else dict(units or {})
            return self.units
        except TypeError:
            # Older client may be sync
            units = self.client.get_units()  # type: ignore[call-arg]
            self.units = {str(u.get("id")): u for u in units}
            return self.units
        except AiocasambiException as err:
            _LOGGER.error("Casambi update failed: %s", err)
            raise