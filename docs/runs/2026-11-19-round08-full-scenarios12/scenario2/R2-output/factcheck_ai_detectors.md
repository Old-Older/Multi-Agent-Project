# Fact-check: Can AI-writing detectors reliably tell whether a student's assignment was written by AI?

**Verdict: FALSE as stated.** The claim that AI-writing detectors *can reliably determine* whether a university student's assignment was written by AI is not supported by the published evidence we reviewed. Detectors can sometimes flag text, but in the studies we reviewed they miss paraphrased AI text, flag human writing — especially by non-native English speakers — and the vendors' own headline accuracy figures come with conditions that undercut "reliable".

**Audience:** students and faculty. **Final — fact-checked (v1 FAIL, 11 items; v2 PASS on all 11).**

---

## 1. What the claim means, and how we judged it

"Reliably determine" is a high bar. In assessment terms it would mean: a detector that, on a real student's assignment, gives an answer a university could act on — low false positives (human work wrongly flagged) and low false negatives (AI work that passes), across students, subjects and languages. We tested the claim against that standard, not against "detectors are useless". They are not useless; they are not reliable enough to decide a misconduct question on their own.

## 2. The evidence against "reliable"

**Detectors flag human writing by non-native English speakers.** Liang et al. (*Patterns*, 10 July 2023) tested several widely used GPT detectors on writing by native and non-native English writers and reported that the detectors *"consistently misclassify non-native English writing samples as AI-generated, whereas native writing samples are accurately identified."* The authors *"caution against their use in evaluative or educational settings, particularly when they may inadvertently penalize or exclude non-native English speakers from the global discourse."* (Abstract read directly; the paper's numeric false-positive rates were not obtained — see §5.)

**Simple edits defeat detection.** Sadasivan et al. (TMLR; arXiv v1 March 2023) show a "recursive paraphrasing attack" — a tool any student can run — *"can significantly reduce detection rates"* on passages of approximately 300 tokens while *"only slightly degrad[ing] text quality in many cases."* They also show the reverse: human text can be made to look AI-generated. Their theoretical result is the deeper point — the best possible detector's accuracy is bounded by how different human and AI text are, and that gap is narrowing.

**Independent tests find low accuracy and a bias toward "human".** Weber-Wulff et al. (*International Journal for Educational Integrity*, 25 December 2023) tested 12 free tools plus Turnitin and PlagiarismCheck. The authors wrote in the abstract: *"the available detection tools are neither accurate nor reliable and have a main bias towards classifying the output as human-written rather than detecting AI-generated text. Furthermore, content obfuscation techniques significantly worsen the performance of tools."*

**Recall collapses on rephrased text.** A 2024 study (*International Journal for Educational Integrity*, 20 May 2024) tested six detectors on 50 real articles, 50 ChatGPT-written articles and 50 articles rephrased with the Wordtune tool. Its abstract reports that *"Turnitin showed a 0% misclassification rate for human-written articles, although it only identified 30% of AI-rephrased articles"*, while Originality.ai detected 100% of the ChatGPT-generated and AI-rephrased texts and ZeroGPT 96% and 88% respectively. The spread between tools is itself the story: results depend heavily on which tool and which text.

**The vendors' own numbers are conditional — and self-reported.** Turnitin's chief product officer wrote on 23 May 2023: *"Since our release, we discovered real-world use is yielding different results from our lab."* The company reported that *"in cases where we detect less than 20% of AI writing in a document, there is a higher incidence of false positives"* — the regime most student work sits in. Its *"less than 1%"* document false-positive rate applies only to documents with **over 20% AI writing**; it also reported a **sentence-level false-positive rate of ~4%** — *"the specific sentence we are highlighting may be human-written 4 times for every 100 highlighted sentences"* — and stated: *"We cannot mitigate the risk of false positives completely given the nature of AI writing and analysis."* All vendor accuracy figures in this article are the companies' own, on test sets they chose; we found no independent audit of any of them.

OpenAI launched its own classifier on 31 January 2023 and, as of 20 July 2023, it was *"no longer available due to its low rate of accuracy."* In OpenAI's own testing it correctly identified 26% of AI-written text and incorrectly labelled human-written text as AI-written 9% of the time, and OpenAI warned it *"should not be used as a primary decision-making tool."*

## 3. What this means in practice

- **A detector score is evidence of a signal, not proof of authorship.** A "likely AI" flag can be produced by a human writing in a second language, by heavy editing, or by a template; a "human" result can be produced by AI text that has been paraphrased.
- **Institutions are moving away from sole reliance.** As of 5 August 2026, Inside Higher Ed reported that Yale, Vanderbilt, Johns Hopkins and Indiana had policies banning or discouraging detector scores as the *sole* evidence of alleged cheating, and that at least a dozen universities including Northwestern, Georgetown and NYU had disabled Turnitin's AI detection. England's Office for Students said in November 2026 that AI has made it *"close to impossible"* to assess coursework and pushed universities toward in-person assessment instead.
- **Cases have gone wrong.** England and Wales's Office of the Independent Adjudicator published case summaries in July 2025 on AI-misconduct accusations; as reported by HEPI, three of the four involved international or second-language students, and in one the university *"had never considered whether Turnitin's AI detection might perform less reliably for non-native English speakers."* We did not read the OIA summaries themselves.
- **For students:** a detector flag is not a finding of misconduct. Ask what evidence beyond the score exists, and check your course syllabus for the rule you are actually being judged against.
- **For faculty:** the practical alternative is assessment design — process evidence, drafts, in-class work, oral defence — rather than detector scores.

## 4. What would change our verdict

Evidence that a detector, independently validated on real student assignments across languages and subjects, achieves both high sensitivity and a false-positive rate low enough to act on. We found no such validation.

## 5. What we could not confirm

- **No peer-reviewed study on real student assignments** (as opposed to synthetic or rephrased text) was verified in our research, and none on non-English or mixed-language student writing. This is the biggest limitation on our verdict: it rests on abstract-level and synthetic-text evidence.
- **Liang et al.'s numeric false-positive rates** (the widely cited "over 61% of non-native essays flagged" figure) come from a secondary source (HEPI, 20 July 2026); the paper's full text was not read, so we do not print a percentage attributed to it.
- **Weber-Wulff et al.'s full text was not read** — we quote its abstract only.
- **No individual wrongful-accusation case was verified from a primary source**; the OIA material above is second-hand via HEPI.
- **Turnitin's 2024–2025 model changes** and any newer published accuracy figure could not be verified.
- **Hong Kong-specific data** on detector use in universities (UGC, CUHK) was snippet-only and is not reported as a finding.
- **No HKUST-specific detector dispute** was confirmed in our research.

## Sources

1. Liang, Yuksekgonul, Mao, Wu & Zou, "GPT detectors are biased against non-native English writers", *Patterns* 4(7):100779, 10 Jul 2023 — https://arxiv.org/abs/2304.02819 ; DOI 10.1016/j.patter.2023.100779
2. Sadasivan, Kumar, Balasubramanian, Wang & Feizi, "Can AI-Generated Text be Reliably Detected?", TMLR — https://arxiv.org/abs/2303.11156
3. Weber-Wulff et al., "Testing of detection tools for AI-generated text", *Int. J. Educational Integrity* 19:26, 25 Dec 2023 — https://link.springer.com/article/10.1007/s40979-023-00146-z
4. Detector study, *Int. J. Educational Integrity*, 20 May 2024 (title not verified; cited by journal, date and URL) — https://link.springer.com/article/10.1007/s40979-024-00155-6
5. Turnitin CPO blog, 23 May 2023 (archived) — https://web.archive.org/web/20240118235040/https://www.turnitin.com/blog/ai-writing-detection-update-from-turnitins-chief-product-officer
6. OpenAI, "New AI classifier for indicating AI-written text", 31 Jan 2023 (archived) — https://web.archive.org/web/20240508142915/https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text
7. Inside Higher Ed, "AI detectors are out. New approaches are in", 5 Aug 2026 — https://www.insidehighered.com/news/tech-innovation/artificial-intelligence/2026/08/05/ai-detectors-are-out-new-approaches-are
8. The Guardian, OfS on AI and coursework assessment, 11 Nov 2026 — https://www.theguardian.com/education/2026/nov/11/ai-close-to-impossible-assess-university-coursework-regulator
9. HEPI, "Catching the wrong students", 20 Jul 2026 — https://www.hepi.ac.uk/2026/07/20/catching-the-wrong-students-ai-detection-international-students-and-the-fairness-crisis-in-uk-universities/
10. Inside Higher Ed, Turnitin false positives, 1 Jun 2023 — https://www.insidehighered.com/news/quick-takes/2023/06/01/turnitins-ai-detector-higher-expected-false-positives
