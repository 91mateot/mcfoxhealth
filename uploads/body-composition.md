---
name: body-composition
triggers: weight, body fat, muscle mass, body comp, scale, weigh-in, weight trend, body recomposition, Withings
---

# Body Composition

Track weight and body composition from Withings scale in context of recomp goal + reta protocol.

## MCP: withings
- Pull weight, body fat %, muscle mass, water %

## Current Stats (April 2026)
- Weight: 169 lbs (76.8 kg)
- Body fat: 13.6%
- Lean mass: ~146 lbs
- Goal: sub-12% BF, maintain lean mass
- Reta active: expect accelerated fat loss starting week 1

## Analysis Rules
- Compare 7-day avg to previous 7-day avg (never react to single weigh-in)
- Daily fluctuation of 2-4 lbs is normal (water, sodium, glycogen)
- Healthy loss pace: 0.5-1.0 lb/week at his BF level
- **With reta: alert if losing >1.5 lbs/week** (increase calories to protect muscle)

## Lean Mass Preservation (critical with reta)
- Weight dropping + BF% dropping = ideal recomp
- Weight dropping + BF% stable/rising = losing muscle → increase protein, reduce deficit
- Weight stable + BF% dropping = perfect recomp

## Report Format
Append to `Inputs/Health/Body/weight-log.md`:
```markdown
## Week of YYYY-MM-DD
- Avg weight: XXX.X lbs (prev: XXX.X, delta: +/-X.X)
- Latest BF%: XX.X% (prev: XX.X%)
- Estimated lean mass: XXX lbs
- Assessment: [On track / Plateau / Too fast — adjust]
- Reta dose: X of 4
```

## Trend History
- Jan 2026: 170 lbs
- Feb-Mar 2026: 168 lbs (dipped)
- April 2026: 169 lbs (slight rebound, plateaued)
- Reta started April 21 — expect movement within 1-2 weeks
