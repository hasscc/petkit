"""Support for select."""
import logging
import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.components.select import (
    SelectEntity,
    DOMAIN as ENTITY_DOMAIN,
)

from . import (
    DOMAIN,
    PetkitDevice,
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


class PetkitSelectEntity(PetkitEntity, SelectEntity):
    def __init__(self, name, device: PetkitDevice, option=None):
        super().__init__(name, device, option)
        self._attr_current_option = None
        self._attr_options = self._option.get('options')

    def update(self):
        super().update()
        self._attr_current_option = self._attr_state

    async def async_select_option(self, option: str):
        """Change the selected option."""
        ret = False
        fun = self._option.get('async_select')
        if callable(fun):
            kws = {
                'entity': self,
            }
            ret = await fun(option, **kws)
        if ret:
            self._attr_current_option = option
            self.async_write_ha_state()
            if dly := self._option.get('delay_update'):
                await asyncio.sleep(dly)
                self._handle_coordinator_update()
        return ret
