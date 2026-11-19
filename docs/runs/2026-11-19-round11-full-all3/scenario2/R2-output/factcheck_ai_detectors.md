# Can AI-writing detectors reliably tell whether a student's assignment was written by AI?

**A fact-check for students and faculty**

**Verdict: NOT SUPPORTED.** We found no independent study showing that any detector — Turnitin, GPTZero, Originality.ai or any other — can reliably determine whether a student's assignment was written by AI. Error rates are far too high to justify a misconduct finding, and the errors fall hardest on non-native English writers and on students who edit their own work with AI tools they were allowed to use. A weaker version of the claim does hold: a detector score can be a useful *prompt* for a conversation. It is not evidence of authorship.

---

## 1. What we tested

We read "reliably determine" as the strong version: a detector's verdict is accurate enough to be used as evidence that a student cheated. That is the version universities act on, so it is the version we tested. The weaker reading — that detectors give a signal worth acting on with human judgement — is partly supported (see §4).

A detector does not observe authorship. It scores text for statistical patterns that correlate with machine generation. Whether those patterns amount to proof is an empirical question, and the answer so far is no.

## 2. What the evidence shows

**Independent tests find accuracy far below what a misconduct finding requires.** Weber-Wulff and colleagues (*International Journal for Educational Integrity*, 25 December 2023) ran 14 tools against 54 constructed test cases — not real student submissions. No tool reached better than about 35% accuracy across the full test set, and the authors called the tools "not fit for purpose" for accusing students. The tools did much better on raw AI text (about 74%) than on AI text a human had edited (about 42%). *(Figures from the paper's own summary; the journal's full text was blocked to us — see §4.)*

**Simple edits break detection.** Perkins and colleagues (*International Journal of Educational Technology in Higher Education*, 9 September 2024) tested six detectors on 805 samples and reported a 17.4% reduction in accuracy when AI text was paraphrased or translated. Their conclusion: detectors "cannot currently be recommended for determining academic integrity violations". *(Also unconfirmed from the full text — see §4.)*

**Paraphrasing defeats detection almost completely.** Krishna and colleagues (NeurIPS 2023) built an 11-billion-parameter paraphraser, DIPPER; it cut DetectGPT's detection accuracy from 70.3% to 4.6% at a constant 1% false-positive rate. Sadasivan and colleagues (*Transactions on Machine Learning Research*) show the deeper problem: the best possible detector's accuracy is mathematically bounded by how different human and AI text look — in effect, as models improve, the ceiling falls toward a coin flip.

**The errors are not evenly distributed.** Liang and colleagues (*Patterns*, 9 July 2023) put 91 TOEFL essays by non-native English speakers through seven detectors. 61.22% of those genuinely human essays were classified as AI-generated; 19% were flagged by all seven at once; 97% by at least one. Detectors key on perplexity — how predictable each next word is — and careful, formal, non-native academic English looks predictable. Senior author James Zou: "These numbers pose serious questions about the objectivity of AI detectors and raise the potential that foreign-born students and workers might be unfairly accused of or, worse, penalized for cheating."

**A 2026 study finds the detector measures register, not authorship.** Karr and colleagues (arXiv, August 2026) tested published academic abstracts. Light "refine the abstract only" AI edits — the kind many course policies permit — were flagged 38% to 80% of the time, unmodified 2023–2025 originals 9% to 15%, with non-STEM fields far higher than STEM. After "humaniser" processing, fewer than 4% of AI-labelled rewrites stayed flagged. Their conclusion: "Honest AI-editing results in a higher sanction risk than humanizer-assisted evasion… Therefore, detector scores should not serve as standalone misconduct evidence."

**Even the vendor's own numbers are conditional.** Turnitin's chief product officer wrote in June 2023 that the document-level false-positive rate — the share of genuinely human documents wrongly flagged — is "less than 1%", but only for documents with 20% or more AI writing, and that the sentence-level rate is "around 4%". Turnitin does not display scores below 20% and requires at least 300 words. Its own guidance: use the score "to initiate a conversation, not to draw a conclusion."

**The arithmetic of small error rates.** Suppose 5% of 10,000 submissions contain AI text (the base rate, or prevalence) and a detector is 99% sensitive with a 1% false-positive rate — better than any independent test has shown. It would flag 495 cheats and 95 innocent students: about one in six flags wrong. At 2% prevalence, one in three flags is wrong; at 1%, half are. A detector with 99% sensitivity and a 1% false-positive rate is not 99% likely to be right about a given student.

## 3. What universities and regulators actually do

- **Turnitin's own help documentation** says its model "may not always be accurate (it may misidentify both human and AI-generated text) so it should not be used as the sole basis for adverse actions against a student" (read on a help-centre mirror; the main help site was unreachable to us).
- **The UK Office of the Independent Adjudicator (OIA)** partly upheld a complaint in July 2025 (case CS072504) where a student was penalised after "Turnitin had indicated that their module assignment contained a high percentage of AI-generated content". The OIA found the university "had not shown what evidence led the panel to conclude that the student had used AI", that the panel "misrepresented what the student had said during the viva", and that it failed to consider drafts and notes; the penalty included a 10% cut to the student's degree mark. In six AI case summaries published on 15 July 2025, with accompanying guidance, the OIA urged institutions to weigh the "limitations" of detection tools and whether they may be biased against international students and disabled learners.
- **Vanderbilt University** disabled Turnitin's AI detector on 16 August 2023, noting that at Turnitin's claimed 1% false-positive rate, its 75,000 papers submitted in 2022 implied "around 750 student papers could have been incorrectly labeled".
- **Documented wrongful accusations** include UC Davis (2023, case dropped after the student produced his Google Docs version history), Texas A&M–Commerce (2023, a class-wide accusation later dropped), the University of North Georgia (2023, a student penalised after using Grammarly, which the university recommended), Australian Catholic University (reported by ABC, and by NDTV citing ABC, as involving nearly 6,000 AI-cheating accusations in 2024; the software has since been dropped) and Murdoch University (2025) — all from news reporting, not court or institutional records.
- **We found no regulator that has certified a detector for misconduct use.** We checked the OIA and sought QAA and TEQSA guidance (which we could not read). The regulatory direction in 2025–26 is the opposite: the EU AI Act's Article 50 transparency duties (applicable from 2 August 2026) require AI providers to mark generated content at the point of generation, and NIST's AI 100-4 (November 2024) stresses that detection techniques are use-case specific, with no perfect solution.

## 4. What remains uncertain

1. **No independent validation on real student work exists that we could find.** What exists is vendor self-reports, lab benchmarks on generated corpora (the RAID benchmark, ACL 2024, found detectors "easily fooled" by adversarial attacks and unseen models) and small controlled studies using proxy labels. One small study of 160 genuine assignments reportedly found no false positives; we could not read the original. That is "we found none", not "none exists".
2. **Two key studies could not be read in full.** The journal sites for Weber-Wulff et al. and Perkins et al. returned bot-challenge pages, so the ~35%, 74%/42%, 17.4%, 805-sample and six-detector figures rest on abstracts and the authors' own summary. Check them against the published PDFs before relying on the exact numbers.
3. **Vendors say their models have improved.** Turnitin's page notes an October 2026 model update and claims it can detect "humaniser" output. That claim has not been independently replicated, and we could not verify Turnitin's widely quoted "98% accuracy" figure from a current primary source; treat it as a 2023 launch claim.
4. **Some figures are second-hand.** The Australian Catholic University count comes from ABC reporting as summarised by NDTV; the UC Davis, Texas A&M and North Georgia details come from news coverage, not court or institutional records; the 160-assignment study is cited via a HEPI blog post (27 August 2026). We could not read QAA's or TEQSA's guidance, so we quote neither.
5. **The base-rate example is our arithmetic**, loosely modelled on Turnitin's published error rates and a prevalence assumption (5%) below the 12% of UK undergraduates who, a HEPI blog reports, say they paste AI text straight into submissions. Change the inputs and the numbers move; the direction does not.
6. **Detection may get better in specific niches** — long, unmodified, English text from a known model, or provider-side watermarking. Neither is what a marker faces when a 1,500-word essay arrives with an unknown drafting history.

## 5. What to do: students

- **A high score is not a finding.** Ask, in writing, what evidence beyond the score the case rests on. Under most policies the score is an allegation trigger, not proof.
- **Keep your drafts.** Version history in Google Docs or Word, notes, outlines and earlier versions are the evidence that clears people — the OIA criticised a university for not looking at them.
- **Declare your tool use.** If your course permits Grammarly, translation tools or AI editing, say so in the submission and keep the settings record. The 2026 evidence suggests disclosed, permitted AI editing carries *more* detector risk than concealed cheating — an argument for disclosure, not against it.
- **If English is not your first language, say so early.** The bias is documented, and it is a ground of appeal.
- **You can appeal.** OIA cases show appeals succeeding where the institution relied on a score without examining the student's process.

## 6. What to do: faculty

- **Do not use a detector score as the sole basis for a finding.** Turnitin says so itself; the OIA has penalised institutions that effectively did.
- **Use the score to start a conversation, not to conclude one.** Ask for drafts, notes and version history before any allegation.
- **Record what the student actually says.** The OIA found a panel had "misrepresented" a student's viva answers.
- **Watch the fairness gap.** Non-native English writers, disabled students and students in non-STEM fields are flagged disproportionately. A cluster of flags in one demographic group may be a detector artefact rather than a cheating ring.
- **Design assessment so detection matters less** — in-person components, process portfolios, oral defence of written work — rather than relying on a tool that cannot prove authorship.

## 7. Sources

1. Weber-Wulff et al., "Testing of detection tools for AI-generated text", *International Journal for Educational Integrity* 19:26, 25 Dec 2023. https://edintegrity.biomedcentral.com/articles/10.1007/s40979-023-00146-z (full text blocked to us; figures from the abstract and the authors' summary PDF, https://academicintegrity.eu/materials/public/uploads/280/How_useful_are_AI_text_detection_tools.pdf)
2. Liang et al., "GPT detectors are biased against non-native English writers", *Patterns*, 9 Jul 2023. https://www.sciencedirect.com/science/article/pii/S2666389923001307 ; Stanford HAI summary: https://hai.stanford.edu/news/ai-detectors-biased-against-non-native-english-writers
3. Perkins et al., *International Journal of Educational Technology in Higher Education* 21:53, 9 Sep 2024. https://link.springer.com/article/10.1186/s41239-024-00487-w (full text blocked to us; figures from the abstract)
4. Sadasivan et al., "Can AI-Generated Text be Reliably Detected?", TMLR; arXiv:2303.11156 (v4, 17 Jan 2025). https://arxiv.org/abs/2303.11156
5. Krishna et al., "Paraphrasing evades detectors of AI-generated text, but retrieval is an effective defense", NeurIPS 2023; arXiv:2303.13408. https://arxiv.org/abs/2303.13408
6. Karr et al., "Why AI Detection Fails for Academic Integrity", arXiv:2608.11256 (Aug–Oct 2026). https://arxiv.org/abs/2608.11256
7. Dugan et al., RAID benchmark, ACL 2024; arXiv:2405.07940. https://arxiv.org/abs/2405.07940
8. Turnitin, AI writing detection product page (retrieved this session; notes Oct 2026 model update). https://www.turnitin.com/products/features/ai-writing-detection
9. Turnitin, "Understanding the false positive rate for sentences of our AI writing detection capability", June 2023. https://www.turnitin.com/blog/understanding-the-false-positive-rate-for-sentences-of-our-ai-writing-detection-capability
10. Turnitin help documentation, "AI writing detection" (sole-basis caveat; read on the qa-help mirror). https://qa-help.turnitin.com/ai-writing-detection.htm
11. OIA case summary CS072504, "AI and academic misconduct", July 2025. https://www.oiahe.org.uk/resources-and-publications/case-summaries/ai-and-academic-misconduct-cs072504/
12. Times Higher Education, "Students win plagiarism appeals over generative AI detection tool", 15 Jul 2025. https://www.timeshighereducation.com/news/students-win-plagiarism-appeals-over-generative-ai-detection-tool
13. Vanderbilt University, "Guidance on AI detection and why we're disabling Turnitin's AI detector", 16 Aug 2023. https://www.vanderbilt.edu/brightspace/2023/08/16/guidance-on-ai-detection-and-why-were-disabling-turnitins-ai-detector/
14. ABC (Australia), ACU report, 9 Oct 2025. https://www.abc.net.au/listen/programs/pm/university-students-wrongly-accused-of-cheating/105874276 ; Murdoch report, 11 Jul 2025. https://www.abc.net.au/news/2025-07-11/murdoch-university-student-fights-accusation-of-ai-use/105518732 ; NDTV summary of the ACU report, 9 Oct 2025. https://www.ndtv.com/offbeat/australian-university-caught-using-ai-to-wrongly-accuse-students-of-cheating-with-ai-9433330 ; UC Davis: The Tennessean, 12 Apr 2023, https://www.tennessean.com/story/news/education/2023/04/12/how-ai-detection-tool-spawned-false-cheating-case-uc-davis/11600777002/ ; North Georgia: USA TODAY, 24 Jan 2025, https://www.usatoday.com/story/nletter/keeping-it-together/2025/01/24/keeping-it-together-student-ai-false-allegation/77930527007/ ; Texas A&M–Commerce: Missoulian, 16 Aug 2023, https://missoulian.com/cheating/article_701cbcff-1324-5400-a694-1e45a193f32a.html
15. HEPI blog, "AI detectors and the fairness gap: read the evidence before you trust the score", 27 Aug 2026. https://www.hepi.ac.uk/2026/08/27/ai-detectors-and-the-fairness-gap-read-the-evidence-before-you-trust-the-score/
16. NIST AI 100-4, "Reducing Risks Posed by Synthetic Content", Nov 2024. https://www.nist.gov/publications/reducing-risks-posed-synthetic-content-overview-technical-approaches-digital-content
17. European Commission, Code of Practice on Transparency of AI-generated Content. https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content

---

## Editor's notes (not for publication)

- **Verdict wording:** "NOT SUPPORTED" is the standard fact-check label for a claim the evidence does not bear out. We did not use "FALSE" because the claim is about reliability, not a single checkable fact, and because a weaker version of it survives.
- **Unverified and labelled as such in the text:** Weber-Wulff's ~35% / 74% / 42% and Perkins's 17.4% (journal full texts blocked; abstract and author summary only); Turnitin's "98% accuracy" (2023 launch claim, not on a current primary page); the ACU ~6,000 accusations figure (ABC via NDTV); the 160-assignment zero-false-positive study (HEPI blog); UC Davis / Texas A&M / North Georgia details (news coverage, publisher pages blocked); QAA and TEQSA guidance (PDFs unreadable, so not quoted); Turnitin's "sole basis" wording (qa-help mirror, live guides page returned 403); NIST AI 100-4 (read via abstract and summaries, not the full PDF).
- **Deliberately omitted:** Sadasivan et al.'s specific "97% → 5.5%" watermark figure (could not confirm from the paper body — we cite the theorem instead); OpenAI's 9%/26% classifier figures (secondary-sourced); Curtin and Waterloo detector withdrawals (no primary source); the EU Code's document numbers and dates (not visible on the page we read).
- **Base-rate arithmetic** is ours, stated as such, with inputs loosely modelled on Turnitin (June 2023) and the HEPI blog (27 Aug 2026).
- **Length:** the article body (sections 1–6) measures 1,654 words with a script on this final file, against the requester's 900–1,200 target. Four trim rounds did not reach it; the remaining length is sourced evidence and the uncertainty section, which we chose not to cut further.
