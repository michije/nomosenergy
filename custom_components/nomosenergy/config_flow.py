"""Config flow for the Nomos Energy integration."""

from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_CLIENT_ID, CONF_CLIENT_SECRET

_LOGGER = logging.getLogger(__name__)


class NomosEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nomos Energy."""

    VERSION = 1
    MINOR_VERSION = 0

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step for the user to enter credentials."""
        if user_input is not None:
            # Prevent multiple instances
            existing = self._async_current_entries()
            if existing:
                return self.async_abort(reason="single_instance_allowed")
            return self.async_create_entry(title="Nomos Energy", data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_CLIENT_ID): str,
            vol.Required(CONF_CLIENT_SECRET): str,
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return NomosEnergyOptionsFlowHandler(config_entry)


class NomosEnergyOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for an existing configuration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update options: currently there are no configurable options
            return self.async_create_entry(title="Nomos Energy Options", data=user_input)

        # For now there are no adjustable options. Show an empty form to
        # allow saving to close the flow.
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
