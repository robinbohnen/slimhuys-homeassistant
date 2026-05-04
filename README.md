# SlimHuys — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Home Assistant integratie voor [SlimHuys.nl](https://slimhuys.nl) — dynamische
stroomtarieven (EPEX day-ahead, NL) + push-bridge voor je P1/DSMR-meter.

## Wat krijg je?

**Negen sensors per leverancier:**

| Sensor | Eenheid | Voorbeeld |
|---|---|---|
| `sensor.huidige_prijs` | EUR/kWh | `0.158` |
| `sensor.epex_kale_prijs` | EUR/kWh | `0.082` |
| `sensor.daggemiddelde` | EUR/kWh | `0.217` |
| `sensor.laagste_vandaag` | EUR/kWh | `0.089` |
| `sensor.hoogste_vandaag` | EUR/kWh | `0.464` |
| `sensor.goedkoopste_blok_start` | string | `"2026-04-30 02:00"` |
| `sensor.goedkoopste_blok_gemiddelde` | EUR/kWh | `0.094` |
| `sensor.volgende_negatieve_prijs` | string | `"2026-04-30 13:00"` |
| `sensor.tariefniveau_nu` | enum | `very_low / low / medium / high / peak` |

Plus **één service** voor terug-push naar SlimHuys:

```yaml
service: slimhuys.push_reading
data:
  consumption_kwh_total: "{{ states('sensor.dsmr_reading_electricity_consumption_total') | float }}"
  delivered_kwh_total:    "{{ states('sensor.dsmr_reading_electricity_delivery_total')    | float }}"
  active_power_w:         "{{ (states('sensor.dsmr_reading_current_electricity_usage')    | float * 1000) | int }}"
```

## Installeren

### Via HACS (aanbevolen)

1. Open HACS → 3-puntjes menu → **Custom repositories**
2. URL: `https://github.com/SlimHuys/slimhuys-homeassistant`
3. Categorie: **Integration**
4. **Add** → zoek "SlimHuys" → **Download**
5. Restart Home Assistant
6. **Settings → Devices & Services → + Add Integration → SlimHuys**
7. Plak je API-key — die maak je aan op [slimhuys.nl/app/account?tab=api](https://slimhuys.nl/app/account?tab=api)

### Handmatig

Kopieer `custom_components/slimhuys/` naar je HA `config/custom_components/`-folder
en restart HA.

## P1/DSMR-meter pushen — geen YAML nodig

Tijdens **Add Integration** ziet de wizard 3 stappen: API-key → leverancier →
**P1-koppeling**. In de laatste stap detecteert de integratie automatisch
mogelijke DSMR-sensors en biedt 3 dropdowns aan:

- Cumulatief verbruik (kWh)
- Cumulatieve teruglevering (kWh)
- Huidig vermogen (W of kW — wordt automatisch geconverteerd)

Plus een push-interval (1–300 seconden, default 30s). De integratie pusht
zelf je waardes naar SlimHuys — je hoeft geen automation te schrijven.

> **1-seconde push** is sinds v0.2.0 mogelijk. DSMR-meters publiceren naturally
> elke ~1s; de SlimHuys-API rate-limit is 600/min/key (= 10/s) dus 1Hz uit één
> instance is comfortabel. Aan te raden voor live-dashboard-feel; voor
> energie-tracking is 30s ruim genoeg.

Werkt out-of-the-box met:

- **DSMR Slimme meter** (P1-poort via USB): `sensor.dsmr_reading_*`
- **HomeWizard P1-meter**: `sensor.p1_meter_*`
- **Tibber Pulse**: `sensor.tibber_*`

Wil je toch zelf via een automation pushen? De service `slimhuys.push_reading`
blijft beschikbaar voor maatwerk.

## Configuratie wijzigen

Settings → Devices & Services → SlimHuys → **Configure** → wissel van leverancier
(Tibber, Frank, Zonneplan, ANWB, Eneco, NextEnergy, Coolblue, easyEnergy, Powerpeers).

## Licentie

MIT — zie [LICENSE](LICENSE).
