# Fact check: Can AI-writing detectors reliably tell whether a student's assignment was written by AI?

**Verdict: FALSE — as stated, the claim is not supported by the evidence.** Detectors can flag *some* AI-written text. The published, independent evidence does not show that they can *reliably determine* authorship of a student assignment: they miss a lot of AI text, they wrongly flag a lot of human text, and the errors fall unevenly on some groups of students. **Our conclusion** is that a detector score is a weak signal, not a finding of fact.

*Audience: students and faculty.*

---

## 1. What exactly is being claimed?

The claim has three parts, and each has to hold:

1. **Detectors exist and produce a verdict** on a piece of student writing.
2. **That verdict is reliable** — right nearly all the time in both directions: it catches AI-written work, and it does not accuse students who wrote their own.
3. **It determines authorship** — good enough to act on, for example in a misconduct case.

Part 1 is true. Parts 2 and 3 are where the claim collapses. "Reliable" is the load-bearing word: a tool that is right most of the time on average can still be wrong most of the time *when it raises a flag*, if AI-written work is rare in the class being screened (§4).

---

## 2. What the evidence shows

### 2.1 Independent testing: "neither accurate nor reliable"

The most direct test is Weber-Wulff and colleagues, *Testing of Detection Tools for AI-Generated Text*, **International Journal for Educational Integrity** 19:26 (2023). The authors tested **12 publicly available tools plus two commercial systems, Turnitin and PlagiarismCheck**, against ChatGPT-generated text. Their conclusion, in their own words: *"the available detection tools are neither accurate nor reliable and have a main bias towards classifying the output as human-written rather than detecting AI-generated text."* They add that *"content obfuscation techniques significantly worsen the performance of tools."*

Two things matter. First, the dominant error is a **miss**, not a false accusation — so a clean detector report tells you very little. Second, light disguise made the tools worse: a student who paraphrases is not caught, while a student who writes plainly may be.

### 2.2 Non-native English writers are systematically misclassified

Liang, Yuksekgonul, Mao, Wu and Zou (all Stanford University), *GPT detectors are biased against non-native English writers*, **Patterns** (Cell Press), 14 July 2023. The authors ran seven widely used detectors over **91 TOEFL essays** and **88 US eighth-grade essays**. They report that the detectors classified the US student essays accurately, but **incorrectly labelled more than half of the TOEFL essays as AI-generated — an average false-positive rate of 61.3%**. (The paper's per-detector figures for the US essays were not available to us; "accurately" is the authors' characterisation, not a measured zero.)

The authors also found that *"simple prompting strategies can not only mitigate this bias but also effectively bypass GPT detectors"*, and they *"caution against their use in evaluative or educational settings."*

For a university with a large international cohort this is the most important finding in the literature: the error rate is not spread evenly. It lands hardest on students writing in a second or third language.

### 2.3 Detectors work only on the text they were trained on

M4GT-Bench (Wang et al., 14 authors, **ACL 2024** main conference) is a multilingual, multi-domain, multi-generator benchmark. Its central finding: *"obtaining good performance in MGT detection usually requires an access to the training data from the same domain and generators."*

In plain terms, a detector tuned on one model's output and one kind of writing does not transfer to a new model or a new genre, and every new model release moves the target. The benchmark also tests **mixed human–machine text** — a student drafting with AI help and then editing — as a separate, harder task, and that is the most common real case.

### 2.4 Watermarking does not solve it

The most promising technical fix is watermarking: a model embeds a statistical signature in its output. Google DeepMind's SynthID-Text (Dathathri et al.), published in **Nature** vol. 634, 23 October 2024, doi:10.1038/s41586-024-08025-4, is described as *"a production-ready text watermarking scheme that preserves text quality and enables high detection accuracy, with minimal latency overhead."*

But a watermark can only be found in text produced by a model that embeds it, and only while the text is largely intact — heavily rewritten text may lose the signal. Text from a model without watermarking, or from an open-weight model run locally, carries no watermark at all. Watermarking can answer "was this produced by a watermarked model and left mostly unmodified?" It cannot answer "did a student use AI?"

### 2.5 A regulator has already rejected a "98% accurate" claim

In April 2025 the US Federal Trade Commission announced an order against Workado LLC over its "AI Content Detector", marketed as **"98 percent"** accurate. According to the FTC's complaint, independent testing showed accuracy of about **53 percent on general-purpose content**, and the model *"was trained or fine-tuned to effectively classify only academic content."* The FTC approved a final order on 28 August 2025; its Bureau of Consumer Protection director called the tool's performance "no better than a coin toss" (*CyberScoop*, 29 August 2025).

Two cautions. This is an action about **advertising claims**, not a ruling that detectors may not be used in misconduct proceedings. And the "trained only on academic content" allegation cuts both ways: the tool may have done better on student essays than on general text, so 53% should not be read as the accuracy on assignments. What the case does establish is that a headline accuracy number from a vendor is not evidence.

### 2.6 What happens when an accusation is wrong

In May 2023 Dr Jared Mumm, an instructor at Texas A&M University–Commerce, ran his students' **last three essay assignments** through ChatGPT itself, twice each, and gave a zero or an incomplete to any student whose text the chatbot "claimed"; seniors who had already walked at graduation were temporarily denied their diplomas. ChatGPT is a generative model, not a detector, and it will claim authorship of text it did not write. The university said it was investigating and developing AI policy (*Rolling Stone*, 17 May 2023; *New York Post*, 18 May 2023).

This case is about a chatbot misused as a detector, not a commercial detector's false positive — but it shows the shape of the harm: a machine verdict, applied at scale, with the burden of proof falling on the student.

---

## 3. Why the claim fails

- **The errors run in both directions, and the bigger one is silence.** Independent testing found tools biased toward calling AI text human. A "0% AI" report is close to meaningless.
- **The false positives are not random.** They concentrate on non-native English writers (61.3% on TOEFL essays) and on writing that is plain, formulaic or heavily edited — the register many students are taught to produce.
- **The target moves.** Detectors need same-generator, same-domain training data; new models arrive constantly.
- **The technical fix is conditional.** Watermarks only exist in cooperating models' unmodified output.
- **Vendor accuracy claims have not held up when tested.** The one claim a regulator has tested in public did not survive (§2.5).

---

## 4. The arithmetic that decides the policy question

Even a detector with a **1% false-positive rate** produces mostly wrong accusations when AI use is rare. Our own illustrative calculation, not a measurement, using a 1% false-positive rate and an assumed 80% detection rate:

| AI use in the cohort | Submissions | True flags (80% caught) | False flags (1% of human-written submissions) | Share of flags that are wrong |
|---|---|---|---|---|
| 5% | 10,000 | 400 | 95 | **≈19%** |
| 1% | 10,000 | 80 | 99 | **≈55%** |
| 0.5% | 10,000 | 40 | ≈100 | **≈71%** |

The lesson is general: **the rarer the misconduct, the more often a flag is wrong.** A tool can be "98% accurate" and still be wrong most of the time it fires — when AI use is rare. Any policy that treats a flag as a finding inherits this arithmetic.

Note what the 1% premise is worth: Turnitin's claimed sub-1% false-positive rate is stated by the company only for documents with **20% or more AI writing**, and it has conceded a higher incidence of false positives below that threshold (*Inside Higher Ed*, 1 June 2023). For the typical submission, the vendor does not claim 1%.

---

## 5. What remains uncertain

We are not claiming detectors are useless. Several questions are genuinely open:

1. **Some detectors may be much better than the 2023 studies suggest.** Pangram, a commercial detector, publishes a technical report by its own founders (Emi & Spero, February 2024) claiming error rates *"over 38 times lower"* than DetectGPT and leading commercial detectors, and no bias against non-native English speakers — on the company's own benchmark. We found no independent replication. A well-resourced detector on a known model may perform substantially better than the tools tested in 2023.
2. **We found no published figure, as of this article's research, for how detectors perform on the newest model families** (GPT-4-class and later, Claude, Gemini). The mechanism in §2.3 predicts degradation; that is a reason to expect it, not a measurement, so we give no number.
3. **The base-rate table is arithmetic, not measurement.** It shows the structure of the problem; the real false-positive rate of any specific tool at any specific threshold is unknown to us.
4. **Turnitin's own published figures could not be read directly** (its site blocked automated access). The only verified Turnitin numbers are the conditional sub-1% false-positive rate from its March and June 2023 posts. **We could not verify any "98% accuracy" claim by Turnitin from its own pages**, and the article should not be read as saying Turnitin makes one.
5. **We could not verify the text of university or regulator guidance** (QAA, Russell Group, TEQSA, individual universities) on how detector scores should be used. We therefore make no claim about what any institution's rules currently say.
6. **We found no reliable data on how often students are wrongly accused.** The Texas A&M case is documented; its frequency is not.

---

## 6. What this means for students

- **A detector score is not proof.** If you are accused on the basis of a detector report, ask for the specific tool, the specific passage, the score, and the false-positive rate the tool claims at that threshold.
- **Keep your drafts.** Version history, timestamps, notes and earlier outlines are the evidence that actually settles these cases. The Texas A&M students reportedly offered Google Docs version history, which the instructor initially ignored — which is exactly why you should keep yours.
- **Writing in a second language is a known trigger.** If English is not your first language, the published evidence says you are more likely to be flagged for writing you did yourself. That is a documented bias in the tool, not a judgement about you.
- **Check your course outline, not the detector.** Your course's rules on AI use are written down somewhere; a detector cannot tell you what they are.

## 7. What this means for faculty

- **Do not treat a detector flag as a finding.** Use it, if at all, as a reason to look at the work and talk to the student — never as the evidence itself.
- **Do not run student work through a chatbot to ask if it wrote the text.** That is what happened at Texas A&M; chatbots claim authorship of text they did not write.
- **Collect process evidence.** Outlines, drafts, in-class writing and a short oral defence give you something a detector score cannot: a record of how the work was made. They are also fairer to students who write in a second language.
- **Write the AI rule into the course outline in specific terms** — which tools, for which tasks, with what disclosure — so the question in a dispute is what the rules were, not what a classifier thinks.
- **Expect the tool to miss things.** The dominant error in independent testing was AI text classified as human. A clean report is not a clean bill of health.

---

## 8. Sources

1. Weber-Wulff, Anohina-Naumeca, Bjelobaba, Foltýnek, Guerrero-Dib, Popoola, Šigut, Waddington, "Testing of Detection Tools for AI-Generated Text", *International Journal for Educational Integrity* 19:26 (2023), doi:10.1007/s40979-023-00146-z; preprint https://arxiv.org/abs/2306.15666
2. Liang, Yuksekgonul, Mao, Wu, Zou, "GPT detectors are biased against non-native English writers", *Patterns* (2023), https://www.cell.com/patterns/fulltext/S2666-3899(23)00130-7 ; preprint https://arxiv.org/abs/2304.02819
3. Wang et al., "M4GT-Bench: Evaluation Benchmark for Black-Box Machine-Generated Text Detection", ACL 2024 (main), https://arxiv.org/abs/2402.11175
4. Dathathri et al., "Scalable watermarking for identifying large language model outputs" (SynthID-Text), *Nature* 634 (2024), doi:10.1038/s41586-024-08025-4
5. Emi & Spero, "Pangram Text" technical report, https://arxiv.org/abs/2402.14873 (vendor-authored, own benchmark)
6. US Federal Trade Commission, "FTC Order Requires Workado to Back Up Artificial Intelligence Detection Claims", 28 April 2025, https://www.ftc.gov/news-events/news/press-releases/2025/04/ftc-order-requires-workado-back-artificial-intelligence-detection-claims ; final order, 28 August 2025, https://www.ftc.gov/news-events/news/press-releases/2025/08/ftc-approves-final-order-against-workado-llc-which-misrepresented-accuracy-its-artificial ; *CyberScoop*, "Workado settles with FTC over allegations it inflated its AI detector's accuracy", 29 August 2025, https://cyberscoop.com/ftc-workado-settlement-ai-detector-false-and-misleading-claims/
7. *Rolling Stone*, "Professor Flunks All His Students After ChatGPT Falsely Claims It Wrote Their Papers", 17 May 2023, https://www.rollingstone.com/culture/culture-features/texas-am-chatgpt-ai-professor-flunks-students-false-claims-1234736601/ ; *New York Post*, 18 May 2023, https://nypost.com/2023/05/18/texas-professor-flunked-whole-class-after-chatgpt-wrongly-claimed-it-wrote-their-papers/
8. Turnitin blog posts, 16 March 2023 and 14 June 2023 (conditional false-positive claims; read via search snippets only — see §5.4); *Inside Higher Ed*, "Turnitin's AI detector has a higher than expected false positive rate", 1 June 2023, https://www.insidehighered.com/news/quick-takes/2023/06/01/turnitins-ai-detector-higher-expected-false-positives
