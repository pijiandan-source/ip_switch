# -*- coding: utf-8 -*-
"""Default network settings for NetworkSwitcher."""

DEFAULT_IP = "112.13.121.254"
ALTERNATE_DEFAULT_IP = "112.13.121.253"
DEFAULT_MASK = "255.255.255.128"
DEFAULT_GATEWAY = "112.13.121.129"
DEFAULT_DNS = "223.5.5.5"

# Routes managed by this tool only.
# Add your company-specific external network routes here when needed.
# Example:
# ROUTES = [
#     {"dest": "10.10.0.0", "mask": "255.255.0.0", "gateway": DEFAULT_GATEWAY},
# ]
ROUTES = []
