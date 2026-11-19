# Evaluation report

- model provider: deepseek
- answers to questions: llm
- graded by a model: True
- runs per scenario: 1
- memory kept between runs: False
- early-stop nudges: on
- time budget per request (s): 900.0
- research limit per task: 28
- lead may hand in after (share of budget): 0.0
- wall time (s): 4184

## Summary

- Requests: **5/6 completed (83%)**
- Sub-tasks: 51/62 done (82%)
- Execution time per request: mean 693.87 s, median 721.7 s, max 967.22 s
- Questions the team asked the human: 6
- Graded by a model: 2/6 requests met (33%), mean score 6.17/10
- Failure modes: tool_error 1

## By scenario

| scenario | completed | sub-tasks | mean time (s) | graded passed | mean score |
|---|---|---|---|---|---|
| scenario_1_software_engineering 2 | 2/2 | 24/33 | 835.08 | 1/2 | 7.0 |
| scenario_2_newsroom 2 | 2/2 | 15/16 | 632.47 | 0/2 | 6.0 |
| scenario_3_securities_fund 2 | 1/2 | 12/13 | 614.06 | 1/2 | 5.5 |

## Every task

| scenario | run | task | lead | result | failure | seconds | sub-tasks | questions | files | graded |
|---|---|---|---|---|---|---|---|---|---|---|
| scenario_1_software_engineering 2 | 1 | 1. Scenario 1, Task 1: Build a Meeting Room Booking System | lead | completed | - | 702.947 | 17/23 | 1 | 3 | not met (6/10) |
| scenario_1_software_engineering 2 | 1 | 2. Scenario 1, Task 2: Add a Room Usage Dashboard | lead | completed | - | 967.222 | 7/10 | 1 | 6 | met (8/10) |
| scenario_2_newsroom 2 | 1 | 1. Scenario 2, Task 1: Produce a News Report | chief_editor | completed | - | 740.451 | 8/9 | 1 | 1 | not met (5/10) |
| scenario_2_newsroom 2 | 1 | 2. Scenario 2, Task 2: Fact-Check AI-Writing Detectors | chief_editor | completed | - | 524.495 | 7/7 | 1 | 2 | not met (7/10) |
| scenario_3_securities_fund 2 | 1 | 1. Scenario 3, Task 1: Develop a Simulated Investment Proposal | fund_manager | completed | - | 339.567 | 8/8 | 1 | 1 | met (9/10) |
| scenario_3_securities_fund 2 | 1 | 2. Scenario 3, Task 2: The Future of the Semiconductor Industry: An HTML Slide Presentation | fund_manager | FAILED | tool_error | 888.55 | 4/5 | 1 | 5 | not met (2/10) |

## Where the time went

The lead's own seconds are on the critical path (they add up to the request's time). The team columns add up every member, and members work at the same time, so they can exceed it.

| scenario | run | task | seconds | lead: model | lead: tools | lead: waiting for teammates | lead: waiting for the human | team: model calls | team: model s | team: tool s | web_search calls | web_search s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scenario_1_software_engineering 2 | 1 | 1 | 703 | 117 | 0 | 583 | 1 | 280 | 796 | 84 | 0 | 0 |
| scenario_1_software_engineering 2 | 1 | 2 | 967 | 140 | 0 | 826 | 1 | 307 | 1019 | 218 | 0 | 0 |
| scenario_2_newsroom 2 | 1 | 1 | 740 | 255 | 1 | 481 | 2 | 226 | 785 | 146 | 25 | 24 |
| scenario_2_newsroom 2 | 1 | 2 | 524 | 283 | 1 | 239 | 1 | 182 | 661 | 104 | 33 | 36 |
| scenario_3_securities_fund 2 | 1 | 1 | 340 | 128 | 0 | 208 | 2 | 118 | 433 | 76 | 27 | 26 |
| scenario_3_securities_fund 2 | 1 | 2 | 889 | 247 | 0 | 640 | 1 | 138 | 1066 | 190 | 39 | 43 |

## Where the lead's steps went

Each step is one model call of the lead. `tools` are its own tool calls (the second column lists them), `delegate` the steps that handed work to teammates, `push_*` the steps it was sent back (to have a deliverable reviewed, to check the requirements, to use more of the time, to check the loose ends), `final` the answer that was accepted.

| scenario | run | task | steps | delegate | tools | push_review | push_requirements | push_early | push_closing | format_error | final | the lead's own tool calls |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scenario_1_software_engineering 2 | 1 | 1 | 38 | 12 | 20 | 1 | 0 | 0 | 2 | 2 | 1 | read_file 11, list_files 6, edit_file 2, run_python 1, write_file 1 |
| scenario_1_software_engineering 2 | 1 | 2 | 42 | 8 | 31 | 1 | 0 | 0 | 0 | 1 | 1 | read_file 21, edit_file 9, list_files 2, write_file 1 |
| scenario_2_newsroom 2 | 1 | 1 | 60 | 7 | 50 | 0 | 1 | 0 | 0 | 1 | 1 | read_file 28, run_python 11, edit_file 7, write_file 4 |
| scenario_2_newsroom 2 | 1 | 2 | 60 | 3 | 52 | 0 | 2 | 0 | 0 | 2 | 1 | read_file 34, edit_file 26, run_python 13, write_file 8 |
| scenario_3_securities_fund 2 | 1 | 1 | 24 | 4 | 17 | 0 | 0 | 0 | 2 | 0 | 1 | read_file 17, write_file 3, run_python 3, edit_file 1, delete_file 1 |
| scenario_3_securities_fund 2 | 1 | 2 | 21 | 2 | 18 | 0 | 0 | 0 | 0 | 0 | 1 | read_file 14, write_file 7, run_python 1 |

## Notes

- scenario_1_software_engineering 2 run 1, task 1: The delivered files (README.md, QUICKSTART.md, CHANGELOG.md) are complete and describe a real app with server-side conflict checks, cancellation, my-bookings, CSV export and 16 passing tests, and the usage explanation is thorough. However, the actual application code (app.py, test_app.py) is not among the delivered files — the lead itself admits it could not collect them — so the requester was not actually shown the built system, only documentation about it. The 'show me what you have built' requirement is therefore not met from the evidence available.
- scenario_1_software_engineering 2 run 1, task 2: The delivered app.py contains a complete, working dashboard: /api/dashboard with range validation, per-room bookings/hours/utilisation/flags, weekday and hour-band aggregation, top dates, cancellation counts/rate/trend, summary and recommendation, plus an inline-SVG UI section with presets and room filter. Soft-delete cancellations with idempotent migration are implemented and test_app.py has 7 new DashboardTests alongside the 16 originals; README/QUICKSTART/CHANGELOG/DASHBOARD_HANDOVER document it. Minor gaps: no automated test for multi-day aggregation or the capped recommendation, no real-b
- scenario_2_newsroom 2 run 1, task 1: The package is substantive and covers the chosen GenAI rollout angle with a web article, social post, email blurb, channel plan and source list. However, the web article body is ~1,269 words against the 700-900 requirement (the file's own channel-plan line falsely claims ~800 words), and the fact-checker's re-check found 10 items still open (misattributed/spliced quote, unsupported March 2023 date, internal date contradiction, unlabelled Fung quote, usage-implying sentences), so the report is not publication-ready as claimed.
- scenario_2_newsroom 2 run 1, task 2: The article is substantive, well-sourced, covers the verdict, evidence, uncertainty and separate student/faculty guidance, and the blurb is delivered. The main shortfall is length: the article body is 1,654 words against the agreed 900-1,200 target, which the team itself reports as not met. The final trim was applied after the last reviewer pass, so the current wording of sections 1-6 was not re-confirmed, though the visible text reads coherently.
- scenario_3_securities_fund 2 run 1, task 1: The delivered document is complete and substantive: a five-sleeve allocation totalling HKD 1,000,000, per-sleeve rationale, a quantified risk section (drawdown, concentration, valuation, rates, FX, tax, behavioural), a plain-language introduction with a glossary, staged entry, checklist and dated sources. The client's defaults were confirmed via the clarifying question, and the risk/marketing reviews were closed out with quoted evidence. Minor residual issues (some unverified UCITS alternatives, secondary-source forward return estimate) are explicitly flagged in the document rather than hidden
- scenario_3_securities_fund 2 run 1, task 2: The research briefs, deck plan and risk review are substantive and well sourced, but the actual deliverable — the HTML slide deck — was never produced; the marketing agent's write_file calls failed and the final reply admits no HTML file exists. Planning documents and fact briefs are not a presentation, so the core request is unmet.
