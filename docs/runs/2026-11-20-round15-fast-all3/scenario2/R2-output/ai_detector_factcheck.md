# Fact-check: Can AI-writing detectors reliably tell whether a student's assignment was written by AI?

**Verdict: Not supported.** The evidence does not show that AI-writing detectors can reliably determine whether a university student's assignment was written by AI. Detectors perform well on average on clean, unedited, whole-model output, but they are not reliable enough to decide individual cases — which is exactly what the claim asserts. Universities should not treat a detector score as proof of misconduct, and students should not be told that a score settles the question either.

*Audience: students and faculty. Published by the newsroom. All figures are quoted from the source named; where a figure is our own arithmetic, it is labelled.*

---

## 1. What the claim says — and the version we tested

Read literally, "reliably determine" could mean two very different things:

- **The weak version:** on average, across many texts, detectors do better than chance at separating AI-generated from human-written prose.
- **The strong version:** a detector's verdict on *one* student's assignment is accurate and consistent enough to be relied on — including as evidence in a misconduct case.

We tested the **strong version**, because that is the version that matters in a university: it is the version that decides whether a student is failed, loses a scholarship, or has a finding on their record. The weak version is partly supported (see §2); the strong version is not (§3–§5).

---

## 2. What the evidence does support

- **On clean, unedited, whole-model text, the best commercial detectors can be quite accurate.** Turnitin, which launched its AI-writing indicator in April 2023, reported detecting ChatGPT/GPT-3.0-written content 97% of the time with a false-positive rate below 1% at announcement (THE Journal, 12 Feb 2023; Aalto University, 8 May 2023). These are vendor self-reports, not independent tests.
- **Detectors are much better than chance on pure human vs pure AI text.** A 2026 inter-rater study of nine commercial detectors found 96–97% pairwise agreement on texts that were entirely human or entirely AI (TextPulse Research working paper, 18–19 Aug 2026, DOI 10.5281/zenodo.22003419 — not peer-reviewed; see §6).
- **Watermarking works in principle.** Google's SynthID-Text, published in *Nature* (634:818–823, 23 Oct 2024), embeds a detectable signal in model output and was validated on nearly 20 million Gemini responses with no measured quality loss. This is the one approach that could, in future, give a genuine provenance check rather than a statistical guess.

That is the honest case *for* detectors. It is not enough for the claim.

---

## 3. Why the strong version fails: four lines of evidence

### (a) OpenAI withdrew its own detector, citing low accuracy

OpenAI launched an AI-text classifier on 31 January 2023 and withdrew it in July 2023. Its own evaluation found it correctly identified **26% of AI-written text** and wrongly labelled **9% of human-written text** as AI (OpenAI, https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/). *Unverified: this page returned an access error to our research tools. The 26%/9% figures are corroborated by the page's search snippet and by contemporaneous news coverage, but the exact withdrawal date, OpenAI's stated reason and its warning against using the tool as a primary basis for decisions could not be read from the page itself and are not quoted here. Check in a browser before republication.*

### (b) False positives fall hardest on non-native English writers

The best-known study on this point tested seven widely used detectors on **91 TOEFL essays** written by non-native English speakers. The detectors were near-perfect on essays by US-born eighth-graders, but classified **61.22% of the TOEFL essays as AI-generated**; **all seven detectors unanimously flagged 18 of the 91 essays (19%)**, and **89 of the 91 (97%) were flagged by at least one** (Liang, Yuksekgonul, Mao, Wu & Zou, "GPT detectors are biased against non-native English writers", *Patterns* 4(7):100779, 10 July 2023, DOI 10.1016/j.patter.2023.100779; Stanford HAI release, 15 May 2023).

The mechanism is not malice but method: detectors score text on *perplexity* — how surprising the word choices are — and careful, plain, grammatically simple non-native writing looks "predictable", and therefore "AI-like", to the model. As the authors put it, "these numbers pose serious questions about the objectivity of AI detectors and raise the potential that foreign-born students and workers might be unfairly accused of or, worse, penalized for cheating" (Stanford HAI, 15 May 2023).

### (c) The base rate makes individual verdicts unreliable even at a "1% false positive rate"

This is the argument that matters most for faculty, and it is arithmetic, not opinion. Take OpenAI's own figures — a 9% false-positive rate and a 26% true-positive rate — and apply them to 1,000 honest-looking submissions in which 20 students actually used AI:

- about **90 honest students are wrongly flagged** (9% of 980);
- about **5 of the 20 AI users are caught** (26% of 20);
- so of roughly 95 flags, only about 5 are correct: **about 19 of every 20 flags are wrong** (precision ≈ 5%).

*(Our calculation from OpenAI's published rates; it is an illustration of the base-rate problem, not a measurement of any particular tool.)*

Turnitin's own figures make the same point at a smaller scale. Turnitin says its document-level false-positive rate is below 1% for documents with 20% or more AI writing, but that its **sentence-level false-positive rate is around 4%**, and that **54% of those false-positive sentences sit right next to genuine AI writing** (Turnitin, 13 June 2023). Vanderbilt University, which disabled Turnitin's AI detector on 16 August 2023, did the multiplication: a 1% rate across the **75,000 papers** submitted at Vanderbilt in 2022 would mean "around **750 student papers** could have been incorrectly labeled" (Vanderbilt Brightspace, 16 Aug 2023). Turnitin's own published advice to instructors is to "use the information to initiate a conversation, not to draw a conclusion" (Turnitin, 13 June 2023).

### (d) Detectors are easy to evade, and they disagree with each other on mixed text

- **Paraphrasing collapses detection.** An 11-billion-parameter paraphraser (DIPPER) dropped DetectGPT's detection accuracy from **70.3% to 4.6%** at a fixed 1% false-positive rate, and also evaded watermarking, GPTZero and OpenAI's classifier "without appreciably modifying the input semantics" (Krishna et al., NeurIPS 2023, arXiv:2303.13408).
- **Simple character-level tricks break commercial tools.** In the RAID benchmark — over 6 million generations, 11 models, 11 adversarial attacks — Originality.ai's accuracy at a 5% false-positive operating point fell from **85.0% to 9.3%** under a homoglyph attack (Dugan et al., ACL 2024, arXiv:2405.07940).
- **On mixed human–AI text, detectors stop agreeing.** In the 2026 nine-detector study, agreement on hybrid texts fell to chance (mean pairwise kappa 0.02); 28 of 30 hybrid texts received both a "human" and an "AI" verdict from different tools, and the median per-text score range was 100 points on a 100-point scale. The authors conclude that on mixed writing "the classification a text receives relies more on the choice of detector than on the text itself" (TextPulse, 18–19 Aug 2026 — working paper, not peer-reviewed).
- **Most deployed detectors are statistical guesses, not provenance checks.** Watermarking "has not been adopted in production systems" at scale (Dathathri et al., *Nature*, 23 Oct 2024), and we found no evidence that any student-facing academic-integrity product uses watermark detection. That is an absence of evidence, not proof of absence.

---

## 4. What has actually happened when universities relied on detectors

- **UC Davis (2023).** A history major was accused of using AI after GPTZero flagged his midterm; he was given a zero and reported to the honour court, and was cleared months later after producing his version history (Tech & Learning, 3 Dec 2023).
- **Texas A&M University-Commerce (May 2023).** An instructor ran essays through ChatGPT itself, failed the whole graduating class and withheld diplomas; the university reversed the grades and reinstated the students (KETR, 19 May 2023).
- **University of North Georgia (Oct 2023).** A student received a zero after Turnitin flagged her two-page paper as AI-generated; she had used Grammarly for grammar and spelling (EdSurge, 4 Apr 2024).
- **Adelphi University (court ruling, 28 Jan 2026).** Turnitin gave an essay an "AI-generated score of 100%"; the university found the student responsible. New York Supreme Court, Nassau County, annulled the finding, expunged the record and rescinded the penalty (*Matter of Newby v Adelphi Univ.*, 2026 NY Slip Op 26021, https://www.nycourts.gov/reporter/3dseries/2026/2026_26021.htm). It is a trial-level decision, not an appellate precedent, and the record included the student's own answers as well as the score — but it is the clearest legal ruling we located on a detector-based finding, and it went against the university.

Institutions have drawn their own conclusions. Vanderbilt disabled Turnitin's AI detector in August 2023, citing the false-positive arithmetic and evidence that detectors "are more likely to label text written by non-native English speakers as AI-written". Several other universities opted out in September 2023 (The Register, 23 Sept 2023). Nanyang Technological University in Singapore reportedly deactivated its institutional detector from the end of 2025 (reported in a peer-reviewed review, *AI and Ethics*, 17 Sept 2026 — secondary source; NTU's own notice not obtained).

---

## 5. What this means at HKUST and in Hong Kong

- **There is no single Hong Kong rule on detectors.** The University Grants Committee told LegCo on 29 March 2023 that UGC-funded universities are autonomous and set their own rules on AI in academia (https://www.info.gov.hk/gia/general/202303/29/P2023032900296.htm).
- **HKUST sets GenAI policy course by course.** HKUST allows faculty to set their own course-level policies, and instructors are required to communicate the chosen policy to students in writing for courses from Fall 2023-24 onward (HKUST Center for Education Innovation, "Guidelines and Policies", https://cei.hkust.edu.hk/en-hk/education-innovation/generative-ai-education/guidelines-and-policies).
- **HKUST's own teaching centre cautions against detector-only judgments.** Our research captured CEI guidance stating that solely relying on AI detection tools to detect AI-generated content in students' output "is not the best solution". *(Unverified: our fact-checker could not retrieve this sentence from the live CEI page, which renders only a login-gated guidebook introduction. Do not quote it in print until a colleague has opened the page and confirmed the wording.)*
- **Elsewhere in Hong Kong:** HKU banned ChatGPT in February 2023 and lifted the ban in early August 2023 in favour of permitted use with attribution (The Standard, 6 Aug 2023); CUHK's published guidance treats unauthorised AI use as plagiarism (secondary source, Young Post, 13 Mar 2023). We found **no official HKU or CUHK statement on detector reliability** — a gap, not a finding.

---

## 6. Remaining uncertainty — what we could not establish

We are confident in the verdict, but these points are genuinely open, and we flag them rather than smooth them over:

1. **No independent, peer-reviewed head-to-head study gives a single "accuracy %" for GPTZero or Originality.ai on real student coursework.** Their accuracy claims are self-reported. We did not verify them independently.
2. **The OpenAI 26%/9% figures** come from a page our tools could not open directly; they are corroborated by the page's search snippet and by news coverage, but should be eyeballed once in a browser before republication. The same applies to the HKUST CEI sentence quoted in §5.
3. **The strongest evidence of detector disagreement is a working paper by an interested party.** The TextPulse study is not peer-reviewed and is published by a company that sells an "AI humaniser" — it has a commercial interest in showing that detectors disagree. Its score matrix is public and could be reanalysed; until then, treat it as indicative.
4. **We found no peer-reviewed, large-N study measuring re-submission inconsistency** (the same text, the same tool, a different score). Anecdotal reports are common; a measured rate is not available to us.
5. **Several studies were verified only at abstract level** — Popkov et al. (*Accountability in Research*, 21 Mar 2024), the *Current Medical Research and Opinion* comparison (2 Mar 2024), TempParaphraser (EMNLP 2025) and a 2025 study on German theses. We cite their direction, not specific percentages. A 2026 PRISMA systematic review (Caner, Khazar University repository, 22 Jan 2026) and a 2025 Research Square preprint review were located but their findings were not read, so we do not cite their conclusions.
6. **The field moves fast.** Detectors are trained on older models and degrade on newer ones and on edited text; a study that is accurate today may not be next year. Nothing here should be read as a permanent verdict on any named product.
7. **Absence of evidence is not proof of absence.** We found no evidence that watermark-based detection is offered to universities for essay screening; that does not prove no vendor is working on it.

---

## 7. What students and faculty should do

**For students**
- **Know your course's rule, in writing.** At HKUST the rule is set course by course and must be given to you in writing; if you cannot find it, ask before you submit, not after.
- **Keep your process.** Drafts, version history, notes, outlines and earlier submissions are the evidence that actually clears people — they cleared the UC Davis student. Keep them.
- **A detector score is not a finding.** If you are accused, ask what evidence beyond the score exists, and use your institution's formal procedure and appeal route. In Hong Kong, suspected dishonesty must go through a formal procedure under university handbooks, not a single tool's output.
- **If English is not your first language, say so early.** The evidence shows your writing is more likely to be flagged; that is a known flaw in the tools, not a flaw in you.

**For faculty**
- **Do not use a single detector score as proof of misconduct.** Turnitin itself says its indicator should start a conversation, not draw a conclusion; HKUST's CEI says detector-only judgments are "not the best solution"; and a court has annulled a finding that rested on a 100% score.
- **Do the base-rate arithmetic before you act.** At a 1% false-positive rate over a large cohort, hundreds of honest students can be flagged. Ask what the prior probability of AI use in your class actually is.
- **Prefer process evidence and conversation.** Drafts, in-class writing, oral defence of the work, and a discussion about how the student wrote it are more reliable than any score — and they are what the case law rewards.
- **Design assessment so the question matters less.** Where AI use is permitted, require disclosure; where it is not, assess in ways that make the process visible.

---

## Sources

- OpenAI, "New AI classifier for indicating AI-written text", 31 Jan 2023 (updated Jul 2023) — https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/
- Liang, Yuksekgonul, Mao, Wu & Zou, "GPT detectors are biased against non-native English writers", *Patterns* 4(7):100779, 10 Jul 2023 — https://www.sciencedirect.com/science/article/pii/S2666389923001307 ; Stanford HAI, 15 May 2023 — https://hai.stanford.edu/news/ai-detectors-biased-against-non-native-english-writers
- Turnitin, "Understanding false positives within our AI writing detection capabilities", 15 Mar 2023 — https://www.turnitin.com/blog/understanding-false-positives-within-our-ai-writing-detection-capabilities ; "Understanding the false positive rate for sentences…", 13 Jun 2023 — https://www.turnitin.com/blog/understanding-the-false-positive-rate-for-sentences-of-our-ai-writing-detection-capability
- Vanderbilt University Brightspace, "Guidance on AI detection and why we're disabling Turnitin's AI detector", 16 Aug 2023 — https://www.vanderbilt.edu/brightspace/2023/08/16/guidance-on-ai-detection-and-why-were-disabling-turnitins-ai-detector/
- Dugan et al., "RAID: A Shared Benchmark for Robust Evaluation of Machine-Generated Text Detectors", ACL 2024 — https://arxiv.org/abs/2405.07940
- Krishna et al., "Paraphrasing evades detectors of AI-generated text, but retrieval is an effective defense", NeurIPS 2023 — https://arxiv.org/abs/2303.13408
- Dathathri et al., "Scalable watermarking for identifying large language model outputs", *Nature* 634:818–823, 23 Oct 2024 — https://www.nature.com/articles/s41586-024-08025-4
- TextPulse Research, "Do AI Detectors Agree?", 18–19 Aug 2026 (working paper) — https://zenodo.org/records/22003328
- *Matter of Newby v Adelphi Univ.*, NY Supreme Court, Nassau County, 28 Jan 2026, 2026 NY Slip Op 26021 — https://www.nycourts.gov/reporter/3dseries/2026/2026_26021.htm
- Tech & Learning, 3 Dec 2023 — https://www.techlearning.com/news/he-was-falsely-accused-of-using-ai-heres-what-he-wishes-his-professor-did-instead ; KETR, 19 May 2023 — https://www.ketr.org/news/2023-05-19/chatgpt-episode-at-a-m-commerce-receives-national-attention-on-social-media ; EdSurge, 4 Apr 2024 — https://www.edsurge.com/news/2024-04-04-can-using-a-grammar-checker-set-off-ai-detection-software
- "Are Teachers Assessing Work Written by Students or by AI? A Rapid Literature Review", *European Journal of Education*, 10 Sep 2025 — https://onlinelibrary.wiley.com/doi/10.1111/ejed.70240
- HKUST Center for Education Innovation, "Guidelines and Policies" — https://cei.hkust.edu.hk/en-hk/education-innovation/generative-ai-education/guidelines-and-policies ; UGC reply to LegCo, 29 Mar 2023 — https://www.info.gov.hk/gia/general/202303/29/P2023032900296.htm
- The Register, 23 Sept 2023 — https://www.theregister.com/2023/09/23/turnitin_ai_detection/ ; *AI and Ethics*, 17 Sept 2026 — https://link.springer.com/article/10.1007/s43681-026-01376-w
