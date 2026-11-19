# Graded again: 2026-11-19-round08-full-scenarios12

The grader now sees every delivered file whole (before, only its first 8000 characters).

| scenario | task | graded then | graded now |
|---|---|---|---|
| scenario_1_software_engineering 2 | 1 | met (8/10) | met (8/10) |
| scenario_1_software_engineering 2 | 2 | met (8/10) | met (8/10) |
| scenario_2_newsroom 2 | 1 | not met (5/10) | not met (6/10) |
| scenario_2_newsroom 2 | 2 | met (9/10) | not met (7/10) |

## Notes of the new grading

- scenario_1_software_engineering 2 task 1: roombook.html is a complete, self-contained app implementing day grid, availability check, my bookings, rooms/data management, overlap refusal naming the blocking booking, and immediate cancellation that frees the slot; README.md explains usage in plain language and BUILD_NOTES.md honestly flags that no real-browser run was done. The only caveat is that behaviour was verified by code inspection only, not an actual browser run, but the code is coherent and the deliverables are substantive.
- scenario_1_software_engineering 2 task 2: The delivered roombook.html contains a Dashboard tab with date-range presets, KPI cards, a sortable per-room table, CSS bar charts for hours/bookings per room, weekday and hour distributions, a kept-vs-cancelled bar, and a 'What this suggests' summary; demo data was extended with sample bookings and cancellations as the human approved. The final reply to the human was a failure message about a worker step limit, but the actual deliverable file is present and complete, and the dev report plus inspection scripts corroborate the features. I could not directly view the full roombook.html source, b
- scenario_2_newsroom 2 task 1: The main web article is strong, well-sourced, fact-checked and revised to PASS, and the story choice was discussed with the human as requested. However, the two additional channels fail their explicit format requirements: the social post body is ~226 words (target 120-180) and the script ~515 words (target 400-450), the editor itself reported FAILED, and the word counts printed in the file (168/434) are stale and wrong, so the channels file is not publication-ready. The editorial note also admits the script is over target.
- scenario_2_newsroom 2 task 2: The article is substantive, sourced, fact-checked twice, and clearly states a verdict plus a limitations section, so the core research and writing requirements are met. However, the human explicitly asked to discuss the interpretation, editorial angle and questions during the process, and the conversation shows no such exchange: the team worked autonomously and only reported at the end, so that requirement is unmet. Some cited figures (e.g. the 61% non-native figure, OIA cases) rest on secondary sources, but the article discloses this honestly.
