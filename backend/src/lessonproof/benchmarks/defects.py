"""Deliberate errors planted in a good lesson, each paired with the check that must catch it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lessonproof.schemas import Lesson, QuizQuestion, SectionRole

HARD_TEXT = (
    "Contemporary epistemological frameworks necessitate comprehensive contextualization of "
    "heterogeneous informational repositories, notwithstanding substantial computational "
    "considerations inherent in sophisticated architectural methodologies. "
)
FOREIGN_TEXT = (
    "Think about the final play of the Super Bowl. A quarterback checks the playbook before he "
    "throws. It is also like a Thanksgiving dinner, when your family looks up a recipe. Baseball "
    "fans and tailgate parties work in the same way."
)


def _append(lesson: Lesson, role: SectionRole, text: str) -> Lesson:
    copy = lesson.model_copy(deep=True)
    copy.section(role).body += f"\n\n{text}"
    return copy


def _prepend(lesson: Lesson, role: SectionRole, text: str) -> Lesson:
    copy = lesson.model_copy(deep=True)
    copy.section(role).body = f"{text}\n\n{copy.section(role).body}"
    return copy


def _replace(lesson: Lesson, role: SectionRole, text: str) -> Lesson:
    copy = lesson.model_copy(deep=True)
    copy.section(role).body = text
    return copy


def _false_claim(lesson: Lesson) -> Lesson:
    return _append(
        lesson,
        SectionRole.HOW,
        "RAG works by retraining the LLM with your documents. After this, the documents become a "
        "permanent part of the model.",
    )


def _invented_statistic(lesson: Lesson) -> Lesson:
    return _append(
        lesson,
        SectionRole.WHY,
        "Studies show that RAG makes answers 95 percent more correct than every other method.",
    )


def _invented_claim(lesson: Lesson) -> Lesson:
    return _append(
        lesson,
        SectionRole.WHY,
        "RAG was first built by Google, and it can also read photos and videos by itself.",
    )


def _unexpanded_abbreviation(lesson: Lesson) -> Lesson:
    copy = lesson.model_copy(deep=True)
    for section in copy.sections:
        section.body = section.body.replace("large language model", "LLM")
        section.body = section.body.replace("Large language model", "LLM")
    copy.section(SectionRole.WHAT).body += "\n\nAn LLM helps here."
    return copy


def _absolute_promise(lesson: Lesson) -> Lesson:
    return _append(lesson, SectionRole.LIMITS, "With RAG, the answer is always correct.")


def _hard_language(lesson: Lesson) -> Lesson:
    copy = lesson.model_copy(deep=True)
    for section in copy.sections:
        section.body = HARD_TEXT * 8
    return copy


def _assumes_knowledge(lesson: Lesson) -> Lesson:
    return _prepend(
        lesson,
        SectionRole.WHAT,
        "As you already know from linear algebra and your Python projects, gradient descent "
        "trains the network. We will build on that here without explaining it again.",
    )


def _foreign_examples(lesson: Lesson) -> Lesson:
    copy = lesson.model_copy(deep=True)
    for role in (SectionRole.INTRO, SectionRole.WHAT, SectionRole.WHY, SectionRole.HOW):
        copy.section(role).body = FOREIGN_TEXT
    copy.section(SectionRole.EXAMPLE).body = FOREIGN_TEXT
    return copy


def _vague_example(lesson: Lesson) -> Lesson:
    return _replace(
        lesson,
        SectionRole.EXAMPLE,
        "Here is an example. A person asks a question. The system finds some text and adds it to "
        "the prompt. Then the LLM gives a good answer. This shows how the steps work together.",
    )


def _unexplained_jargon(lesson: Lesson) -> Lesson:
    return _prepend(
        lesson,
        SectionRole.INTRO,
        "The system uses cosine similarity over dense vectors with a bi-encoder to rank each "
        "passage.",
    )


def _unlisted_jargon(lesson: Lesson) -> Lesson:
    return _append(lesson, SectionRole.HOW, "Next, a transformer changes each token.")


def _drops_limits(lesson: Lesson) -> Lesson:
    return _replace(
        lesson,
        SectionRole.LIMITS,
        "RAG is a very useful tool. Many teams enjoy using it. You will enjoy it too.",
    )


def _drops_section(lesson: Lesson) -> Lesson:
    copy = lesson.model_copy(deep=True)
    copy.sections = [s for s in copy.sections if s.role != SectionRole.WHY]
    return copy


def _scrambled_order(lesson: Lesson) -> Lesson:
    copy = lesson.model_copy(deep=True)
    copy.sections.reverse()
    return copy


def _forward_dependency(lesson: Lesson) -> Lesson:
    copy = lesson.model_copy(deep=True)
    intro, example = copy.section(SectionRole.INTRO), copy.section(SectionRole.EXAMPLE)
    intro.body, example.body = example.body, intro.body
    return copy


def _wrong_quiz_answer(lesson: Lesson) -> Lesson:
    copy = lesson.model_copy(deep=True)
    copy.quiz[0] = QuizQuestion(
        question="In RAG, which step happens first?",
        answer="The LLM writes the answer first, and retrieval happens after that.",
    )
    return copy


def _new_idea_in_recap(lesson: Lesson) -> Lesson:
    return _append(
        lesson,
        SectionRole.RECAP,
        "You also learned that reranking and query rewriting make retrieval better.",
    )


@dataclass(frozen=True)
class Defect:
    id: str
    expected_check: str
    description: str
    apply: Callable[[Lesson], Lesson]


DEFECTS = [
    Defect("false-claim", "ACC-1", "States that RAG retrains the model", _false_claim),
    Defect("invented-claim", "ACC-2", "Adds a made-up origin and ability", _invented_claim),
    Defect("absolute-promise", "ACC-3", "Promises answers are always correct", _absolute_promise),
    Defect("invented-statistic", "ACC-4", "Adds a made-up 95 percent claim", _invented_statistic),
    Defect("hard-language", "LANG-1", "Rewrites everything in academic English", _hard_language),
    Defect("assumes-knowledge", "BEG-1", "Assumes linear algebra and Python", _assumes_knowledge),
    Defect("foreign-examples", "BEG-2", "Uses only American cultural examples", _foreign_examples),
    Defect("vague-example", "EX-1", "Replaces the worked example with a summary", _vague_example),
    Defect("unlisted-jargon", "JAR-1", "Uses technical terms missing from key words",
           _unlisted_jargon),
    Defect("unexplained-jargon", "JAR-2", "Uses heavy jargon with no explanation",
           _unexplained_jargon),
    Defect("unexpanded-abbreviation", "JAR-4", "Never spells out an abbreviation",
           _unexpanded_abbreviation),
    Defect("drops-limits", "COV-1", "Removes the explanation of RAG's limits", _drops_limits),
    Defect("drops-section", "COV-2", "Deletes a required section", _drops_section),
    Defect("scrambled-order", "FLOW-1", "Reverses the section order", _scrambled_order),
    Defect("forward-dependency", "FLOW-2", "Moves the full example before any teaching",
           _forward_dependency),
    Defect("wrong-quiz-answer", "FLOW-3", "Gives a false quiz answer", _wrong_quiz_answer),
    Defect("new-idea-in-recap", "FLOW-4", "Adds untaught ideas to the recap", _new_idea_in_recap),
]


def get_defect(defect_id: str) -> Defect:
    for defect in DEFECTS:
        if defect.id == defect_id:
            return defect
    known = ", ".join(d.id for d in DEFECTS)
    raise ValueError(f"Unknown defect '{defect_id}'. Choose one of: {known}")
