# Rejection Log: Introduction to RAG (Retrieval-Augmented Generation)

- Run: `20261106-190509-84070e`
- Final status: **SHIPPED** after 2 attempt(s)
- Usage (judge): 12 calls, 21601 input tokens, 18419 output tokens, models: {'google_genai:gemini-3.5-flash-lite': 12}
- Usage (writer): 4 calls, 13775 input tokens, 6726 output tokens, models: {'google_genai:gemini-3.5-flash-lite': 4}

## Attempt 1: REJECTED (19/23 checks run, 10s)

Fixed by code, at no token cost:

- Split 1 long paragraph(s), with no words changed
- Added to key words from the glossary: indexing, augmentation
- Split 1 long paragraph(s), with no words changed

The author's draft failed these rule checks, and had one repair before judging:

- FLOW-1: 560 words, needs 600-1500.

| Check | Dimension | Why it failed | Evidence | Required fix |
| --- | --- | --- | --- | --- |
| EX-2 | examples | The section explaining what the topic is does not contain any concrete example or analogy. | - | Add a concrete example or analogy to the 'what' section to explain the concept. |
| JAR-2 | clarity | The term RAG is used in the title before it is defined, and when it is introduced, it is only expanded into its full form rather than explained in plain, simple words. | `Welcome to AI and RAG`; `RAG stands for Retrieval-Augmented Generation.` | Explain what Retrieval-Augmented Generation means in simple words the very first time RAG is mentioned. |
| COV-1 | coverage | K3 (Why RAG matters, covering answers based on current or private information without retraining the model, and sources that people can check): The lesson explains that RAG provides outside facts without retraining, but it does not cover sources that people can check. \| K7 (The limits of RAG, covering that it reduces but does not remove wrong answers and depends on good documents and good retrieval): its quote is not in the lesson sections. | - | Teach each listed key point in the lesson body. |
| FLOW-2 | flow | The lesson introduces embeddings, embedding models, and vector databases in the '[how] How RAG Works Step by Step' section without defining them first, or explaining them simply before using the terms. | `An embedding is a list of numbers that represents the meaning of text.`; `Think of it like a set of test scores that shows how close two subjects are to each other. An embedding model is an AI model that turns text into embeddings.` | Explain what embeddings, embedding models, and vector databases are in simple terms before using them in the step-by-step section. |

## Attempt 2: PASSED (23/23 checks run, 7s)

Fixed by code, at no token cost:

- Split 3 long paragraph(s), with no words changed

**What changed on this retry**

- Sections rewritten: intro, what, why, how
- Key words changed: no; quiz changed: no
- Words added: 82; words removed: 1
- Checks fixed: COV-1, EX-2, FLOW-2, JAR-2
- New failures: none

Reviser's notes:

- EX-2: Added a concrete analogy comparing RAG to an open-book exam in the 'what' section.
- JAR-2: Introduced the simple open-book exam comparison in the intro section the very first time RAG is mentioned.
- COV-1: Added the fact that RAG shows which documents it used so people can check the answer to the 'why' section to fully cover K3.
- FLOW-2: Defined embeddings, embedding models, and vector databases with simple explanations and daily-life analogies in the 'how' section before using them in the steps.
