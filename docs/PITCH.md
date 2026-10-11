# 3-minute pitch (numbers come from `backend/demo.py`)

**0:00 Problem.** "AQI is 238. That number doesn't tell a school what to do."
**0:20 Product.** BreatheOps joins air quality with the school's actual timetable and campus zones.
**0:40 Analyze.** 5 activities: 1 HIGH (Sports), 2 MEDIUM (Assembly, Bus), 2 LOW.
**1:10 Plan.** Move assembly to Main Building. Shorten sports 60 -> 30 min. Monitor bus departure. Keep class and lunch.
**1:40 Why.** Open one card: AQI 238 (Poor), source + age, current vs alternative dose (13.9 -> 4.2), confidence.
**2:00 Human approval.** Admin approves/modifies/rejects; Daily Safety Plan generated.
**2:20 Impact.** "100 -> 60.1: a 39.9% lower modeled exposure index under this scenario. Not a claim about pollution or health."
**2:40 AWS.** API Gateway, Lambda, DynamoDB, Bedrock, CloudWatch (show the console).
**2:50 Close.** "It doesn't just tell schools the air is unsafe. It helps them decide what to change because of it."

## Judge Q&A
- **Why not just an AQI app?** AQI is the input. We connect it to the timetable, zones, capacity and feasible actions.
- **Why AI?** Numbers are deterministic. AI ranks feasible options and explains trade-offs.
- **Can it hallucinate?** It only sees feasible candidates; output is schema- and feasibility-validated (tested: infeasible/unknown/missing actions are rejected) and falls back to rules.
- **Is the score validated?** No. It's a transparent prototype index for comparing scenarios; formula and assumptions are in docs/EXPOSURE_MODEL.md.
- **Data/AI outage?** Stale data lowers confidence (tested); no fabricated values; deterministic fallback keeps the workflow running.
- **Why would a school trust it?** Evidence + explanation + human approval; AI never controls the school.
- **Isn't it too big?** One user, one problem, one workflow.
