"""Support for sensor."""
import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.components.sensor import (
    SensorEntity,
    DOMAIN as ENTITY_DOMAIN,
)

from . import (
    DOMAIN,
    PetkitEntity,
    async_setup_accounts,
)

_LOGGER = logging.getLogger(__name__)

DATA_KEY = f'{ENTITY_DOMAIN}.{DOMAIN}'


async def async_setup_entry(hass, config_entry, async_add_entities):
    cfg = {**config_entry.data, **config_entry.options}
    await async_setup_platform(hass, cfg, async_setup_platform, async_add_entities)


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    hass.data[DOMAIN]['add_entities'][ENTITY_DOMAIN] = async_add_entities
    await async_setup_accounts(hass, ENTITY_DOMAIN)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        'request_api',
        {
            vol.Required('api'): cv.string,
            vol.Optional('params', default={}): vol.Any(dict, None),
            vol.Optional('method', default='GET'): cv.string,
            vol.Optional('throw', default=True): cv.boolean,
        },
        'async_request_api',
    )


class PetkitSensorEntity(PetkitEntity, SensorEntity):
    """ PetkitSensorEntity """
