# gta6-trophy-rarity-forecast-01-v3

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/kiroroai/gta6-trophy-rarity-forecast-01-v3/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/kiroroai/gta6-trophy-rarity-forecast-01-v3/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Refresh-inversion forecaster v3: it forecasts each GTA VI PS5 trophy's
Exophase earn rate at the target by inverting how a refresh recomputes
the page. On a frozen page, rates × players_tracked are exact earner
counts; a refresh divides grown counts by the new pool, so the entry
recovers the counts, grows them per trophy (global growth factor ×
tier/secret velocity, with count jitter and a wide robust mixture), and
divides by the refreshed pool — mixing over a possible second refresh
for later targets. On a moving page, each trophy gets a
duration-weighted logit trend over the last 24 hours of distinct pages,
its slope shrunk toward its tier's precision-weighted mean slope,
damped, and extrapolated to the answer-effective time (the target minus
the expected refresh staleness). A trophy earned by the whole pool stays
at 100%.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

Entered on [make.fun](https://make.fun/bounty/gta6-trophy-rarity-forecast-01) for the bounty [gta6-trophy-rarity-forecast-01](https://make.fun/bounty/gta6-trophy-rarity-forecast-01).
