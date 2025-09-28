"""
Support for Casambi lights.
For more details about this component, please refer to the documentation at
https://home-assistant.io/components/@todo
"""

import logging
import voluptuous as vol

from homeassistant.components.light import ATTR_BRIGHTNESS

try:
    from homeassistant.components.light import ATTR_DISTRIBUTION
except ImportError:
    ATTR_DISTRIBUTION = "distribution"

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_platform

from .const import (
    DOMAIN,
    CONF_CONTROLLER,
    CONF_COORDINATOR,
    SERVICE_CASAMBI_LIGHT_TURN_ON,
    ATTR_SERV_BRIGHTNESS,
    ATTR_SERV_DISTRIBUTION,
    ATTR_SERV_ENTITY_ID,
)

from .casambi.CasambiLightEntity import CasambiLightEntity

_LOGGER = logging.getLogger(__name__)

CASAMBI_CONTROLLER = None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
):
    """
    Setup sensors from a config entry created in the integrations UI.
    """
    # Prefer existing controller if present (backwards compat). Otherwise, create a thin
    # proxy around the aiocasambi client from the coordinator so existing entities keep working.
    coordinator = hass.data[DOMAIN][CONF_COORDINATOR]
    controller = hass.data[DOMAIN].get(CONF_CONTROLLER)

    if controller is None:
        class _ControllerProxy:
            def __init__(self, client):
                self.aiocasambi_controller = client
                self.lights = {}

        proxy = _ControllerProxy(coordinator.client)
        hass.data[DOMAIN][CONF_CONTROLLER] = proxy
        controller = proxy

    # Get units (support both sync getter and async method from aiocasambi)
    units = None
    try:
        # aiocasambi >= OpenAPI uses async get_units()
        units = await controller.aiocasambi_controller.get_units()  # type: ignore[func-returns-value]
    except TypeError:
        # legacy client returns a list directly
        units = controller.aiocasambi_controller.get_units()

    for unit in units:
        if not unit.is_light():
            continue

        casambi_light = CasambiLightEntity(coordinator, unit, controller, hass)
        async_add_entities([casambi_light], True)

    # add entity service to turn on Casambi light
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_CASAMBI_LIGHT_TURN_ON,
        {
            vol.Required(ATTR_BRIGHTNESS): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=255)
            ),
            vol.Optional(ATTR_DISTRIBUTION): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=255)
            ),
        },
        "async_handle_entity_service_light_turn_on",
    )

    return True
