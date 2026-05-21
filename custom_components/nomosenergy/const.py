"""Constants for the Nomos Energy integration."""

DOMAIN = "nomosenergy"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"

# Base URL for the Nomos Energy API
API_BASE_URL = "https://api.nomos.energy"

# Number of hours in a day, kept for backward-compatibility references
HOURS_IN_DAY = 24

# 15-minute interval support: 96 slots per day (4 per hour × 24 hours)
INTERVALS_PER_DAY = 96
INTERVAL_MINUTES = 15
