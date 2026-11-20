# Fact-check: Can AI-writing detectors "reliably determine" whether a student's assignment was written by AI?

**Verdict: FALSE.** AI-writing detectors cannot reliably determine whether a university assignment was written by AI, and they are not safe as the sole or decisive basis for a misconduct finding. The best-known detectors have failed their own tests, error rates vary widely, and false positives fall hardest on non-native English writers. A score can be one signal worth a conversation; it is not proof of authorship.

*For students and faculty. Published [date — to be filled before publication]. Sources are numbered at the end; figures we could not confirm are marked.*

---

## What the claim says

"Reliably determine" is doing a lot of work. We tested the strong reading — that a detector's output can be used as sole or decisive evidence of AI authorship in an academic-misconduct decision — because that is how scores are used in practice. On that reading the claim fails. On a weaker reading — that a score can be *one* signal worth a conversation — the evidence supports only heavy qualification.

## The evidence against

**1. The best-known detectors have failed their own tests.** OpenAI withdrew its AI Text Classifier on 20 July 2023, citing a "low rate of accuracy"; in OpenAI's own evaluation it caught only **26%** of AI-written texts while flagging **9%** of human-written ones as AI [1]. A 2023 test of 12 free tools plus Turnitin and PlagiarismCheck in the *International Journal for Educational Integrity* found them "neither accurate nor reliable", with the dominant error being AI text passed off as human: on average across the 14 tools, unmodified ChatGPT text was caught **74%** of the time, but once a human had edited it, only **42%** [2].

**2. False positives fall hardest on non-native English writers.** In a *Patterns* study (2023), seven widely used detectors were run on 91 TOEFL essays by non-native English speakers; the detectors misclassified more than half as AI-generated — an average false-positive rate of **61%** across the seven, the study's own figure — while essays by native speakers were almost never flagged [3]. The mechanism is mundane: simpler vocabulary and grammar lower the "perplexity" detectors read as human. Note the sample is essays, not university assignments.

**3. Detection can be defeated, and it can be spoofed.** Sadasivan and colleagues (TMLR) show that recursive paraphrasing sharply cuts detection rates with little loss of text quality, and that the best achievable accuracy is mathematically bounded by how different human and AI text look [4]. As models improve, that gap narrows. Their own framing matters: detectors can work under their specific settings — the impossibility result is about an adversary who is trying, and a detector that does not know which model produced the text.

**4. The arithmetic of a 1% false-positive rate is brutal.** Suppose 1% of submissions are AI-written and a detector has a 1% false-positive rate with 90% sensitivity. Of 10,000 submissions, 189 get flagged — and **99 of them, about 52%, are human-written**. At 50% sensitivity, two-thirds of flags are wrong. *(Our own calculation, with the inputs named; we found no peer-reviewed estimate of how much university work is AI-written — itself part of the problem.)*

**5. Institutions and the vendor say the same thing.** Turnitin says its AI indicator is not a determination of misconduct and should not be used on its own as the basis for action [7]. In 2023 it conceded that its false-positive rate was higher than the under-1% it had claimed at launch, and it marks scores for documents with less than 20% AI writing as less reliable [8]. Waterloo told instructors to treat results cautiously [9]; Pitt's Teaching Center says it does not endorse AI-detection tools [10]. Documented wrongful accusations include a UC Davis student cleared only by his Google Docs version history [12], a Texas A&M instructor who failed a class after treating ChatGPT's answers as proof, and a University of North Georgia student who said she lost her scholarship after an AI accusation [11].
## Where detectors do work — narrowly

Detection is not impossible in every setting. Watermarking — a signature the AI provider embeds at generation time — can be tested at very low false-positive rates (Kirchenbauer et al. design for 1 in 100,000) and is detectable after light paraphrasing of texts of roughly 800+ tokens, though it degrades under stronger paraphrasing and on short texts [5]; Google's SynthID-Text (*Nature*, 2024) is deployed at scale [6]. But that works only when the model is known, the watermark is present, and the text is long and largely unedited — none of which holds for a typical assignment submitted as a Word file.
## What this means for faculty

- **Do not treat a score as evidence.** A detector percentage is not proof of authorship and should not be the basis of a misconduct finding.
- **Ask for the process, not the product.** Drafts, version history, outlines and a short viva are far stronger evidence than any classifier.
- **Design assessment that resists the question** — in-class writing, oral components, personalised tasks — and require students to disclose AI use where permitted.
- **If you must use a detector, treat a flag as a reason to look, not to accuse.**
## What this means for students

- **A flag is not a finding.** Ask what evidence beyond the score exists; you are entitled to know the basis of an allegation.
- **Keep your trail.** Drafts, cloud version history and notes are the evidence that has cleared wrongly accused students.
- **Know your institution's policy** on permitted AI use — the rules that bind you are your institution's, not a detector's.
## What we could not confirm

- The exact per-detector false-positive rates in the *Patterns* TOEFL study (we report the study's own 61% average; we could not open the full text to check each detector).
- Turnitin's current stated false-positive rate; its published figure is the 2023 launch claim of under 1%, later conceded to be optimistic.
- The final outcomes of the Texas A&M and North Georgia cases.
- Any peer-reviewed estimate of the base rate of AI-written university assignments — the key unknown in the arithmetic above. We found none; that is not proof none exists.
- No HKUST- or CUHK-specific statement on detectors was verified for this article.

## Sources

1. OpenAI, "New AI classifier for indicating AI-written text", 31 Jan 2023 (withdrawn 20 Jul 2023). https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/
2. Weber-Wulff et al., "Testing of detection tools for AI-generated text", *International Journal for Educational Integrity* 19:26, 25 Dec 2023. https://doi.org/10.1007/s40979-023-00146-z
3. Liang et al., "GPT detectors are biased against non-native English writers", *Patterns* 4(7):100779, 2023. https://doi.org/10.1016/j.patter.2023.100779
4. Sadasivan et al., "Can AI-Generated Text be Reliably Detected?", TMLR; arXiv:2303.11156. https://arxiv.org/abs/2303.11156
5. Kirchenbauer et al., "On the Reliability of Watermarks for Large Language Models", arXiv:2306.04634. https://arxiv.org/abs/2306.04634
6. Dathathri et al., "Scalable watermarking for identifying large language model outputs" (SynthID-Text), *Nature* 634, 2024. https://doi.org/10.1038/s41586-024-08025-4
7. Turnitin, "AI writing detection capabilities FAQs". https://www.turnitin.com/products/features/ai-writing-detection
8. Inside Higher Ed, "Turnitin's AI Detector: Higher-Than-Expected False Positives", 1 Jun 2023. https://www.insidehighered.com/news/quick-takes/2023/06/01/turnitins-ai-detector-higher-expected-false-positives
9. University of Waterloo, AVPA memo on Turnitin and AI, 10 Apr 2023. https://uwaterloo.ca/associate-vice-president-academic/news/avpa-memo-turnitin-and-ai
10. University Times (Pitt), "Teaching Center doesn't endorse AI detectors", Jun 2023. https://utimes.pitt.edu/news/teaching-center-doesn-t
11. USA TODAY, "She lost her scholarship over an AI allegation", 22 Jan 2025. https://www.usatoday.com/story/life/health-wellness/2025/01/22/college-students-ai-allegations-mental-health/77723194007/
12. The Register-Guard / USA TODAY network, UC Davis false-accusation case, 12 Apr 2023. https://www.registerguard.com/story/news/education/2023/04/12/how-ai-detection-tool-spawned-false-cheating-case-uc-davis/11600777002/
