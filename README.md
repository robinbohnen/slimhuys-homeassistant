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

## P1-data: push of pull

Tijdens **Add Integration** kies je in stap 3 één van drie P1-modi:

| Modus | Richting | Wanneer kiezen |
|---|---|---|
| **none** | geen P1 | Je wilt alleen de prijs-sensors |
| **push** | HA → SlimHuys | Je hebt een DSMR-meter via USB / HomeWizard / Tibber Pulse en wilt die data delen met SlimHuys |
| **pull** | SlimHuys → HA | Je hebt een SlimHuys-P1-bridge die rechtstreeks aan SlimHuys is gekoppeld |

De wizard kiest een sane default op basis van je SlimHuys-account
(`has_p1_meter`-veld uit `/v1/me`): is er al een P1-bridge gepaird, dan
default'ed pull, anders push.

### Push-modus — DSMR-data naar SlimHuys

In stap 4 detecteert de integratie automatisch mogelijke DSMR-sensors
en biedt dropdowns aan:

- Cumulatief verbruik (kWh)
- Cumulatieve teruglevering (kWh)
- Huidig vermogen (W of kW — wordt automatisch geconverteerd)

Plus een push-interval (1–300 seconden, default 30s). Sinds v0.3.0 is de
push **event-driven**: zodra je DSMR-meter een nieuwe waarde publiceert
gaat 'ie meteen naar SlimHuys (met throttling op de configured interval).

**Optionele velden** (3-fase + gas) verschijnen automatisch onderin de
wizard als ze in je HA-instance bestaan.

> **1-seconde push** is sinds v0.2.0 mogelijk. DSMR-meters publiceren naturally
> elke ~1s; de SlimHuys-API rate-limit is 600/min/key (= 10/s) dus 1Hz uit één
> instance is comfortabel.

Werkt out-of-the-box met DSMR Slimme meter (USB), HomeWizard P1, en Tibber Pulse.

Wil je toch zelf via een automation pushen? De service `slimhuys.push_reading`
blijft beschikbaar voor maatwerk.

### Pull-modus — SlimHuys-P1 als bron voor HA

Heb je een P1-meter rechtstreeks aan SlimHuys gekoppeld (cellular, wifi)?
Dan vult pull-modus je HA met live entiteiten — geen DSMR-USB nodig.

Connectie: **Server-Sent Events** op `/v1/me/usage/live-events` — sub-seconde
latency, native HTTP, automatische reconnect met exponential backoff. Bij
SSE-uitval valt de integratie terug op `GET /v1/me/usage/current` (5s-poll).

Aangemaakte sensors:

| Entity | Eenheid | Device-class |
|---|---|---|
| `sensor.actief_vermogen` | W | power |
| `sensor.teruglevering_vermogen` | W | power |
| `sensor.verbruik_totaal` | kWh (total_increasing) | energy |
| `sensor.teruglevering_totaal` | kWh (total_increasing) | energy |
| `sensor.spanning_l1/l2/l3` | V | voltage (L2/L3 als diagnostic) |
| `sensor.stroom_l1/l2/l3` | A | current (L2/L3 als diagnostic) |
| `sensor.vermogen_l1/l2/l3` | W (signed) | power |
| `sensor.gas_totaal` | m³ (total_increasing) | gas |
| `sensor.water_totaal` | L native, m³ display (total_increasing) | water |

3-fase entities worden alleen aangemaakt voor fasen die de meter rapporteert
(via een eenmalige `/current`-probe bij setup). 1-fase huishoudens krijgen
geen permanent-unavailable L2/L3-entities.

## Configuratie wijzigen

Settings → Devices & Services → SlimHuys → **Configure** → wissel van leverancier
(Tibber, Frank, Zonneplan, ANWB, Eneco, NextEnergy, Coolblue, easyEnergy, Powerpeers).

## Licentie

MIT — zie [LICENSE](LICENSE).
