# -*- coding: utf-8 -*-
"""Default network settings for NetworkSwitcher."""

TEMP_IP = "112.13.121.254"
ALTERNATE_TEMP_IP = "112.13.121.253"
DEFAULT_IP = TEMP_IP
ALTERNATE_DEFAULT_IP = ALTERNATE_TEMP_IP
DEFAULT_MASK = "255.255.255.128"
DEFAULT_GATEWAY = "112.13.121.129"
DEFAULT_DNS = "223.5.5.5"

NETWORK_APPLY_DELAY_SECONDS = 2.0
PING_RETRY_COUNT = 2
PING_RETRY_INTERVAL_SECONDS = 1.0
SCAN_PING_COUNT = 1
SCAN_PING_TIMEOUT_MS = 800
CLEAR_ARP_CACHE_BEFORE_SCAN = False

# Routes managed by this tool only.
# Add your company-specific external network routes here when needed.
# Example:
# ROUTES = [
#     {"dest": "10.10.0.0", "mask": "255.255.0.0", "gateway": DEFAULT_GATEWAY},
# ]
ROUTES = []
