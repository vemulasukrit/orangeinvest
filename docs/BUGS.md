# Observed defects and fixes

These are real defects found while developing this implementation. The tests were run and failed before the corresponding fixes. They are not hypothetical production incidents.

| Defect | Observed failure | Fix and regression |
|---|---|---|
| Relative date ignored | `test_next_week_slots_match_request` expected 2026-11-07 but received 2026-11-01. The first mock implementation treated every non-today request as tomorrow. | Provider search now resolves next week and supported weekday/week ranges in +05:30 local time. The date regression passes. |
| Invalid reusable time persisted | `test_memory_set_validates_time` submitted `99:99`; the snapshot had no error and stored the preference. | Memory validates HH:MM using the same clock bounds as request facts. Invalid preferences now return a user message and are not persisted. |
| Whitespace area accepted | `test_empty_area_rejected` submitted three spaces; the snapshot reported no error. | All textual facts reject whitespace-only input before state mutation. The regression passes. |

Additional review-driven fixes have dedicated tests: quoted price above budget, INR commas, cross-session booking visibility, receipt booking ID, preferred technician filtering, actual engine limits and mutated durable hold rejection. The first exact-provider-contract test also exposed an incompatible draft search signature; the public mock now uses the specified eight tool signatures.

## Presentation revision

Seven browser regressions now cover stable inspector positioning, preserved message DOM, receipt price, provider placement, progressive/reduced motion, failed-chat rollback, and long tablet review tickets. The original five tests failed against the previous UI; review reproduced the additional two defects before the fixes.

The original recording contained long silent holds and no voice track. It has been replaced with a real-browser recording synchronized to generated narration. The recorder has no target-duration padding. Voice generation and video encoding are optional development tooling, not runtime services.
