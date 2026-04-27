---
name: sleep-analysis
triggers: sleep review, "how did I sleep", sleep score, sleep stages, deep sleep, REM, sleep debt, bedtime consistency
---

# Sleep Analysis

Apple Health sleep stage data analysis. Sleep is the #1 lever for recovery.

## Data Source
Apple Health sleepAnalysis samples: Awake, REM, Core (light), Deep

## Nightly Breakdown
1. Total time in bed, total asleep, sleep efficiency
2. Stage durations: Deep, REM, Core, Awake (minutes + % of total)
3. Benchmarks:
   - Total: target 7h 30m
   - Deep: target 1h+ (13-23% healthy)
   - REM: target 1.5h+ (20-25% healthy)
   - Efficiency: target >90%
   - Wake episodes: <3 good, >5 concerning

## Sleep Debt
- Nightly debt = 7.5h - actual_sleep
- Track 7-day cumulative
- >3h accumulated = flag
- >5h = strong recommendation for catch-up

## Observed Patterns
- April 17: 6h 20m, 99% efficiency — short but excellent quality (deep 1h18m, REM 2h22m)
- April 20: ~8h 43m, 87% efficiency — long but choppy, 5 wake-ups (53min awake), post-alcohol
- Alcohol consistently degrades sleep efficiency even when duration is adequate
- Mateo tends to go to bed late (~11:45pm-12am) and wake early (~6am)

## Weekly Report Includes
- Avg duration, avg efficiency, avg deep/REM %
- Sleep debt accumulated
- Bedtime consistency (std deviation)
- Trend vs previous week

## Correlations to Surface
- Low HRV morning → check preceding night's sleep
- High strain day → did sleep increase to compensate?
- Late bedtimes (after midnight) → correlate with next-day recovery
- Weight fluctuations → sleep deprivation causes water retention
