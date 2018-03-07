# IMPORTS
import asyncio
import logging
import re
import time
import datetime
import voluptuous as vol

import homeassistant.components.mqtt as mqtt
from homeassistant.components.mqtt import (CONF_DISCOVERY_PREFIX, CONF_QOS, valid_discovery_topic, _VALID_QOS_SCHEMA)
from homeassistant.helpers.discovery import (async_load_platform, load_platform)
from homeassistant.helpers.event import (async_track_time_interval)
from homeassistant.helpers import (config_validation as cv)
from homeassistant.const import (EVENT_HOMEASSISTANT_STOP)
from .mqtt_message import (MQTTMessage)
from .homie_classes import (HomieDevice)

# TYPES
from typing import (Dict, List, Callable)
from homeassistant.helpers.typing import (HomeAssistantType, ConfigType)
from ._typing import (MessageQue)

Devices = List[HomieDevice]

# REGEX
DISCOVER_DEVICE = re.compile(r'(?P<prefix_topic>\w[-/\w]*\w)/(?P<device_id>\w[-\w]*\w)/\$homie')


# CONSTANTS
DOMAIN = 'homie'
DEPENDENCIES = ['mqtt']
INTERVAL_SECONDS = 1
MESSAGE_MAX_KEEP_SECONDS = 5
HOMIE_SUPPORTED_VERSION = '2.0.0'
DEFAULT_DISCOVERY_PREFIX = 'homie'
DEFAULT_QOS = 0
KEY_HOMIE_DEVICES = 'HOMIE_DEVICES'
KEY_HOMIE_DEVICE_ID = 'HOMIE_DEVICE_ID'
KEY_HOMIE_NODE_ID = 'HOMIE_NODE_ID'

# CONFIg
CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(CONF_DISCOVERY_PREFIX, default=DEFAULT_DISCOVERY_PREFIX): valid_discovery_topic,
        vol.Optional(CONF_QOS, default=DEFAULT_QOS): _VALID_QOS_SCHEMA,
    }),
}, extra=vol.ALLOW_EXTRA)

# GLOBALS
_LOGGER = logging.getLogger(__name__)


@asyncio.coroutine
def async_setup(hass: HomeAssistantType, config: ConfigType):
    """Setup the Homie service."""
    _LOGGER.info(f"Component - {DOMAIN} - Setup")

    # Init
    _MQTT_MESSAGES = dict()
    _DEVICES = list()
    hass.data[KEY_HOMIE_DEVICES] = _DEVICES

    # Config
    conf = config.get(DOMAIN)
    if conf is None:
        conf = CONFIG_SCHEMA({DOMAIN: {}})[DOMAIN]
    discovery_prefix = conf.get(CONF_DISCOVERY_PREFIX)
    qos = conf.get(CONF_QOS)

    # Create Proccess Task
    @asyncio.coroutine
    def async_interval(time: datetime):
        discover_devices()
        proccess_messages()
        yield from async_setup_device_components()

    _Task = async_track_time_interval(hass, async_interval, datetime.timedelta(0, INTERVAL_SECONDS))

    # Destroy Homie
    @asyncio.coroutine
    def async_destroy(event):
        _LOGGER.info(f"Component - {DOMAIN} - Destroy")
        if _Task: _Task()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_destroy)

    # Sart
    @asyncio.coroutine
    def async_start():
        _LOGGER.info(f"Component - {DOMAIN} - Start. Discovery Topic: {discovery_prefix}/")
        yield from mqtt.async_subscribe(hass, f'{discovery_prefix}/#', async_device_message_received, qos)

    @asyncio.coroutine
    def async_device_message_received(topic: str, payload: str, qos: int):
        message = MQTTMessage(topic, payload, qos)
        _MQTT_MESSAGES[topic] = message
        proccess_messages()

    def proccess_messages():
        for device in _DEVICES:
            filtered_topics = {k:v for (k,v) in _MQTT_MESSAGES.items() if device._base_topic in k}
            device._update(filtered_topics)
        remove_messages()

    def remove_messages():
        to_remove = list()
        # Remove old message from the que
        for topic, message in _MQTT_MESSAGES.items():
            if message.seen or (time.clock() - message.timeStamp) > MESSAGE_MAX_KEEP_SECONDS:
                to_remove.append(topic)
        for topic in to_remove:
            del _MQTT_MESSAGES[topic]

    def discover_devices():
        for topic, message in _MQTT_MESSAGES.items():
            device_match = DISCOVER_DEVICE.match(topic)
            if device_match and message.payload == HOMIE_SUPPORTED_VERSION:
                device_base_topic = device_match.group('prefix_topic')
                device_id = device_match.group('device_id')
                if not has_device(device_id):
                    device = HomieDevice(device_base_topic, device_id)
                    _DEVICES.append(device)

    def has_device(device_id: str):
        for device in _DEVICES:
            if device.device_id == device_id:
                return True
        return False
    
    @asyncio.coroutine
    def async_setup_device_components():
        for device in _DEVICES:
            #_LOGGER.info(f"Device {device.device_id}")
            # Do device relate component Suff
            # TODO: create device sneosors for stats

            # Do Node related component stuff
            for node in device.nodes:
                #_LOGGER.info(f"Node {node.node_id}")
                if not node._is_setup:
                    if node.type == 'sensor':
                        # Setup Node as a Sensor
                        _LOGGER.info(f"Loading Sensor Platform for {device.device_id} -> {node.node_id}")
                        discovery_info = {KEY_HOMIE_DEVICE_ID: device.device_id, KEY_HOMIE_NODE_ID: node.node_id}
                        yield from async_load_platform(hass, 'sensor', DOMAIN, discovery_info)
                        node._is_setup = True
                        _LOGGER.info(f"Done Loading Sensor Platform for {device.device_id} -> {node.node_id}")
                    elif node.type == 'switch':
                        # Setup Node as a Switch
                        None

    yield from async_start()

    return True

