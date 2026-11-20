# Can AI-writing detectors reliably tell whether a student wrote an assignment?

**A fact-check for students and faculty**

**Verdict: Not supported.** "Reliably determine" means a detector's verdict on one student's assignment is accurate and dependable enough to act on — to fail a paper, open a misconduct case, or clear a student. The evidence does not meet that standard. Detectors measure statistical style, not authorship. Their error rates are high and unevenly distributed, they are easy to defeat, and the leading vendor's own guidance, as restated by universities using its tool, says a score should not be used on its own to accuse a student. A detector can raise a question worth asking. It cannot answer it.

## The evidence against the claim

**The makers of the biggest AI model withdrew their own detector.** OpenAI launched its AI Text Classifier on 31 January 2023 and published its own accuracy figures: it caught **26%** of AI-written text and wrongly flagged human-written text **9%** of the time. On 20 July 2023 OpenAI withdrew it, stating the reason plainly: "no longer available due to its low rate of accuracy." The tool lasted under six months.

**The leading commercial detector's own numbers are modest.** Turnitin switched on its AI-writing indicator in April 2023, claiming about **98%** accuracy and a false-positive rate **below 1%**. A secondary summary of Turnitin's methodology reports its testing on roughly 2,000 English-language-learner samples found false positives of **0.014%** for those writers against **0.013%** for native speakers, with no statistically significant bias. But Turnitin's chief product officer has since said the tool **misses roughly 15%** of AI-generated text — a deliberate trade-off to keep false positives near 1%. That is a miss rate (false negatives), not a contradiction of the 98% figure. And Turnitin's guidance, as restated by universities using the tool, says the score should **not be the sole basis for adverse action** against a student.

**Independent tests are much worse than the marketing.** In an April 2023 test by *The Washington Post*, Turnitin's detector wrongly flagged **more than half** of the text it was given as AI-written, including part of a real student's essay — the "innocent student" of the Post's headline. A widely cited independent evaluation, Weber-Wulff and colleagues in the *International Journal for Educational Integrity* (25 December 2023), tested a range of commercial and free detectors and concluded that **none was reliable enough for high-stakes use**; manual paraphrasing alone pushed the share of AI text going undetected to roughly **50%**.

**The errors are not random — they fall on particular students.** Liang and colleagues at Stanford, in an opinion paper in *Patterns* (10 July 2023), ran seven widely used detectors over essays by native English speakers and by non-native writers sitting TOEFL. Across the seven detectors the average false-positive rate on the non-native essays was **61.22%**, and **18 of the 91** essays were flagged by all seven detectors at once; native-speaker essays were reported as classified with near-perfect accuracy. Secondary coverage of the same study also reports a 97% flagging figure; the two are not reconciled in the sources we reviewed, and the paper itself must be read before either is quoted. The mechanism is plain. Detectors key on perplexity and burstiness — how predictable the next word is, and how much sentence lengths and rhythms vary. Careful, formulaic, or second-language academic prose looks statistically "AI-like" on both counts.

A separate Maryland study, Saha and Feizi's "Almost AI, Almost Human" (arXiv, February 2025; reported in Findings of ACL 2025), found that after only **extremely minor AI edits** to human writing, false-positive rates rose to **32%** for ZeroGPT and **43%** for a second detector, across twelve detectors and about 14,700 samples. These figures come from a single secondary report.

**Detection can be defeated by routine editing.** Sadasivan and colleagues at Maryland, in a preprint ("Can AI-Generated Text be Reliably Detected?", arXiv, March 2023), showed both in theory and in tests that paraphrasing evades a wide range of detectors, including watermarked ones. One reported result — from a secondary summary, not checked against the paper's tables — puts a watermark's true-positive rate at a 1% false-positive rate falling from **99% to 15%** after five rounds of paraphrasing. A detector that a free paraphrasing tool can beat is not a reliable test of authorship.

**Several universities have switched the feature off.** Vanderbilt University disabled Turnitin's AI detector effective 16 August 2023. Montclair State's provost ordered it switched off on 1 November 2023, citing "challenges and limitations" and concerns about false positives. In late September 2025 RNZ reported that Massey, Auckland and Victoria universities in New Zealand had stopped using detection software, with Massey calling detection unreliable. The consequences are real: in January 2026 the New York Supreme Court in Nassau County annulled an Adelphi University misconduct finding in *Newby v. Adelphi University*, a case in which Turnitin had scored an essay **100% AI-generated** while conventional similarity checking returned **4%**; that account rests on secondary summaries of the ruling pending the court record.

## What this means for you

**If you are a student:**

- A detector score is not proof you cheated, and a high score is not a finding. If you are challenged, ask what evidence exists beyond the score.
- Keep your drafts, notes, version history and any AI-use disclosure your course requires. Process evidence is what actually defends you.
- Be careful with editing tools. A Murdoch University nursing student was accused after using a grammar checker the university itself recommended (ABC News, July 2025). If your course restricts AI-assisted editing, know the rule before you use Grammarly-style tools.
- If you write in a second language, you are statistically more likely to be flagged. That is a known flaw in the tools, not a reflection of your work.

**If you are faculty:**

- Do not treat a detector percentage as evidence of misconduct. A systematic review in *Discover Education* (16 October 2026) recommends that staff evaluate flagged work "within its full academic context rather than treating detector scores as definitive evidence", and warns against treating false-positive rates reported across heterogeneous studies as directly comparable.
- Use a flag as a prompt for a conversation or an oral follow-up, not as a verdict. Ask for drafts and revision history.
- Design assessment so authorship matters less: in-class writing, staged drafts, oral defence of submitted work.
- Check your institution's policy before quoting a score to a student. Several universities have disabled these features outright.

## What we still don't know

- **How good today's detectors are.** Most published accuracy figures come from 2023-era tools, and we found no independent, peer-reviewed evaluation of current commercial versions.
- **Whether newer models are harder to detect.** It is widely asserted that GPT-4-class output is harder to catch than earlier output, but we found no verified figure quantifying the difference. Treat the comparison as unproven.
- **The true rate of wrongful accusation.** Court cases and news reports show it happens. Nobody has measured how often.
- **What "written by AI" means.** A student who outlines with a chatbot, drafts alone and edits with a grammar tool sits somewhere in the middle. Most detectors do not distinguish degrees of involvement — Saha and Feizi found most flagged light edits at nearly the same rate as heavy rewrites.
- **Sourcing note.** Every figure in this article comes from search-result snippets, published abstracts, vendor statements or secondary summaries; none was read from the primary source, and the primary papers and court record should be checked before republication. The Adelphi case is a court ruling reported through secondary summaries.

## The bottom line

Detectors can flag text that *looks* machine-like. They cannot establish who wrote it. Using a score to decide a student's fate mistakes a statistical guess for a finding of fact — and the students most likely to be guessed wrong are those writing in a second language, and students who edit their own drafts with AI-assisted tools.

---

### Sources

1. OpenAI, "New AI classifier for indicating AI-written text," 31 January 2023 (withdrawn 20 July 2023). https://openai.com/index/new-ai-classifier-for-indicating-ai-written-text/
2. Turnitin AI writing detection, launched April 2023; accuracy and false-positive claims as reported by The Register, 4 April 2023. https://www.theregister.com/software/2023/04/05/anti-plagiarism-tool-turnitin-turns-on-ai-writing-detection/556280
3. Geoffrey Fowler, "We tested a new ChatGPT-detector for teachers. It flagged an innocent student," *The Washington Post*, 1 April 2023. https://www.washingtonpost.com/technology/2023/04/01/chatgpt-cheating-detection-turnitin/
4. D. Weber-Wulff et al., "Testing of detection tools for AI-generated text," *International Journal for Educational Integrity* 19:26, 25 December 2023. https://doi.org/10.1007/s40979-023-00146-z
5. W. Liang, M. Yuksekgonul, Y. Mao, E. Wu, J. Zou, "GPT detectors are biased against non-native English writers," *Patterns*, 10 July 2023. https://www.sciencedirect.com/science/article/pii/S2666389923001307
6. S. Saha, S. Feizi, "Almost AI, Almost Human: The Challenge of Detecting AI-Polished Writing," arXiv:2502.15666, February 2025. https://arxiv.org/abs/2502.15666
7. V. S. Sadasivan et al., "Can AI-Generated Text be Reliably Detected?", arXiv:2303.11156, March 2023. https://arxiv.org/abs/2303.11156
8. Vanderbilt University, "Guidance on AI Detection and Why We're Disabling Turnitin's AI Detector," 16 August 2023. https://www.vanderbilt.edu/brightspace/2023/08/16/guidance-on-ai-detection-and-why-were-disabling-turnitins-ai-detector/
9. Montclair State University, Provost memorandum on disabling Turnitin AI detection, 1 November 2023. https://www.montclair.edu/faculty-excellence/wp-content/uploads/sites/195/2023/11/Provost-Communication-AI-Detection-Disabling-Fall-2023.docx.pdf
10. RNZ, "Universities give up using software to detect AI in students' work," 29 September 2025. https://www.rnz.co.nz/news/education/574517/universities-give-up-using-software-to-detect-ai-in-students-work
11. ABC News (Australia), "Uni student accused of using AI in assignment fights to clear his name," 11 July 2025. https://www.abc.net.au/news/2025-07-11/murdoch-university-student-fights-accusation-of-ai-use/105518732
12. "AI content detection in student text assignments, false positive rates, and academic integrity," *Discover Education*, 16 October 2026. https://link.springer.com/article/10.1007/s44217-026-02307-x
13. *AI and Ethics* (Springer), 2026, review of institutional retreat and litigation, including the *Newby v. Adelphi University* ruling. https://link.springer.com/content/pdf/10.1007/s43681-026-01376-w.pdf
14. Turnitin chief product officer on the ~15% miss rate, as reported by Detection Drama, 2026 (secondary).
15. Turnitin's "not the sole basis for adverse action" caution, as restated in institutional guidance (e.g. Washington State University, "AI Writing Detection and Turnitin") and press coverage (secondary).
