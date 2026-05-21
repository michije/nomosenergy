# Nomos Energy Home Assistant Integration

A custom Home Assistant integration that fetches 15-minute electricity price
data from the [Nomos Energy API](https://api.nomos.energy) and exposes it as
a small, focused set of sensors — following the same pattern used by the
popular Nordpool and Tibber integrations.

## Features

* Authenticates with your **Client ID** and **Client Secret**.
* Automatically discovers your first subscription.
* Retrieves **15-minute granularity** price data for **today** and **tomorrow**.
* Creates a compact set of sensors instead of hundreds of individual slots.
* Full price curve exposed as sensor attributes — works out-of-the-box with
  the [ApexCharts card](https://github.com/RomRider/apexcharts-card).
* DST-safe: all processing uses UTC internally; local times are computed per
  timestamp, so 23-hour and 25-hour days are handled correctly.
* Optional **price component** sensors (grid fee, energy, levies/taxes) when
  the API returns a breakdown.
* Refreshes every 15 minutes.

---

## Sensors

### Price sensors (unit: `ct/kWh`)

| Entity ID | Description |
|---|---|
| `sensor.nomosenergy_current_price` | Price for the current 15-min slot |
| `sensor.nomosenergy_next_price` | Price for the next 15-min slot |
| `sensor.nomosenergy_today_min` | Lowest price today |
| `sensor.nomosenergy_today_max` | Highest price today |
| `sensor.nomosenergy_today_average` | Average price today |
| `sensor.nomosenergy_tomorrow_min` | Lowest price tomorrow (`None` until published) |
| `sensor.nomosenergy_tomorrow_max` | Highest price tomorrow |
| `sensor.nomosenergy_tomorrow_average` | Average price tomorrow |

### Optional component sensors

Created automatically if the API returns a price breakdown:

| Entity ID | Description |
|---|---|
| `sensor.nomosenergy_current_price_grid` | Grid fee component |
| `sensor.nomosenergy_current_price_energy` | Pure energy component |
| `sensor.nomosenergy_current_price_levies` | Taxes / levies component |

### Diagnostic sensors

| Entity ID | Description |
|---|---|
| `sensor.nomosenergy_last_update_time` | Timestamp of the last successful fetch |
| `sensor.nomosenergy_last_update_success` | `True` / `False` |

---

## Price Curve Attributes

The `today_min`, `today_max`, `today_average` (and their `tomorrow_*`
equivalents) sensors expose the full price curve as an attribute called
`prices`.  This is a list of dicts:

```yaml
prices:
  - start: "2025-05-21T00:00:00+02:00"
    price: 22.4
  - start: "2025-05-21T00:15:00+02:00"
    price: 21.9
  # …95 more entries for a normal day
```

`sensor.nomosenergy_current_price` additionally provides:

```yaml
current_price_start: "2025-05-21T14:15:00+02:00"
current_price_end:   "2025-05-21T14:30:00+02:00"
next_price: 19.8
current_components:   # raw dict of any component fields returned by the API
  grid: 8.2
  electricity: 11.6
  levies: 2.6
```

---

## ApexCharts Card Example

```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: day
series:
  - entity: sensor.nomosenergy_today_min
    attribute: prices
    data_generator: |
      return entity.attributes.prices.map(e => [new Date(e.start).getTime(), e.price]);
    type: area
    name: Today's prices
```

---

## Installation via HACS

1. In Home Assistant, open the **HACS** panel.
2. Click **⋮ → Custom repositories**, enter this repository URL and select
   **Integration**.
3. Search for **Nomos Energy** and install it.
4. Restart Home Assistant when prompted.

## Configuration

Go to **Settings → Devices & Services → Add Integration**, search for
**Nomos Energy**, and enter your **Client ID** and **Client Secret**
(available from your energy supplier).

## Troubleshooting

* **Auth errors** — double-check your Client ID and Secret.
* **Missing tomorrow data** — prices for the next day are typically published
  in the afternoon.  Until then, the `tomorrow_*` sensors report `None`.
* **Only one subscription is used** — if you have multiple subscriptions, only
  the first returned by the API will be active.

## License

MIT — see `LICENSE` for details.
