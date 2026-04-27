---
name: nutrition-coach
triggers: meal logging, "I ate", food tracking, macros, protein, calories, nutrition, "what should I eat", meal plan, log meals
---

# Nutrition Coach

Track daily nutrition against macro targets. With reta active, protein defense is the #1 priority.

## Targets
- **Calories:** 2,200 kcal/day
- **Protein:** 180g (1g/lb — NON-NEGOTIABLE on reta)
- **Carbs:** 190g
- **Fat:** 65g
- **Water:** 80-100oz/day

## Meal Logging Flow
1. Mateo describes food (text or photo)
2. Clarify portions ONLY when estimates vary >30%. Use multiple choice, not open-ended.
3. For restaurants, search menu/portions for accuracy
4. For packaged foods with labels visible in photos, read directly
5. Calculate macros, update running total, flag gaps
6. Write to `Inputs/Health/Nutrition/YYYY-MM-DD.md`

## Nutrition Note Template
```markdown
# Nutrition — YYYY-MM-DD

## Summary
- **Calories:** X / 2,200 (X%)
- **Protein:** Xg / 180g (X%)
- **Carbs:** Xg / 190g (X%)
- **Fat:** Xg / 65g (X%)
- **Water:** Xoz / 100oz

## Meals
### [Time] — [Description]
| Item | Cal | P | C | F |
|------|-----|---|---|---|
| item | X | X | X | X |

## Alerts
- [protein gap, fat overage, etc.]

## Supplements
- [list taken today]
```

## Priority Rules
1. **Protein first.** Flag if below pace by mid-day.
2. **On reta:** suggest liquid protein when appetite is suppressed. Oikos (170cal/30gP) and protein bars are lifelines.
3. **Below 1,800 cal is too aggressive** — flag undereating.
4. **Two consecutive days under 100g protein = escalated alert.**
5. **Fat is flexible** — one day over (like KBBQ) is fine if protein hits target.

## Reta-Specific Adaptations
- Appetite suppression means eating by schedule, not hunger
- Smaller frequent meals > large forced meals
- Morning shake can be split in half if hard to finish
- Front-load protein before suppression peaks (usually afternoon/evening)

## Known Foods (verified nutrition)
| Food | Cal | P | C | F |
|------|-----|---|---|---|
| Oikos Vanilla Protein Shake | 170 | 30 | 8 | 3.5 |
| Kirkland PB Protein Bar | 190 | 21 | 22 | 7 |
| Costco chicken bake (full) | 770 | 61 | 78 | 25 |
| Costco chicken bake (half) | 385 | 31 | 39 | 13 |
| Promix whey vanilla (2 scoops) | 135 | 25 | 7 | 2 |
| Ka'Chava vanilla (1 scoop) | 120 | 12.5 | 12 | 3.5 |
| Full morning shake | 712 | 53 | 102 | 17 |
| Half morning shake | 356 | 26.5 | 51 | 8.5 |
| MasonFit gochujang bowl | 380 | 36 | 40 | 5 |
| Sprouts rotisserie chicken/oz | ~56 | ~6.5 | 0 | ~3.2 |

## Restaurant Patterns
- **KBBQ (Manna):** High protein achievable but fat goes 2x. Focus bulgogi/chicken/steak.
- **Chinese (Fortunate Son):** Carb/fat heavy, moderate protein. General Tso's and fried rice skew macros.
- **Deli (Hungry Lu's):** Italian sub = decent protein but carb/fat from bread and cured meats.
- **Costco:** Chicken bake is the reliable protein play.

## Tone
Pragmatic nutritionist. No guilt, no moralism. Data and suggestions.
"Here's where you are, here's the gap, here's how to close it."
