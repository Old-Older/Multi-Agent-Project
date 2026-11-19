# Fact-check: Can AI-writing detectors "reliably determine" whether a student's assignment was written by AI?

**Verdict: Mostly False.** Detectors can produce a signal worth a second look. They cannot reliably determine authorship, and neither the leading vendor nor the universities that have examined them treat a detector score as proof. The claim fails on accuracy, on fairness, and on the fact that the people who sell the tools say so themselves.

*For students and faculty. Figures we could not confirm from a primary source are marked **[unverified]** and are not relied on. Sources and dates are listed at the end.*

---

## 1. The claim we tested

"Reliably determine" is the load-bearing phrase. We tested it in the sense that matters in a misconduct case or a grade penalty: **can a detector's output, on its own, establish that a student's submitted work was AI-generated, accurately and consistently enough to act on?** That is the standard the claim has to meet, because that is how detector scores are used in practice — as evidence against a named student. Judged against it, the claim is not supported.

## 2. The evidence

**Independent testing finds the tools neither accurate nor reliable.** Weber-Wulff and colleagues, in the *International Journal for Educational Integrity* (published online 25 December 2023), tested 12 publicly available tools plus two commercial systems (Turnitin and PlagiarismCheck) — one of the most comprehensive tests to date. Their conclusion, in the abstract: "the available detection tools are neither accurate nor reliable," with a bias toward classifying output as human-written — that is, they miss AI text. They also found that "content obfuscation techniques significantly worsen the performance of tools."

**Errors are not spread evenly — they fall hardest on non-native English writers.** Liang and colleagues at Stanford, in *Patterns* 4(7):100779 (published online 10 July 2023), found that detectors "consistently misclassify non-native English writing samples as AI-generated, whereas native writing samples are accurately identified," and advised "caution against their use in evaluative or educational settings." A widely repeated figure — that seven detectors wrongly flagged an average of 61% of genuine TOEFL essays — comes from a secondary summary, not the paper itself, and we could not confirm the sample size either, so we do not rely on it **[unverified]**. The direction of the finding, however, is the best-replicated result in this literature, and it is an equity problem, not a technical footnote.

**Detection is easy to defeat.** The same Stanford study found that "simple prompting strategies can not only mitigate this bias but also effectively bypass GPT detectors." Sadasivan and colleagues (arXiv, first posted March 2023; later published in TMLR) showed that "our recursive paraphrasing method can significantly reduce detection rates" while it "only slightly degrades text quality in many cases," and that watermarks can be spoofed. A detector that misses paraphrased AI text but flags careful human writing is unreliable in both directions at once.

**The vendor's own documentation says the score is not proof.** Turnitin's current AI-writing FAQ states that "the percentage on the AI writing indicator should not be used as the sole basis for action or a definitive grading measure." Its reports carry the warning "Percentage may not indicate academic misconduct. Review required." Turnitin does not display scores below 20% in its report, and students cannot see their own score at all. Turnitin has publicly claimed about 98% confidence with a roughly 1% false-positive rate for long-form English text; that figure was not on the FAQ page we read and we could not confirm it from Turnitin's current materials **[unverified]** — Stellenbosch University's library guide quotes it as Turnitin's stated position. Even taken at face value, 1% of a large marking load is a lot of wrongly accused students.

**Universities have reached the same conclusion.** Cambridge's guidance states that "detection tools offer no evidence to support investigations even when identifying possible use in a submitted example." Oxford's AI Competency Centre (16 February 2026) says the tools "cannot reliably determine whether AI has been used and therefore should not be used to inform academic decision-making." Vanderbilt disabled Turnitin's AI detector in August 2023, estimating that a 1% false-positive rate would have wrongly flagged about 750 of the 75,000 papers it submitted the previous year **[unverified — Vanderbilt's original post is offline; figure as reported by Business Insider, 22 September 2023]**. Stellenbosch University switched the Turnitin AI plugin off across the institution from 1 January 2026, after Senate approval, citing fairness, transparency and "undue trust in the plugin's veracity."

**And the errors have real costs.** In 2023 a UC Davis history student, William Quarterman, was given a failing grade and referred to judicial affairs after his exam was flagged; the case collapsed when he produced his Google Docs version history (USA TODAY, 12 April 2023). At Texas A&M-Commerce an instructor ran assignments through ChatGPT itself and withheld graduating students' grades and diplomas; the university reinstated the students' grades (May 2023) **[unverified — final resolution wording not confirmed]**. A University of North Georgia student received a zero and academic probation, spent six months in appeals and lost her scholarship after using Grammarly, which the university listed as a recommended tool (USA TODAY, 22 January 2025) **[unverified — whether the penalty was overturned]**. In each case what settled matters was **process evidence — drafts, version history, an audit trail — not a detector.**

## 3. What this means at HKUST

HKUST's "Policy for GenAI Integration in Teaching and Learning" (effective for courses from Fall 2023-24) leaves the permitted use of generative AI to each instructor, who must state the rules in writing for each course. That design puts the burden on clear, course-level rules rather than on after-the-fact detection. We found **no published HKUST statement endorsing AI-detector scores as evidence of misconduct**; students and staff should check their course outline and the university's academic-integrity procedures rather than assume a detector score settles anything. *(If HKUST has issued detector-specific guidance we have not seen, we will update this section.)*

## 4. What we are not saying

- **We are not saying detectors are useless.** A high score can be a legitimate reason to look more closely, ask a student about their process, or check drafts. That is a prompt for human judgement, not a finding.
- **We are not saying AI-assisted work is acceptable.** Rules on AI use are a separate question from whether detectors can enforce them. The evidence says the enforcement tool is weak, not that the rules are wrong.
- **We are not saying the science is settled in the other direction.** One reported study of 160 genuine student assignments found no false positives **[unverified — we could not identify or read it]**, and vendors retrain their models frequently, so 2023 results may not describe 2026 tools.

## 5. Remaining uncertainty

1. **No agreed accuracy figure exists.** Results swing with the tool, the model version, text length, language and the threshold chosen. Anyone quoting a single number — 98%, 1%, 61% — is quoting one setting of one tool on one sample.
2. **Most studies use short, prompted or exam-style texts**, not real coursework with drafts and revision history. Performance on authentic student writing is less well measured.
3. **The tools change faster than the literature.** Turnitin's current model was updated in October 2026; independent tests of the current version are not yet available.
4. **Vendor accuracy claims are hard to audit.** Turnitin's 98% / ~1% figures could not be confirmed from its current public pages, and its methodology is not open to independent replication.
5. **Usage data is thin.** We found no reliable survey of how many universities use detectors, so we make no claim about prevalence.
6. **Some institutional statements are recent or secondary.** Vanderbilt's original 2023 post is no longer online; UT Austin's and Northwestern's positions are known only through press reports and are not relied on here.

## 6. What students and faculty should do

**Students:** keep your drafts and version history; know your course's written AI rules; if you use tools such as grammar checkers, check whether they are permitted; and if you are accused, ask for the specific evidence and offer your process record.

**Faculty:** do not treat a detector score as a finding. Use it, if at all, to trigger a conversation, and decide on process evidence — drafts, in-class writing, oral defence, version history. State your AI rules in writing at the start of the course, and design assessment so that the process, not just the product, is visible.

---

## Sources

1. Weber-Wulff et al., "Testing of detection tools for AI-generated text," *International Journal for Educational Integrity* 19:26, online 25 Dec 2023 — https://doi.org/10.1007/s40979-023-00146-z
2. Liang et al., "GPT detectors are biased against non-native English writers," *Patterns* 4(7):100779, online 10 Jul 2023 — https://www.cell.com/patterns/fulltext/S2666-3899(23)00130-7 ; preprint arXiv:2304.02819 — https://arxiv.org/abs/2304.02819
3. Sadasivan et al., "Can AI-Generated Text be Reliably Detected?", arXiv:2303.11156 (v1 17 Mar 2023; TMLR) — https://arxiv.org/abs/2303.11156
4. Turnitin, "AI writing detection capabilities FAQs" (model update Oct 2026) — https://www.turnitin.com/products/features/ai-writing-detection
5. Turnitin/iThenticate guide, "AI writing detection in the classic report view," 26 Jun 2025 — https://guides.ithenticate.com/hc/en-us/articles/28458960923149-AI-writing-detection-in-the-classic-report-view
6. University of Cambridge, Blended Learning Service FAQ — https://blendedlearning.cam.ac.uk/artificial-intelligence-and-education/frequently-asked-questions-faq
7. Oxford AI Competency Centre, "The Question of AI Detection," 16 Feb 2026 — https://oerc.ox.ac.uk/ai-centre/ai-centre-news/the-question-of-ai-detection
8. Business Insider, "Some universities are ditching AI detection software…," 22 Sep 2023 (Vanderbilt, Northwestern, UT Austin) — https://www.businessinsider.com/universities-ditch-ai-detectors-over-fears-students-falsely-accused-cheating-2023-9
9. Stellenbosch University Library, "AI detection tools," updated 20 Oct 2025 (plugin disabled 1 Jan 2026) — https://libguides.sun.ac.za/c.php?g=1497969&p=11190989
10. USA TODAY, "Professors are using ChatGPT detector tools to accuse students of cheating…," 12 Apr 2023 (UC Davis) — https://www.tennessean.com/story/news/education/2023/04/12/how-ai-detection-tool-spawned-false-cheating-case-uc-davis/11600777002/
11. The Hill, "Professor attempts to fail students after falsely accusing them of using ChatGPT to cheat," 17 May 2023 (Texas A&M-Commerce) — https://thehill.com/homenews/education/4010647-professor-attempts-to-fail-students-after-falsely-accusing-them-of-using-chatgpt-to-cheat/
12. USA TODAY, "She lost her scholarship over an AI allegation…," 22 Jan 2025 (University of North Georgia) — https://www.detroitnews.com/story/life/health-wellness/2025/01/22/college-students-ai-allegations-mental-health/77723194007/
13. HKUST, "Policy for GenAI Integration in Teaching and Learning" (CEI; effective for courses from Fall 2023-24) — course-level rules set by instructors in writing; no HKUST detector policy located.
14. HEPI blog, A. Do, "AI detectors and the fairness gap," 27 Aug 2026 (secondary summary; used only for context) — https://www.hepi.ac.uk/2026/08/27/ai-detectors-and-the-fairness-gap-read-the-evidence-before-you-trust-the-score/

*Editorial note: this article was commissioned as a fact-check of a single claim. It is not legal or disciplinary advice; students facing an allegation should consult their institution's academic-integrity office.*
