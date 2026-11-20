# Fact-check: Can AI-writing detectors reliably tell whether a student's assignment was written by AI?

**Verdict: Not supported as stated.** Detectors give a useful statistical signal in aggregate and as one input among several, but we found no published independent study showing they are reliable enough, paper by paper, to decide on their own whether an individual student used AI — and the error rates that matter most in a university setting are large.

*For students and faculty. Published 2026. Figures marked [unverified] could not be confirmed against the full published text.*

---

## How we read the claim

The claim is about **per-paper reliability**: that a detector's output on one assignment reliably establishes whether that assignment was AI-written. That is much stronger than "detectors pick up AI text more often than chance across a large corpus," and it is the version that matters when a mark or a misconduct finding hangs on the result.

## The evidence for detectors

- **Best independent result.** Perkins et al. (2024, *Journal of Academic Ethics*, peer-reviewed) had 15 academic markers assess 22 GPT-4 submissions written with prompts designed to reduce detectability. Turnitin's tool identified **91%** of the AI submissions, and software beat human markers working alone. [unverified — from a search snippet of the paper, not the full text]
- **Vendor claims.** According to a Northern Illinois University compilation (Dec 2024), Turnitin advertises a document-level false-positive rate under 1% (about 4% at sentence level, revised in 2023), GPTZero claims 99% accuracy, Originality.ai 98.2% and Copyleaks 99.12%. These are measured on vendor-chosen benchmarks, not on real student assignments. [unverified]

## The evidence against

- **Non-native English writers are flagged at very high rates.** Liang et al. (2023, *Patterns*, peer-reviewed) ran seven off-the-shelf detectors on 91 human-written TOEFL essays. **61.3%** were classified as AI-generated (some sources give 61.2%), against about **5.1%** of the native-speaker comparison set. The authors blame lower "perplexity" in learner English: narrower vocabulary and simpler grammar look statistically like machine output. [unverified]
- **Editing and paraphrasing break detection.** Weber-Wulff et al. (2023, *International Journal for Educational Integrity*, peer-reviewed) tested 12 tools (some accounts say 14; unresolved) on constructed cases. Unedited AI text scored about **74%**; the same text after human editing about **42%**. A Syracuse University summary puts the false-negative rate at close to **40–50%** once AI text was reworded by a person or a paraphrasing tool. The paper's conclusion, as quoted in a submission to the Australian Parliament, is that no tool "functions well enough for use in education." [unverified — figures from search snippets of the article and secondary summaries; not read from the PDF]
- **Sadasivan et al. (2023, University of Maryland, arXiv preprint)** argue theoretically that a capable paraphraser can drive a detector's true-positive rate toward zero while keeping false positives low, and that watermarking can be removed; their experiments show detection rates falling sharply after paraphrasing. They argue the failure is structural, not a tuning problem. [preprint — not peer-reviewed; figures unverified]

- **The best-known detector was withdrawn for being unreliable.** OpenAI's own classifier, launched January 2023, caught **26%** of AI text while wrongly flagging human text **9%** of the time on OpenAI's own challenge set [vendor self-reported]. OpenAI's page now reads: "As of July 20, 2023, the AI classifier is no longer available due to its low rate of accuracy." On that challenge-set rate, a class of 100 would see about nine students wrongly flagged.
- **Real cases.** In 2023 UC Davis history student William Quarterman was accused of cheating after his exam answers were run through detectors; he was later cleared. At Texas A&M University–Commerce an instructor failed a class of seniors, and diplomas were withheld, after using ChatGPT itself as a "detector" — not a commercial score, but a reminder of how thin the evidence behind such accusations can be.

## What the tool-makers and universities say

- **Turnitin's help page:** the model "may not always be accurate (it may misidentify both human and AI-generated text) so it should not be used as the sole basis for adverse actions against a student."

- **Turnitin's April 2023 FAQ** said it would "likely miss up to 15% of text written by AI," while claiming a less than 1% false-positive rate — the same FAQ behind the vendor figures above.

- **University of Melbourne** Deputy Vice-Chancellor Gregor Kennedy: "Turnitin produces an AI writing report, which alone is not a sufficient basis for an allegation of misconduct… The University requires staff to consider additional evidence before making [an allegation]." [unverified — via news.com.au, 12 Aug 2026]
- **In Australia, the NSW Education Standards Authority** — which regulates schools, not universities — changed its rules in 2025 to stop schools relying on detection software when deciding whether a student cheated, "because these tools are not always reliable." [unverified]

- **HKUST** has no single university-wide allow-or-prohibit rule. Instructors set the course-level generative-AI policy and must communicate it to students in writing; the binding rule is the one in your course outline. [unverified — compiled from HKUST pages by a third-party tracker; confirm against your own course outline]

## What this means in practice

**For faculty.** A detector score is a lead, not a finding. If a paper is flagged, look for process evidence — drafts, version history, in-class writing, an oral check on the argument — before raising anything with a student, and say in your course outline how you will use detectors, if at all. Given Liang et al., be especially careful with second-language writers, flagged at roughly twelve times the rate of the native-speaker comparison set. Several universities are reported to be moving toward assessment design — in-class components, oral defence, staged drafts — instead of detection. [unverified]

**For students.** A high AI score is not proof you cheated, and a low one is not proof you did not. Keep your drafts and notes; they settle these cases. If you are accused, ask what evidence beyond a detector score exists, and ask for the institution's procedure. Know your course's rule: at HKUST, and at many universities, it is set course by course.

## What we could not confirm

- The exact figures for Weber-Wulff et al. (74% / 42%), Liang et al. (61.3% / 5.1%) and Perkins et al. (91%) come from search snippets and secondary summaries; the full texts could not be opened during this check. They are consistent across sources but should be read against the PDFs before republication.

- No independent, peer-reviewed, large-scale test of Turnitin's current detector on real student assignments was found; its <1% and 4% figures are vendor-reported.

- No study measuring detector accuracy on **mixed** human-AI text at scale was found.

- Turnitin's reported change to how it surfaces scores below 20% is second-hand (University World News, 21 May 2026) and is not relied on above.

- We found no primary statement from Cambridge, Oxford or Yale on detector reliability and have not cited any.

## Sources

1. Weber-Wulff, D. et al. (2023). "Testing of detection tools for AI-generated text." *International Journal for Educational Integrity* 19:26, 25 Dec 2023. https://doi.org/10.1007/s40979-023-00146-z
2. Liang, W., Yuksekgonul, M., Mao, Y., Wu, E., Zou, J. (2023). "GPT detectors are biased against non-native English writers." *Patterns* 4(7):100779, 9 Jul 2023. https://www.sciencedirect.com/science/article/pii/S2666389923001307
3. Sadasivan, V. S. et al. (2023). "Can AI-Generated Text be Reliably Detected?" arXiv:2303.11156, 17 Mar 2023 (v4 Jan 2025). https://arxiv.org/abs/2303.11156
4. Perkins, M., Roe, J., Postma, D., McGaughran, J., Hickerson, D. (2024). "Detection of GPT-4 Generated Text in Higher Education: Combining Academic Judgement and Software to Identify Generative AI Tool Misuse." *Journal of Academic Ethics* 22(1):89–113. https://doi.org/10.1007/s10805-023-09492-6
5. OpenAI (2023). "New AI classifier for indicating AI-written text," 31 Jan 2023; withdrawn 20 Jul 2023. https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/ — withdrawal also reported by Ars Technica, 25 Jul 2023: https://arstechnica.com/information-technology/2023/07/openai-discontinues-its-ai-writing-detector-due-to-low-rate-of-accuracy/
6. Turnitin. "AI Writing Detection" help page. https://qa-help.turnitin.com/ai-writing-detection.htm
7. Turnitin (2023). "FAQs for Turnitin's AI writing detection capabilities," April 2023. https://storage.pardot.com/45292/1680208469nVzzEbDg/AI_writing_FAQS_Apr23_US_G.pdf
8. Northern Illinois University CITL (2024). "AI detectors: An ethical minefield," 11–12 Dec 2024 (page date and URL path differ by one day). https://citl.news.niu.edu/2024/12/12/ai-detectors-an-ethical-minefield/
9. The Register-Guard (2023). "How AI detection tool spawned false cheating case at UC Davis," 12 Apr 2023. https://www.registerguard.com/story/news/education/2023/04/12/how-ai-detection-tool-spawned-false-cheating-case-uc-davis/11600777002/
10. AI Incident Database, report 2993 (Texas A&M University–Commerce, 2023). https://incidentdatabase.ai/reports/2993/
11. news.com.au (12 Aug 2026). "Major universities abandon AI detection tools amid fears of false accusations" (quoting Gregor Kennedy, University of Melbourne). https://www.news.com.au/finance/work/careers/major-universities-abandon-ai-detection-tools-amid-fears-of-false-accusations/news-story/274e3059f4637964ace3b229b4e67b72
12. The Conversation (22 Sep 2026). "Unis and schools are moving away from AI-detection software. They should stop using it altogether." (NSW NESA rule change). https://theconversation.com/unis-and-schools-are-moving-away-from-ai-detection-software-they-should-stop-using-it-altogether-292593
13. University AI Policy Tracker, HKUST entry (rev. 22 Oct 2026) — third-party compilation, not an HKUST page. https://eduaipolicy.org/fr/changes/uq-hkust-michigan-v6-r4-20261022/hkust
14. University World News (21 May 2026). "Higher education, stop policing AI. Know your students." https://www.universityworldnews.com/post-mobile.php?story=20260522093324632
