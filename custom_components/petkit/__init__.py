"""The component."""
import logging
import hashlib
import datetime
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.const import *
from homeassistant.components import persistent_notification
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.storage import Store
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
import homeassistant.helpers.config_validation as cv
from aiohttp.client_exceptions import ClientConnectorError

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'petkit'
SCAN_INTERVAL = datetime.timedelta(minutes=2)

CONF_ACCOUNTS = 'accounts'
CONF_API_BASE = 'api_base'
CONF_USER_ID = 'uid'
CONF_FEEDING_AMOUNT = 'feeding_amount'

DEFAULT_API_BASE = 'http://api.petkit.cn/6/'

SUPPORTED_DOMAINS = [
    'sensor',
    'binary_sensor',
    'switch',
    'select',
]

ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_API_BASE, default=DEFAULT_API_BASE): cv.string,
        vol.Optional(CONF_USERNAME): cv.string,
        vol.Optional(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL): cv.time_period,
        vol.Optional(CONF_FEEDING_AMOUNT, default=10): vol.Any(int, cv.entity_id),
    },
    extra=vol.ALLOW_EXTRA,
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: ACCOUNT_SCHEMA.extend(
            {
                vol.Optional(CONF_ACCOUNTS): vol.All(cv.ensure_list, [ACCOUNT_SCHEMA]),
            },
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, hass_config: dict):
    hass.data.setdefault(DOMAIN, {})
    config = hass_config.get(DOMAIN) or {}
    hass.data[DOMAIN]['config'] = config
    hass.data[DOMAIN].setdefault(CONF_ACCOUNTS, {})
    hass.data[DOMAIN].setdefault(CONF_DEVICES, {})
    hass.data[DOMAIN].setdefault('coordinators', {})
    hass.data[DOMAIN].setdefault('add_entities', {})

    component = EntityComponent(_LOGGER, DOMAIN, hass, SCAN_INTERVAL)
    hass.data[DOMAIN]['component'] = component
    await component.async_setup(config)

    als = config.get(CONF_ACCOUNTS) or []
    if CONF_PASSWORD in config:
        acc = {**config}
        acc.pop(CONF_ACCOUNTS, None)
        als.append(acc)
    for cfg in als:
        if not cfg.get(CONF_PASSWORD) and not cfg.get(CONF_TOKEN):
            continue
        acc = PetkitAccount(hass, cfg)
        coordinator = DevicesCoordinator(acc)
        await acc.async_check_auth()
        await coordinator.async_config_entry_first_refresh()
        hass.data[DOMAIN][CONF_ACCOUNTS][acc.uid] = acc
        hass.data[DOMAIN]['coordinators'][coordinator.name] = coordinator

    for platform in SUPPORTED_DOMAINS:
        hass.async_create_task(
            hass.helpers.discovery.async_load_platform(platform, DOMAIN, {}, config)
        )

    return True


async def async_setup_accounts(hass: HomeAssistant, domain):
    for coordinator in hass.data[DOMAIN]['coordinators'].values():
        for k, sta in coordinator.data.items():
            await coordinator.update_hass_entities(domain, sta)


class PetkitAccount:
    def __init__(self, hass: HomeAssistant, config: dict):
        self._config = config
        self.hass = hass
        self.http = aiohttp_client.async_create_clientsession(hass, auto_cleanup=False)

    def get_config(self, key, default=None):
        return self._config.get(key, self.hass.data[DOMAIN]['config'].get(key, default))

    @property
    def username(self):
        return self._config.get(CONF_USERNAME)

    @property
    def password(self):
        pwd = self._config.get(CONF_PASSWORD)
        if len(pwd) != 32:
            pwd = hashlib.md5(f'{pwd}'.encode()).hexdigest()
        return pwd

    @property
    def uid(self):
        return self._config.get(CONF_USER_ID) or self.username

    @property
    def token(self):
        return self._config.get(CONF_TOKEN) or ''

    @property
    def update_interval(self):
        return self.get_config(CONF_SCAN_INTERVAL) or SCAN_INTERVAL

    def api_url(self, api=''):
        if api[:6] == 'https:' or api[:5] == 'http:':
            return api
        bas = self.get_config(CONF_API_BASE) or DEFAULT_API_BASE
        return f"{bas.rstrip('/')}/{api.lstrip('/')}"

    async def request(self, api, pms=None, method='GET', **kwargs):
        method = method.upper()
        url = self.api_url(api)
        kws = {
            'timeout': 20,
            'headers': {
                'User-Agent': 'okhttp/3.12.1',
                'X-Api-Version': '7.29.1',
                'X-Client': 'Android(7.1.1;Xiaomi)',
                'X-Session': f'{self.token}',
            },
        }
        kws.update(kwargs)
        if method in ['GET']:
            kws['params'] = pms
        elif method in ['POST_GET']:
            method = 'POST'
            kws['params'] = pms
        else:
            kws['data'] = pms
        try:
            req = await self.http.request(method, url, **kws)
            return await req.json() or {}
        except ClientConnectorError as exc:
            _LOGGER.error('Request Petkit api failed: %s', [method, url, pms, exc])
        return {}

    async def async_login(self):
        pms = {
            'encrypt': 1,
            'username': self.username,
            'password': self.password,
            'oldVersion': '',
        }
        rsp = await self.request(f'user/login', pms, 'POST_GET')
        ssn = rsp.get('result', {}).get('session') or {}
        sid = ssn.get('id')
        if not sid:
            _LOGGER.error('Petkit login %s failed: %s', self.username, rsp)
            return False
        self._config.update({
            CONF_TOKEN: sid,
            CONF_USER_ID: ssn.get('userId'),
        })
        await self.async_check_auth(True)
        return True

    async def async_check_auth(self, save=False):
        fnm = f'{DOMAIN}/auth-{self.username}.json'
        sto = Store(self.hass, 1, fnm)
        old = await sto.async_load() or {}
        if save:
            cfg = {
                CONF_USERNAME: self.username,
                CONF_USER_ID: self.uid,
                CONF_TOKEN: self.token,
            }
            if cfg.get(CONF_TOKEN) == old.get(CONF_TOKEN):
                cfg['update_at'] = old.get('update_at')
            else:
                cfg['update_at'] = f'{datetime.datetime.today()}'
            await sto.async_save(cfg)
            return cfg
        if old.get(CONF_TOKEN):
            self._config.update({
                CONF_TOKEN: old.get(CONF_TOKEN),
                CONF_USER_ID: old.get(CONF_USER_ID),
            })
        else:
            await self.async_login()
        return old

    async def get_devices(self):
        api = 'discovery/device_roster'
        rsp = await self.request(api)
        eno = rsp.get('error', {}).get('code', 0)
        if eno == 5:
            if await self.async_login():
                rsp = await self.request(api)
        dls = rsp.get('result', {}).get(CONF_DEVICES) or []
        if not dls:
            _LOGGER.warning('Got petkit devices for %s failed: %s', self.username, rsp)
        return dls


class DevicesCoordinator(DataUpdateCoordinator):
    def __init__(self, account: PetkitAccount):
        super().__init__(
            account.hass,
            _LOGGER,
            name=f'{DOMAIN}-{account.uid}-{CONF_DEVICES}',
            update_interval=account.update_interval,
        )
        self.account = account
        self._subs = {}

    async def _async_update_data(self):
        dls = await self.account.get_devices()
        for dvc in dls:
            dat = dvc.get('data') or {}
            did = dat.get('id')
            if not did:
                continue
            typ = dat['type'] = dvc.get('type') or ''
            old = self.hass.data[DOMAIN][CONF_DEVICES].get(did)
            if old:
                dvc = old
                dvc.update_data(dat)
            else:
                if typ.lower() in ['t3']:
                    dvc = LitterDevice(dat, self)
                else:
                    dvc = FeederDevice(dat, self)
                self.hass.data[DOMAIN][CONF_DEVICES][did] = dvc
            await dvc.update_device_detail()
            for d in SUPPORTED_DOMAINS:
                await self.update_hass_entities(d, dvc)
        return self.hass.data[DOMAIN][CONF_DEVICES]

    async def update_hass_entities(self, domain, dvc):
        from .sensor import PetkitSensorEntity
        from .binary_sensor import PetkitBinarySensorEntity
        from .switch import PetkitSwitchEntity
        from .select import PetkitSelectEntity
        hdk = f'hass_{domain}'
        add = self.hass.data[DOMAIN]['add_entities'].get(domain)
        if not add or not hasattr(dvc, hdk):
            return
        for k, cfg in getattr(dvc, hdk).items():
            key = f'{domain}.{k}.{dvc.device_id}'
            new = None
            if key in self._subs:
                pass
            elif add and domain == 'sensor':
                new = PetkitSensorEntity(k, dvc, cfg)
            elif add and domain == 'binary_sensor':
                new = PetkitBinarySensorEntity(k, dvc, cfg)
            elif add and domain == 'switch':
                new = PetkitSwitchEntity(k, dvc, cfg)
            elif domain == 'select':
                new = PetkitSelectEntity(k, dvc, cfg)
            if new:
                self._subs[key] = new
                add([new])


class PetkitDevice:
    data: dict

    def __init__(self, dat: dict, coordinator: DevicesCoordinator):
        self.coordinator = coordinator
        self.account = coordinator.account
        self.listeners = {}
        self.update_data(dat)
        self.detail = {}

    def update_data(self, dat: dict):
        self.data = dat
        self._handle_listeners()
        _LOGGER.info('Update petkit device data: %s', dat)

    def _handle_listeners(self):
        for fun in self.listeners.values():
            fun()

    @property
    def device_id(self):
        return self.data.get('id')

    @property
    def device_type(self):
        return self.data.get('type', '').lower()

    @property
    def device_name(self):
        return self.data.get('name', '')

    @property
    def status(self):
        return self.data.get('status') or {}

    @property
    def state(self):
        sta = self.data.get('state') or 0
        dic = {
            '1': 'online',
            '2': 'offline',
            '3': 'feeding',
            '4': 'mate_ota',
            '5': 'device_error',
            '6': 'battery_mode',
        }
        return dic.get(f'{sta}'.strip(), sta)

    def state_attrs(self):
        return {
            'state': self.data.get('state'),
            'desc':  self.data.get('desc'),
            'status': self.status,
            'shared': self.data.get('deviceShared'),
        }

    @property
    def hass_sensor(self):
        return {
            'state': {
                'icon': 'mdi:information',
                'state_attrs': self.state_attrs,
            },
        }

    @property
    def hass_binary_sensor(self):
        return {}

    @property
    def hass_switch(self):
        return {}

    async def update_device_detail(self):
        api = f'{self.device_type}/device_detail'
        pms = {
            'id': self.device_id,
        }
        rsp = None
        try:
            rsp = await self.account.request(api, pms)
            rdt = rsp.get('result') or {}
        except (TypeError, ValueError) as exc:
            rdt = {}
            _LOGGER.error('Got petkit device detail for %s failed: %s', self.device_name, exc)
        if not rdt:
            _LOGGER.warning('Got petkit device detail for %s failed: %s', self.device_name, rsp)
        self.detail = rdt
        return rdt


class FeederDevice(PetkitDevice):

    @property
    def desiccant(self):
        return self.status.get('desiccantLeftDays') or 0

    @property
    def food_state(self):
        return self.status.get('food', 0) == 0

    def food_state_attrs(self):
        return {
            'state': self.status.get('food'),
            'desc': 'normal' if not self.food_state else 'few',
        }

    @property
    def feed_times(self):
        return self.feed_state_attrs().get('times', 0)

    @property
    def feed_amount(self):
        return self.feed_state_attrs().get('realAmountTotal', 0)

    def feed_state_attrs(self):
        return self.detail.get('state', {}).get('feedState') or {}

    @property
    def feeding(self):
        return False

    @property
    def feeding_amount(self):
        num = self.account.get_config(CONF_FEEDING_AMOUNT)
        eid = f'{num}'
        if 'input_number.' in eid:
            sta = self.account.hass.states.get(eid)
            if sta:
                num = sta.state
        try:
            num = int(float(num))
        except (TypeError, ValueError):
            num = 10
        return num

    def feeding_attrs(self):
        return {
            'feeding_amount': self.feeding_amount,
            'desc': self.data.get('desc'),
            'error': self.status.get('errorMsg'),
            **self.feed_state_attrs(),
        }

    @property
    def hass_sensor(self):
        return {
            **super().hass_sensor,
            'desiccant': {
                'unit': 'days',
                'icon': 'mdi:air-filter',
            },
            'feed_times': {
                'unit': 'times',
                'icon': 'mdi:counter',
                'state_attrs': self.feed_state_attrs,
            },
            'feed_amount': {
                'unit': 'g',
                'icon': 'mdi:weight-gram',
                'state_attrs': self.feed_state_attrs,
            },
        }

    @property
    def hass_binary_sensor(self):
        return {
            **super().hass_binary_sensor,
            'food_state': {
                'icon': 'mdi:food-drumstick-outline',
                'class': 'problem',
                'state_attrs': self.food_state_attrs,
            },
        }

    @property
    def hass_switch(self):
        return {
            **super().hass_switch,
            'feeding': {
                'icon': 'mdi:shaker',
                'state_attrs': self.feeding_attrs,
                'async_turn_on': self.feeding_now,
            },
        }

    async def feeding_now(self, **kwargs):
        typ = self.device_type
        api = 'feeder/save_dailyfeed'
        if typ == 'feedermini':
            api = 'feedermini/save_dailyfeed'
        elif typ in ['d3', 'd4']:
            api = f'{typ}/saveDailyFeed'
        pms = {
            'deviceId': self.device_id,
            'day': datetime.datetime.today().strftime('%Y%m%d'),
            'time': -1,
            'amount': self.feeding_amount,
        }
        rdt = await self.account.request(api, pms)
        eno = rdt.get('error', {}).get('code', 0)
        if eno:
            _LOGGER.error('Petkit feeding failed: %s', rdt)
            return False
        await self.update_device_detail()
        _LOGGER.info('Petkit feeding now: %s', rdt)
        return rdt


class LitterDevice(PetkitDevice):

    @property
    def power(self):
        return not not self.status.get('power')

    @property
    def box_full(self):
        return self.status.get('boxFull')

    @property
    def sand_percent(self):
        return self.status.get('sandPercent')

    def sand_attrs(self):
        return {
            'sand_lack': self.status.get('sandLack'),
            'sand_weight': self.status.get('sandWeight'),
        }

    @property
    def in_times(self):
        return self.detail.get('inTimes')

    @property
    def records(self):
        return self.detail.get('records') or []

    @property
    def last_record(self):
        evt = self.last_record_attrs().get('eventType') or 0
        dic = {
            5: 'cleaned',
            6: 'dumped',
            7: 'reset',
            8: 'deodorized',
            10: 'occupied',
        }
        return dic.get(evt, evt)

    def last_record_attrs(self):
        rls = self.records
        if not rls:
            return {}
        lst = rls[-1] or {}
        ctx = lst.pop('content', None) or {}
        return {**lst, **ctx}

    @property
    def hass_sensor(self):
        return {
            **super().hass_sensor,
            'sand_percent': {
                'icon': 'mdi:percent-outline',
                'state_attrs': self.sand_attrs,
            },
            'in_times': {
                'icon': 'mdi:location-enter',
            },
            'last_record': {
                'icon': 'mdi:history',
                'state_attrs': self.last_record_attrs,
            },
        }

    @property
    def hass_binary_sensor(self):
        return {
            **super().hass_binary_sensor,
            'box_full': {
                'icon': 'mdi:tray-full',
                'class': 'problem',
            },
        }

    @property
    def hass_switch(self):
        return {
            **super().hass_switch,
            'power': {
                'icon': 'mdi:power',
                'async_turn_on': self.turn_on,
                'async_turn_off': self.turn_off,
            },
        }

    @property
    def hass_select(self):
        return {
            'action': {
                'icon': 'mdi:play-box',
                'options': list(self.actions.keys()),
                'async_select': self.select_action,
                'delay_update': 5,
            },
        }

    async def update_device_detail(self):
        await super().update_device_detail()
        api = f'{self.device_type}/getDeviceRecord'
        pms = {
            'deviceId': self.device_id,
        }
        rsp = None
        try:
            rsp = await self.account.request(api, pms)
            rdt = rsp.get('result') or {}
        except (TypeError, ValueError):
            rdt = {}
        if not rdt:
            _LOGGER.warning('Got petkit device records for %s failed: %s', self.device_name, rsp)
        self.detail['records'] = rdt
        return rdt

    async def turn_on(self):
        return await self.set_power(True)

    async def turn_off(self):
        return await self.set_power(False)

    async def set_power(self, on=True):
        val = 1 if on else 0
        dat = '{"power_action":"%s"}' % val
        return await self.control_device(type='power', kv=dat)

    @property
    def action(self):
        return None

    @property
    def actions(self):
        return {
            'start':    1,
            'stop':     2,
            'end':      3,
            'continue': 4,
        }

    async def select_action(self, action, **kwargs):
        val = self.actions.get(action, 0)
        dat = '{"%s_action":"%s"}' % (action, val)
        return await self.control_device(type=action, kv=dat)

    async def control_device(self, **kwargs):
        typ = self.device_type
        api = f'{typ}/controlDevice'
        pms = {
            'id': self.device_id,
            **kwargs,
        }
        rdt = await self.account.request(api, pms)
        eno = rdt.get('error', {}).get('code', 0)
        if eno:
            _LOGGER.error('Petkit device control failed: %s', rdt)
            return False
        await self.update_device_detail()
        _LOGGER.info('Petkit device control: %s', rdt)
        return rdt


class PetkitEntity(CoordinatorEntity):
    def __init__(self, name, device: PetkitDevice, option=None):
        self.coordinator = device.coordinator
        CoordinatorEntity.__init__(self, self.coordinator)
        self.account = self.coordinator.account
        self._name = name
        self._device = device
        self._option = option or {}
        self._attr_name = f'{device.device_name} {name}'.strip()
        self._attr_device_id = f'{device.device_type}_{device.device_id}'
        self._attr_unique_id = f'{self._attr_device_id}-{name}'
        self.entity_id = f'{DOMAIN}.{self._attr_device_id}_{name}'
        self._attr_icon = self._option.get('icon')
        self._attr_device_class = self._option.get('class')
        self._attr_unit_of_measurement = self._option.get('unit')
        self._attr_device_info = {
            'identifiers': {(DOMAIN, self._attr_device_id)},
            'name': device.data.get('name'),
            'model': device.data.get('type'),
            'manufacturer': 'Petkit',
            'sw_version': device.detail.get('firmware'),
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._device.listeners[self.entity_id] = self._handle_coordinator_update
        self._handle_coordinator_update()

    def _handle_coordinator_update(self):
        self.update()
        self.async_write_ha_state()

    def update(self):
        if hasattr(self._device, self._name):
            self._attr_state = getattr(self._device, self._name)
            _LOGGER.debug('Petkit entity update: %s', [self.entity_id, self._name, self._attr_state])

        fun = self._option.get('state_attrs')
        if callable(fun):
            self._attr_extra_state_attributes = fun()

    @property
    def state(self):
        return self._attr_state

    async def async_request_api(self, api, params=None, method='GET', **kwargs):
        throw = kwargs.pop('throw', None)
        rdt = await self.account.request(api, params, method, **kwargs)
        if throw:
            persistent_notification.create(
                self.hass,
                f'{rdt}',
                f'Request: {api}',
                f'{DOMAIN}-request',
            )
        return rdt


class PetkitBinaryEntity(PetkitEntity):
    def __init__(self, name, device: PetkitDevice, option=None):
        super().__init__(name, device, option)
        self._attr_is_on = False

    def update(self):
        super().update()
        if hasattr(self._device, self._name):
            self._attr_is_on = not not getattr(self._device, self._name)
        else:
            self._attr_is_on = False

    @property
    def state(self):
        return STATE_ON if self._attr_is_on else STATE_OFF
