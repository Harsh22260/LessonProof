"""The authoring agents: researcher, planner, writer, and reviser."""

import re

from lessonproof import text as tx
from lessonproof.agents.context import (
    failures_block,
    grounding_block,
    guidelines_block,
    join_blocks,
    lesson_block,
    rubric_block,
    tag,
    writing_rules_block,
)
from lessonproof.llm import LLM
from lessonproof.prompts import load_prompt
from lessonproof.rubric import Rubric
from lessonproof.schemas import (
    CheckResult,
    FactPack,
    KeyTerm,
    Lesson,
    LessonExtras,
    LessonPlan,
    RevisionPatch,
    RevisionRecord,
    Section,
    SectionDraft,
    SectionRole,
)


def research_topic(llm: LLM, topic: str) -> FactPack:
    pack = llm.structured(
        "writer", FactPack, load_prompt("researcher"), tag("topic", topic)
    )
    return pack.model_copy(update={"topic": topic, "provenance": "model_generated"})


def create_plan(
    llm: LLM, topic: str, pack: FactPack, rubric: Rubric, guidelines: list[str]
) -> LessonPlan:
    user = join_blocks(
        tag("topic", topic), grounding_block(pack), rubric_block(rubric),
        guidelines_block(guidelines),
    )
    return llm.structured("writer", LessonPlan, load_prompt("audience", "planner"), user)


def write_section(
    llm: LLM,
    role: SectionRole,
    topic: str,
    pack: FactPack,
    plan: LessonPlan,
    rubric: Rubric,
    guidelines: list[str],
    problems: list[CheckResult] | None = None,
) -> SectionDraft:
    """Writes one section, given only the facts its plan assigned, to keep the prompt small."""
    section_plan = next((s for s in plan.sections if s.role == role), None)
    user = join_blocks(
        tag("topic", topic),
        tag("running_example", plan.running_example),
        tag("facts", pack.facts_block(section_plan.fact_ids if section_plan else None)),
        tag("misconceptions", pack.misconceptions_block()),
        writing_rules_block(rubric),
        guidelines_block(guidelines),
        tag("section_role", role.value),
        tag("section_plan", section_plan.model_dump_json() if section_plan else ""),
        failures_block(problems) if problems else "",
    )
    return llm.structured("writer", SectionDraft, load_prompt("audience", "section_writer"), user)


def write_extras(
    llm: LLM, title: str, sections: list[Section], pack: FactPack, guidelines: list[str]
) -> LessonExtras:
    """Writes the word list and quiz from the finished sections, so they match what was taught."""
    draft = Lesson(title=title, sections=sections, key_terms=[], quiz=[])
    user = join_blocks(
        tag("terms_to_define", ", ".join(pack.must_define)),
        guidelines_block(guidelines),
        lesson_block(draft),
    )
    return llm.structured("writer", LessonExtras, load_prompt("audience", "lesson_extras"), user)


def revise_lesson(
    llm: LLM,
    lesson: Lesson,
    failures: list[CheckResult],
    pack: FactPack,
    rubric: Rubric,
    guidelines: list[str],
) -> RevisionPatch:
    user = join_blocks(
        grounding_block(pack), rubric_block(rubric), guidelines_block(guidelines),
        lesson_block(lesson), failures_block(failures),
    )
    return llm.structured("writer", RevisionPatch, load_prompt("audience", "reviser"), user)


def tidy_lesson(lesson: Lesson, rubric: Rubric, pack: FactPack) -> tuple[Lesson, list[str]]:
    """Fixes purely mechanical problems in code, because they need no judgement or tokens."""
    limit = rubric.get("LANG-4").params["max_paragraph_sentences"]
    sections = []
    splits = 0
    for section in lesson.sections:
        body, count = tx.split_long_paragraphs(section.body, limit)
        splits += count
        sections.append(section.model_copy(update={"body": body}))
    fixes = [f"Split {splits} long paragraph(s), with no words changed"] if splits else []

    tidy = lesson.model_copy(update={"sections": sections})
    added = _missing_glossary_terms(tidy, pack)
    if added:
        tidy = tidy.model_copy(update={"key_terms": [*tidy.key_terms, *added]})
        fixes.append(f"Added to key words from the glossary: {', '.join(t.term for t in added)}")

    trimmed, dropped = _trim_key_terms(tidy, rubric, pack)
    if dropped:
        tidy = trimmed
        fixes.append(f"Removed non-essential key words: {', '.join(dropped)}")
    return tidy, fixes


def _trim_key_terms(lesson: Lesson, rubric: Rubric, pack: FactPack) -> tuple[Lesson, list[str]]:
    """Keeps the list within its limit, dropping unused terms first and then optional ones."""
    limit = rubric.get("JAR-3").params["max_terms"]
    excess = len(lesson.key_terms) - limit
    if excess <= 0:
        return lesson, []
    required = {t.lower() for t in [*rubric.get("JAR-1").params["jargon"], *pack.must_define]}

    def rank(term: KeyTerm) -> int:
        if not _term_is_used(term.term, lesson):
            return 0
        names = [term.term.split(" (")[0], *re.findall(r"\((.+?)\)", term.term)]
        return 2 if any(name.lower() in required for name in names) else 1

    removable = sorted(lesson.key_terms, key=rank)
    dropped = [t for t in removable[:excess] if rank(t) < 2]
    kept = [t for t in lesson.key_terms if t not in dropped]
    return lesson.model_copy(update={"key_terms": kept}), [t.term for t in dropped]


def _term_is_used(term: str, lesson: Lesson) -> bool:
    body = lesson.teaching_text()
    names = [term.split(" (")[0], *re.findall(r"\((.+?)\)", term)]
    return any(tx.contains_term(body, name) for name in names)


def _missing_glossary_terms(lesson: Lesson, pack: FactPack) -> list[KeyTerm]:
    body = lesson.teaching_text()
    listed = " | ".join(t.term.lower() for t in lesson.key_terms)
    missing = []
    for entry in pack.glossary:
        names = [entry.term.split(" (")[0], *re.findall(r"\((.+?)\)", entry.term)]
        is_used = any(tx.contains_term(body, name) for name in names)
        is_listed = any(name.lower() in listed for name in names)
        if is_used and not is_listed:
            missing.append(entry)
    return missing


def apply_patch(lesson: Lesson, patch: RevisionPatch) -> Lesson:
    updates = {u.role: u for u in patch.section_updates}
    sections = [
        s.model_copy(update={"heading": updates[s.role].heading, "body": updates[s.role].body})
        if s.role in updates
        else s
        for s in lesson.sections
    ]
    existing = {s.role for s in lesson.sections}
    missing = [u for role, u in updates.items() if role not in existing]
    if missing:
        order = {role: i for i, role in enumerate(type(lesson.sections[0].role))}
        added = [
            lesson.sections[0].model_copy(
                update={"role": u.role, "heading": u.heading, "body": u.body}
            )
            for u in missing
        ]
        sections = sorted(sections + added, key=lambda s: order[s.role])
    return lesson.model_copy(
        update={
            "sections": sections,
            "key_terms": patch.key_terms if patch.key_terms is not None else lesson.key_terms,
            "quiz": patch.quiz if patch.quiz is not None else lesson.quiz,
        }
    )


def describe_revision(
    before: Lesson,
    after: Lesson,
    patch: RevisionPatch,
    base_attempt: int,
    rolled_back: bool,
) -> RevisionRecord:
    """Measures the real difference, so the log does not rely on the reviser's own account."""
    before_map = {s.role: s for s in before.sections}
    changed = [
        s.role.value
        for s in after.sections
        if s.role not in before_map
        or (s.heading, s.body) != (before_map[s.role].heading, before_map[s.role].body)
    ]
    old_words = [w.lower() for w in tx.words(before.teaching_text())]
    new_words = [w.lower() for w in tx.words(after.teaching_text())]
    return RevisionRecord(
        base_attempt=base_attempt,
        rolled_back=rolled_back,
        sections_changed=changed,
        key_terms_changed=before.key_terms != after.key_terms,
        quiz_changed=before.quiz != after.quiz,
        words_added=_multiset_difference(new_words, old_words),
        words_removed=_multiset_difference(old_words, new_words),
        notes=patch.change_notes,
    )


def _multiset_difference(left: list[str], right: list[str]) -> int:
    remaining: dict[str, int] = {}
    for word in right:
        remaining[word] = remaining.get(word, 0) + 1
    count = 0
    for word in left:
        if remaining.get(word, 0):
            remaining[word] -= 1
        else:
            count += 1
    return count
