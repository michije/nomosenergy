# Nomos Energy Home Assistant Integration

This custom integration fetches hourly electricity price data from the
Nomos Energy API and exposes it as sensors within Home Assistant.  It
is inspired by the existing ioBroker adapter
[`ioBroker.nomosenergy`](https://github.com/michije/ioBroker.nomosenergy) and
shares the same goal of making hourly energy prices available in your
smart‑home system.

## Features

* Uses your **Client ID** and **Client Secret** to authenticate with the
  Nomos Energy API.
* Automatically discovers your first subscription and retrieves price
  series for **today** and **tomorrow**.
* Creates sensors for each hour of the current and next day (e.g.
  `sensor.nomosenergy_price_today_00`, `sensor.nomosenergy_price_tomorrow_23`).
* Provides a `sensor.nomosenergy_current_price` sensor that always
  reflects the price for the current hour in the Europe/Berlin
  time zone.
* Refreshes the data every hour and automatically adjusts for Daylight
  Saving Time.

## Installation via HACS

1. In Home Assistant, open the **HACS** panel.
2. Click the **⋮** menu in the top right and choose **Custom
   repositories**.
3. Enter the URL of this repository (e.g.
   `https://github.com/michije/nomosenergy`) and select **Integration**
   as the category.
4. Press **Add**, then search for **Nomos Energy** in HACS and
   install it.
5. Restart Home Assistant when prompted.

## Configuration

After installation, go to **Settings → Devices & Services**, click
**Add Integration**, and search for **Nomos Energy**.  You will be asked
to enter your **Client ID** and **Client Secret**.  These values are
available from your energy supplier.  Once configured, the sensors
will appear and start updating automatically.

## Troubleshooting

* If you see errors about authentication or no subscription being
  found, double‑check your Client ID and Client Secret in the
  integration's configuration.
* The integration only supports one subscription (the first one
  returned by the API).  If you have multiple subscriptions, only
  the first will be used.
* Prices update hourly; if you don't see tomorrow's values right
  away, they may not be published yet.

## License

This project is licensed under the MIT License.  See the `LICENSE`
file for details.
