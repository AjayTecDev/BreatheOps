# Modeled Exposure Index (prototype) - FINAL v1

> A **relative scenario-comparison** index. Not an absolute exposure, clinical or epidemiological measure.
> Pipeline: CPCB AQI -> environmental severity -> scenario modifiers -> modeled dose -> index vs baseline.

## 1. Inputs
| Input | Source |
|---|---|
| AQI (and PM2.5 if available) | trusted snapshot (LIVE or REPLAY), see Data Trust |
| indoor / outdoor | the activity's campus zone |
| intensity: sedentary / light / vigorous | per activity (assembly = sedentary, bus queue = light, sports = vigorous) |
| minutes | activity duration (original, or as modified by an action) |

## 2. Formula
`dose = severity(AQI) x location_factor x intensity_factor x minutes`   (unit: weighted minutes)

| Constant | Value | Basis |
|---|---|---|
| severity(AQI) | piecewise-linear through (0,0) (50,.05) (100,.15) (200,.35) (300,.65) (400,.85) (500,1) | AQI breakpoints = CPCB National AQI categories; **severity values are our assumption** |
| location_factor | outdoor 1.0, indoor 0.3 | **assumption**: indoor/outdoor ratio varies with ventilation and filtration |
| intensity_factor | sedentary 1.0, light 1.3, vigorous 2.0 | **assumption**: breathing-rate proxy |
| risk bands | LOW < 10, MEDIUM 10-20, HIGH >= 20 weighted-min | chosen for readability; they label activities, they do not drive the index |

All constants live in `ModelParams` (`exposure.py`) and are covered by tests.

## 3. Normalization
Day total = sum of activity doses. **Scenario index = 100 x (proposed total / current total)**; the current schedule is always 100.
"X% lower" = 100 - index. Always phrase it as *"X% lower modeled exposure index under this scenario."*

## 4. Worked example (canonical demo, AQI 238 "Poor", severity 0.464)
| Activity | Current | Proposed |
|---|---|---|
| Assembly 30 min outdoor, sedentary | 0.464 x 1.0 x 1.0 x 30 = 13.9 | moved to Main Building: x 0.3 = 4.2 |
| Mathematics 45 min indoor | 6.3 | 6.3 |
| Sports 60 min outdoor, vigorous | 0.464 x 1.0 x 2.0 x 60 = 55.7 | shortened to 30 min = 27.8 |
| Lunch 45 min indoor | 6.3 | 6.3 |
| Bus 20 min outdoor, light | 12.1 | 12.1 (MONITOR does not change the model) |
| **Total** | **94.2** | **56.6** -> index 100 -> 60.1 (39.9% lower) |

The exact output is frozen in `canonical_demo.json`; tests fail if code or docs drift from it.

## 5. Edge cases (all tested)
- AQI < 0 clamps to 0, AQI > 500 clamps to 500 (severity 1.0).
- Baseline total of 0 (e.g. AQI 0 or everything indoors): index 100, 0% lower, no changes recommended.
- Indoor activities: never offered changes. LOW risk: always KEEP ("good air -> no unnecessary changes").
- MONITOR and KEEP have zero modeled change by design; RESCHEDULE is offered only if a supplied forecast gives a >= 10% lower dose.
- Short outdoor activities (< 30 min) cannot be SHORTENED; shortening halves duration (floor 15 min, 5-min rounding).
- Missing/invalid data: no snapshot -> no analysis is produced (never a guess).

## 6. Limitations (say these out loud)
- Single AQI value for the whole day unless an hourly forecast is supplied.
- No pollutant-specific weighting (PM2.5 vs ozone), no wind/ventilation/filtration, no individual health factors.
- Derived AQI from an instantaneous PM2.5 reading is not a CPCB 24h-average AQI (flagged `DERIVED`).
- Constants are assumptions; sensitivity to them is large, so use the index to compare scenarios, never to claim health outcomes.
