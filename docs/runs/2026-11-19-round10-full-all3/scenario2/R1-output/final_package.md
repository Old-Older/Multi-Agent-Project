# AI glasses scored 92.5 on an HKUST final exam paper — in a test run by an HKUST team

**Standfirst:** In a test run by an HKUST research team during final-exam week, a pair of off-the-shelf Rokid smart glasses running GPT-5.2 finished an undergraduate Computer Communication Networks paper in about 30 minutes and placed in the top five of a class of more than 100. The team is from the university's own Department of Electronic and Computer Engineering, and HKUST Engineering promoted the result on its official social channels — while the university's teaching centre already publishes guidance on exactly this problem.

*By the HKUST Campus Desk · For students and faculty · Reading time ~6 minutes*

---

## What happened

A research team led by **Prof. Jun Zhang** and **Prof. Zili Meng** of HKUST's Department of Electronic and Computer Engineering (ECE) ran a controlled test in which a test-taker wore **Rokid Glasses** — a commercially available pair of AI smart glasses — connected to OpenAI's **GPT-5.2** model, and worked through the undergraduate final examination paper for **Computer Communication Networks**.

The workflow was simple. The wearer looks down at the paper; the glasses' 12-megapixel camera photographs the page; the image travels glasses → phone → cloud to the model; the answer comes back the same way and appears on the in-lens display for the wearer to copy out.

The results, as published by the team:

| | Score (out of 100) |
|---|---|
| Rokid Glasses + GPT-5.2 | **92.5** |
| Highest-scoring student | 97.5 |
| Class average | 72 |

The glasses finished in about **30 minutes** and placed **in the top five of a class of more than 100 students**. The best student scored 97.5 — but took about three hours, according to *unwire.hk*; the comparison is not like-for-like, since the student wrote the whole paper by hand.

The team says it screened **12 commercial smart glasses** before choosing Rokid Glasses, because only a handful combine a camera, a display and an open SDK. It chose GPT-5.2 — which OpenAI released on 11 December — over rival models mainly for response speed. According to *unwire.hk*'s account of the team's results, the glasses took full marks on multiple-choice and single-page written questions; the marks lost came on multi-page questions where the camera could not see all the material at once, and on harder calculation questions. Battery fell from 100% to 58% over the 30 minutes.

**How we know this:** the team published its method and results publicly (authors Jiayang Xu, Yufan Zhuang, Zijie Li, Jun Zhang and Zili Meng; project repository `hkust-spark/xg-glass-release`). HKUST Engineering's official LinkedIn and Facebook posts (6 July 2026) describe "a controlled test conducted by Prof. Zili Meng and Prof. Jun Zhang of the Department of Electronic and Computer Engineering", in which the glasses "scored 92.5/100 in a Computer Communication Networks final, placing it in the top 5 out of over 100 students" — and the post itself raises "bigger questions about … the threats AI poses to academic integrity". *unwire.hk* reported the test on 13 January 2026, citing Sina Tech; DotDotNews followed on 13 July 2026.

**What we could not confirm:** we have not found a formal HKUST press release on the test, nor a peer-reviewed paper describing it; the team's public write-up is the primary account. HKUST has not announced any change to examination or invigilation rules in response. We have sought comment from ECE and CEI and will update this report if they respond.

## Why it matters

**1. The rulebook students live under is per-course, and it was not written for hardware.**
HKUST's guidance asks instructors to set a course-level generative-AI policy and communicate it to students, so the binding document for any assignment is that course's policy, not a single university-wide rule. That model assumes AI use is something a student *types into a chat window*. Smart glasses are not that: nothing is typed, nothing is pasted, and there is no text trail for a marker to compare against a template.

**2. HKUST's own teaching centre already treats this as a live threat.**
CEI publishes a dedicated page, "AI Smart Glasses and Academic Integrity", describing how such devices "allow users to secretly capture exam papers and receive real-time, in-lens AI an…", alongside an embedded video on how smart glasses can be used to cheat in proctored exams. The demonstration did not reveal a gap the university was unaware of — it measured the size of one.

**3. The integrity rules already cover the conduct, even if the technology is new.**
HKUST's Regulations for Student Academic Integrity define cheating as the "offer, receipt or use of unauthorized information or assistance in completing an assignment, test or examination", and breaches of the Rules for the Conduct of Examinations are misconduct in their own right. The regulations do not name any device — they prohibit "unauthorized information or assistance" — so on their face they apply to glasses as much as to phones. What the test changes is not the rule but the **detectability** of breaking it.

**4. Closed-book, invigilated written exams are the format most exposed.**
If a device can reach the top five of a class in half an hour, the discriminating power of a timed, memory-based paper falls. The pedagogically interesting question — the one CEI's own events now pose — is not "how do we catch it?" but "what is this assessment actually measuring?" Assessment designs that ask students to reason, build, defend or apply under conditions AI cannot shortcut are more robust than ones that reward recall under time pressure.

**5. Students are already heavy users, and the university supplies tools rather than banning them.**
A university-wide HKUST survey of **680 students** across the Hong Kong and Guangzhou campuses (launched in November 2023; published in the *Journal of Asian Public Policy*, Vol. 18 No. 2, pp. 352–376, online 28 December 2024) found significant ChatGPT use and a very high intention to keep using it, with students reporting positive effects on learning and career preparation, and variation by gender, level of study, age, discipline and origin. ITSO lists Microsoft Copilot Chat and Open WebUI — which it describes as an upgrade on the HKUST GenAI platform — as available to HKUST staff and students. The policy question is therefore not whether AI is in the exam room, but on what terms.

**6. HKUST is not alone, and its neighbours have drawn the line differently.**
CUHK's student guide states that, as a general principle, students are prohibited from using AI tools to complete assessed work **unless explicitly permitted**. HKU publishes university-wide core principles for AI in teaching and assessment. On the face of the published guidance, CUHK's default is the most restrictive of the three; HKUST's leaves the decision to each course — which puts more weight on every instructor's written policy being clear, and on exam-room practice keeping up.

## What it means for you

**If you are a student:** read the written AI policy on every course outline before you submit anything. "The course didn't say" is not a defence — the regulations treat unauthorized assistance and fabricated facts or references as misconduct regardless. Do not bring smart glasses, smart watches or any connected device into an invigilated exam unless the invigilator has explicitly allowed it. If you are unsure whether a tool is permitted for a specific piece of work, ask the instructor in writing and keep the reply.

**If you are faculty:** your written course policy is the operative rule, so make it specific about *devices* as well as chatbots, and about what is permitted in the exam room. CEI's assessment-design guidance and its smart-glasses module are the place to start. Consider whether any assessment you set can be completed by a camera, a network connection and a fast model in 30 minutes — and if it can, whether it is measuring what you intend.

## What we are still asking

- Does ECE or the University plan to change examination rules, invigilation or device screening for the coming term?
- Was the test reviewed by an ethics or examination committee, and were the student results used with consent?
- How many AI-related academic misconduct cases did HKUST handle in 2025–26? We could not find published case counts.
- Will the University publish guidance for instructors on device-based (as opposed to text-based) AI use?

*This report draws on the research team's published test write-up, HKUST Engineering's official social posts, HKUST CEI and ITSO policy pages, HKUST Academic Registry regulations, the Journal of Asian Public Policy survey (online 2024; Vol. 18 No. 2, 2025), and reporting by unwire.hk and DotDotNews. Figures are as published by the research team and have not been independently replicated.*

---

## 2. Social and newsletter copy

### 2a. X / social post (60 words)

> An HKUST ECE team tested Rokid smart glasses running GPT-5.2 on an undergraduate Computer Communication Networks final paper. Score: 92.5/100, top five of a class of 100+, in about 30 minutes. Class average 72; best student 97.5, in about three hours (unwire.hk; not like-for-like). No peer-reviewed paper on the test found. What should an exam measure?

*(56 words)*

### 2b. LinkedIn / Facebook post (120 words)

> A pair of off-the-shelf Rokid smart glasses running GPT-5.2 worked through an HKUST undergraduate final paper in Computer Communication Networks. It scored 92.5 out of 100 and placed in the top five of a class of more than 100 students, finishing in about 30 minutes. The class average was 72; the best student scored 97.5 but took about three hours, according to unwire.hk — not a like-for-like comparison. The test was run by Prof. Jun Zhang and Prof. Zili Meng of HKUST's Department of Electronic and Computer Engineering, who screened 12 commercial smart glasses before choosing Rokid. We found no peer-reviewed paper on the test, and HKUST has not announced any change to examination or invigilation rules. Full report below.

*(117 words)*

### 2c. Push notification (40 words)

> HKUST ECE test: Rokid smart glasses + GPT-5.2 scored 92.5/100 on a final exam paper, top five of 100+ students, in 30 minutes. No change to exam rules announced. Read what it means.

*(33 words)*

### 2d. Newsletter blurb (3 bullets)

- **What happened:** A team led by Prof. Jun Zhang and Prof. Zili Meng of HKUST's Department of Electronic and Computer Engineering tested Rokid Glasses running GPT-5.2 on the undergraduate Computer Communication Networks final paper. It scored 92.5/100 and placed in the top five of a class of more than 100, in about 30 minutes; the class average was 72 and the best student scored 97.5 in about three hours, according to unwire.hk — not a like-for-like comparison.
- **Why it matters:** HKUST's guidance asks instructors to set AI rules course by course, and assumes text-based tools, while CEI already publishes guidance on smart glasses and academic integrity. The test measures how hard device-based cheating is to detect, not whether the rules cover it.
- **What's next:** We found no peer-reviewed paper on the test, and HKUST has not announced any change to examination or invigilation rules. We have sought comment from ECE and CEI and will update our report if they respond.

---

## 3. Broadcast / audio script (90 seconds)

**[READER — calm, neutral]**

A pair of smart glasses has worked through a university final exam paper — and finished near the top of the class.

A team at HKUST's Department of Electronic and Computer Engineering, led by Professor Jun Zhang and Professor Zili Meng, tested Rokid Glasses running OpenAI's GPT-5.2 on the undergraduate Computer Communication Networks final paper.

The glasses scored 92.5 out of 100. That put them in the top five of a class of more than 100 students, and they finished in about 30 minutes. The class average was 72. The best student scored 97.5 — but took about three hours, according to unwire.hk, which is not a like-for-like comparison.

The team says it screened 12 commercial smart glasses before choosing Rokid, and picked GPT-5.2 mainly for response speed. Battery fell from 100 per cent to 58 per cent over the half hour.

HKUST Engineering promoted the result on its official LinkedIn and Facebook posts. But we have not found a peer-reviewed paper on the test, and the university has not announced any change to examination or invigilation rules. We have sought comment from the Department and the teaching centre, and will update this report if they respond.

What it changes, the report argues, is not the rule but how easy the rule is to enforce. HKUST's academic integrity regulations already treat unauthorized assistance as cheating, whatever the device. And the university's Center for Education Innovation already publishes guidance on smart glasses and academic integrity.

The open questions: will exam rules, invigilation or device screening change — and what should an exam measure?

**[END]**

*(approx. 90 seconds at broadcast pace)*

---

## 4. Chinese-language channel (Traditional Chinese, Hong Kong)

### 4a. 標題

**港科大團隊實測：智能眼鏡配GPT-5.2完成期末試卷 獲92.5分打入全班前五**

### 4b. 摘要（約100字）

港科大電子及計算機工程學系張軍與孟子立團隊，以市面有售的Rokid智能眼鏡配合GPT-5.2，完成本科「計算機通訊網絡」期末試卷，約30分鐘取得92.5分，在逾100名學生中位列前五；全班平均72分，最高分學生97.5分。本報未找到針對該測試的同行評審論文，校方亦未公布修改考試或監考規則。

*(約100字)*

---

## Editorial notes

- **Figures and attributions:** 92.5, 97.5, 72, top five of 100+, ~30 minutes, ~3 hours (attributed to *unwire.hk*), 12 glasses, 100%→58%, 680-student survey, 13 Jan 2026 (*unwire.hk*) and 13 Jul 2026 (DotDotNews), HKUST Engineering LinkedIn/Facebook posts 6 Jul 2026.
- **No official confirmation:** every channel keeps the statement that no formal HKUST press release or peer-reviewed paper on the test has been found, and the main article keeps the "What we are still asking" section.
- **No invented quotes:** the only quoted text is the CEI page wording, the academic integrity regulation wording and the HKUST Engineering social post, all as published.
- **Word counts (verified by script):** X post 56 words; LinkedIn/Facebook 119 words (target ≤120); push 32 words; Chinese summary 107 Chinese characters (target ~100).
- **Channel consistency pass:** every channel now says the test was run by an HKUST ECE team and that the glasses "worked through" the final paper (not "a real final exam"); "three hours" is attributed to *unwire.hk* and flagged as not like-for-like; the caveat is narrowed to "no peer-reviewed paper on the test"; the university line is narrowed to "has not announced any change to examination or invigilation rules"; the unverifiable "we have put those questions to ECE and CEI" is replaced by "we have sought comment from ECE and CEI and will update this report if they respond"; the Fall 2023–24 mandate is hedged to "HKUST's guidance asks instructors"; the survey date is "launched in November 2023"; the equity rationale and the "most permissive of the three" ranking are gone; "three-minute video" is removed; HKUST Engineering's LinkedIn/Facebook posts (6 Jul 2026) are cited and quoted. All figures are unchanged from the main article.
- **Corrections applied after fact-check:** headline and standfirst no longer call the test "a real final exam"; ECE attribution now sourced to the HKUST Engineering post; "three hours" attributed; test date context added; "no peer-reviewed paper" narrowed to "on the test"; "university has not issued a statement" narrowed to "has not announced any change to examination or invigilation rules"; the unverifiable "we have put those questions to ECE and CEI" replaced with "we have sought comment … and will update if they respond"; the Fall 2023–24 mandate hedged to "HKUST's guidance asks instructors"; "three-minute video" removed; "technology-neutral" rephrased; survey date corrected to "launched in November 2023"; the unsourced equity rationale removed; the "most permissive of the three" ranking replaced.
