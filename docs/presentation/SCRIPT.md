# Presentation script

Speaker notes of `docs/presentation/index.html`, in one place for practice. The text is the same as the notes you get with the `N` key; `▶n` marks the n-th click (the → key) that reveals something on the screen. Times are estimates at about 140 words per minute.

## Time budget

| Part | Budget | Script (estimate) | Screens |
|---|---:|---:|---|
| Method | 120 s | 122 s | 1, 2, 3, 4, 5 |
| Mid-test | 60 s | 61 s | 6, 7 |
| In-class test | 60 s | 37 s | 8 |
| Reflection | 60 s | 38 s | 9 |

Whole script: 602 words, about 4.3 minutes of speaking, without pauses. In-class and Reflection have slack on purpose: you will be pointing at the screen, switching tabs and answering the clock.

## Method (120 s)

### Screen 1 · A model plus its harness

Target 20 s · script about 19 s · 45 words

Clicks: **▶1** Tools appear · **▶2** Private workspace with inbox · **▶3** Memory · **▶4** Limits, then the banner “Harness = everything around the model”

> Start with one team member. In the middle is the language model: text in, text out, nothing more. **▶1** Everything that lets it act is the harness around it: tools, **▶2** a private workspace with an inbox, **▶3** memory, **▶4** and limits. The harness is everything around the model.

### Screen 2 · The team comes from a file

Target 20 s · script about 22 s · 51 words

Clicks: **▶1** Four member windows appear from the role file · **▶2** The human request arrives · **▶3** One model call: chief_editor becomes LEAD, the others dim

> The team isn't hard-coded: each task comes with a role file, so a newsroom, a software team or a fund team is just a different file. **▶1** One member per role, each with its own window. **▶2** When a request arrives, **▶3** one model call picks who coordinates, and that member becomes the lead.

### Screen 3 · Delegation and parallel work

Target 35 s · script about 35 s · 82 words

Clicks: **▶1** Two envelopes fly through the Router to the reporter · **▶2** The reporter works on both jobs; their files appear · **▶3** The files are copied into the lead’s inbox · **▶4** The draft goes to the editor and the fact-checker; both start working

> This is the heart of the design. **▶1** The lead sends two research jobs in one reply. They go through the Router, our mail room, and arrive together, so the reporter **▶2** works on both in parallel. **▶3** Each job ends with a file. Workspaces are private, so the Router copies the files into the lead's inbox. **▶4** Then the lead sends the draft to the editor and the fact-checker at once. Every handover goes through the Router, so limits and bookkeeping live in plain code.

### Screen 4 · Three checks and a clock

Target 30 s · script about 31 s · 73 words

Clicks: **▶1** Coverage check · **▶2** Review gate · **▶3** Requirements report · **▶4** Time-budget bar; the marker moves from 0 s to 270 s

> Done is not the model's call. Three checks, all in code. **▶1** Before work goes out, every requirement needs an owner, otherwise the plan is held back once. **▶2** During work, a reviewer says pass or fail, and a file gets at most three rounds. **▶3** Before handing in, the lead reports each requirement as met or not met. **▶4** And underneath, the clock: 270 seconds is a soft budget, with reminders and a short grace period.

### Screen 5 · Delivery

Target 15 s · script about 15 s · 35 words

Clicks: **▶1** The listed files are copied into output/ · **▶2** The reply and the files reach the human · **▶3** The “not met” list appears

> **▶1** The Router copies only the listed files into one output folder. **▶2** The human gets the reply and the files. **▶3** And the reply says what was not met, here the student quotes and the word count.

## Mid-test (60 s)

### Screen 6 · The journey: each leap and its design choice

Target 30 s · script about 31 s · 72 words

Clicks: **▶1** Markers 1 and 2 · **▶2** Markers 3 and 4 · **▶3** Markers 5 and 6

> We ran about sixteen rounds, and each big jump has one design choice behind it. **▶1** Higher step limits and a forced wrap-up made requests finish; parallel research cut the time from 1,500 seconds to 200. **▶2** Requirements and batch review gave six out of six; the fast setup scored higher in half the time. **▶3** File handling and a repeat guard stopped lost files and wasted calls. Single runs, so read them as direction.

### Screen 7 · Final mid-test results

Target 30 s · script about 30 s · 69 words

Clicks: **▶1** The three numbers · **▶2** The score chart · **▶3** The newsroom banner

> **▶1** Our final mid-test run: all six requests finished, mean score 7.67 out of ten, about 4.8 minutes per request. **▶2** Teal is this run, grey is the average of earlier runs. **▶3** The newsroom is our weak spot: it misses hard targets like word counts. A coverage check before delegation gave six out of six against five out of six, one run each, so it is a direction, not a proof.

## In-class test (60 s)

### Screen 8 · Live run

Target 60 s · script about 37 s · 86 words

Clicks: **▶1** No clicks: click “Open workspace ↗” and switch to the new tab

> Now the in-class test. The team started on this task a few minutes ago, so this is live. The button opens our workspace in a new tab. Point out who the lead is, what it handed out, what each member is doing right now, and the clock. That is the picture from the method screens, happening for real. If it has not finished, show what exists so far, and say the final files appear under Results when it ends. Then come back here for the reflection.

## Reflection (60 s)

### Screen 9 · What worked, what did not, what we learned

Target 60 s · script about 38 s · 89 words

Clicks: **▶1** What worked · **▶2** What did not · **▶3** What we learned

> Three takeaways. **▶1** What worked: agents decide and plain code enforces. Parallel research made a request about eight times faster, and the system reports what it did not manage. **▶2** What did not: review loops never converge, word counts keep overshooting, and the time budget is soft. **▶3** What we learned: measure all scenarios before fixing, because review time looked guilty but was not. Check the requirements when work is handed out. And repeat each experiment several times, since the same task scored 8 once and 1 the next time. Thank you.

## Practice tips

- Press `Home` before you start (the page remembers where you were), `T` for the timer, `N` for the notes.
- If you run long in Method, drop the sentence about the clock on screen 4 and the closing sentence on screen 3.
- On the live screen, say one sentence about what you can see right now (who leads, what each member is doing), not a tour.
- Numbers are single runs graded by a model: say “direction”, not “proof”.
