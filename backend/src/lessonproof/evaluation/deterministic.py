"""Rule-based checks. They cost no tokens, never vary between runs, and name exact offenders."""

import re
from collections.abc import Callable

import textstat
from wordfreq import zipf_frequency

from lessonproof import text as tx
from lessonproof.rubric import Check, Rubric
from lessonproof.schemas import CheckResult, FactPack, Lesson, Section

MAX_LISTED_OFFENDERS = 12
NEGATION_WINDOW_WORDS = 3
NEGATIONS = {"not", "no", "never", "cannot", "can't", "doesn't", "don't", "isn't", "won't"}
STATISTIC = re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|percent\b|per cent\b)", re.IGNORECASE)

Outcome = tuple[bool, str, str, list[str]]
CheckFn = Callable[[Lesson, FactPack, dict], Outcome]

_REGISTRY: dict[str, CheckFn] = {}


def _register(check_id: str) -> Callable[[CheckFn], CheckFn]:
    def decorator(fn: CheckFn) -> CheckFn:
        _REGISTRY[check_id] = fn
        return fn

    return decorator


def _is_negated(body: str, match_start: int) -> bool:
    preceding = re.findall(r"[a-z']+", body[:match_start].lower())[-NEGATION_WINDOW_WORDS:]
    return any(word in NEGATIONS for word in preceding)


def _hardest_sections(lesson: Lesson, count: int = 3) -> list[str]:
    """Sections with the longest sentences, with their average, so a fix can be targeted."""
    averages = []
    for section in lesson.sections:
        parts = tx.sentences(section.body)
        if parts:
            average = sum(len(tx.words(p)) for p in parts) / len(parts)
            averages.append((average, f"{section.role.value} ({average:.1f} words per sentence)"))
    return [label for _, label in sorted(averages, reverse=True)[:count]]


@_register("ACC-3")
def _no_absolute_promises(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    body = lesson.teaching_text()
    hits = []
    for phrase in params["banned_phrases"]:
        for match in re.finditer(rf"\b{re.escape(phrase)}\b", body, re.IGNORECASE):
            if not _is_negated(body, match.start()):
                hits.append(phrase)
    if hits:
        return (
            False,
            f"Absolute promises found: {sorted(set(hits))}.",
            "Replace each absolute promise with an honest statement of what usually happens.",
            sorted(set(hits)),
        )
    return True, "No absolute promises.", "", []


@_register("ACC-4")
def _no_statistics(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    hits = [
        match.group(0)
        for section in lesson.sections
        if section.role.value != params["exempt_role"]
        for match in STATISTIC.finditer(section.body)
    ]
    if hits:
        return (
            False,
            f"Statistics that the fact sheet does not provide: {hits}.",
            "Remove each listed number, or say the same thing without a statistic.",
            hits,
        )
    return True, "No invented statistics.", "", []


@_register("JAR-4")
def _abbreviations_spelled_out(lesson: Lesson, pack: FactPack, _: dict) -> Outcome:
    body = lesson.teaching_text()
    missing = [
        short
        for short, full in pack.abbreviations.items()
        if re.search(rf"\b{re.escape(short)}s?\b", body) and not tx.contains_term(body, full)
    ]
    if missing:
        names = [f"{short} ({pack.abbreviations[short]})" for short in missing]
        return (
            False,
            f"Abbreviations never spelled out in the lesson body: {names}.",
            "Write the full name beside each listed abbreviation where it first appears.",
            missing,
        )
    return True, "All abbreviations are spelled out.", "", []


@_register("LANG-1")
def _reading_grade(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    limit = params["max_grade"]
    grade = textstat.flesch_kincaid_grade(tx.prose(lesson.teaching_text()))
    if grade > limit:
        return (
            False,
            f"Reading grade is {grade:.1f}; the limit is {limit}.",
            f"Aim for grade {limit - 1:.0f}. Start with these hardest sections: "
            f"{_hardest_sections(lesson)}. Use shorter sentences and shorter everyday words.",
            [],
        )
    return True, f"Reading grade is {grade:.1f}.", "", []


@_register("LANG-2")
def _sentence_length(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    all_sentences = tx.sentences(lesson.teaching_text())
    if not all_sentences:
        return False, "The lesson has no sentences.", "Write the lesson body.", []
    counts = [len(tx.words(s)) for s in all_sentences]
    average = sum(counts) / len(counts)
    too_long = [
        s for s, n in zip(all_sentences, counts, strict=True) if n > params["max_sentence_words"]
    ]
    if average > params["max_average_words"] or too_long:
        return (
            False,
            f"Average sentence is {average:.1f} words (limit {params['max_average_words']}); "
            f"{len(too_long)} sentences exceed {params['max_sentence_words']} words.",
            f"Bring the average down to {params['max_average_words'] - 2} words by splitting "
            f"sentences, starting with these sections: {_hardest_sections(lesson)}. Also split "
            "every listed sentence.",
            too_long[:MAX_LISTED_OFFENDERS],
        )
    return True, f"Average sentence is {average:.1f} words.", "", []


def _defined_stems(lesson: Lesson, pack: FactPack) -> set[str]:
    names = [t.term for t in lesson.key_terms] + pack.must_define
    tokens = {w.lower() for name in names for w in tx.words(name)}
    return {t[: max(4, len(t) - 3)] for t in tokens}


@_register("LANG-3")
def _rare_words(lesson: Lesson, pack: FactPack, params: dict) -> Outcome:
    stems = _defined_stems(lesson, pack)
    rare: set[str] = set()
    rare_count = 0
    all_words = 0
    for sentence in tx.sentences(lesson.teaching_text()):
        for index, word in enumerate(tx.words(sentence)):
            all_words += 1
            is_name = index > 0 and word[0].isupper()
            lowered = word.lower()
            if is_name or any(lowered.startswith(stem) for stem in stems):
                continue
            if zipf_frequency(lowered, "en") < params["zipf_threshold"]:
                rare.add(lowered)
                rare_count += 1
    share = rare_count / all_words if all_words else 0.0
    if share > params["max_rare_share"]:
        return (
            False,
            f"Uncommon words are {share:.1%} of the text; the limit is "
            f"{params['max_rare_share']:.1%}.",
            "Replace each listed word with a common everyday word, or define it as a key word.",
            sorted(rare)[:MAX_LISTED_OFFENDERS],
        )
    return True, f"Uncommon words are {share:.1%} of the text.", "", []


@_register("LANG-4")
def _paragraph_length(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    limit = params["max_paragraph_sentences"]
    long_ones = [
        p for p in tx.paragraphs(lesson.teaching_text()) if len(tx.sentences(p)) > limit
    ]
    if long_ones:
        return (
            False,
            f"{len(long_ones)} paragraphs have more than {limit} sentences.",
            "Break each listed paragraph into smaller paragraphs.",
            [p[:120] for p in long_ones[:MAX_LISTED_OFFENDERS]],
        )
    return True, "All paragraphs are short.", "", []


@_register("JAR-1")
def _jargon_listed(lesson: Lesson, pack: FactPack, params: dict) -> Outcome:
    body = lesson.teaching_text()
    listed = " | ".join(t.term.lower() for t in lesson.key_terms)
    for short, full in pack.abbreviations.items():
        if tx.contains_term(listed, short) or full.lower() in listed:
            listed += f" | {short.lower()} | {full.lower()}"
    candidates = sorted({term.lower() for term in params["jargon"] + pack.must_define})
    missing = [t for t in candidates if tx.contains_term(body, t) and t not in listed]
    if missing:
        return (
            False,
            f"Technical terms used without a key word entry: {missing}.",
            "Add each listed term to the key words, or replace it with plain language.",
            missing,
        )
    return True, "All technical terms used are in the key words list.", "", []


@_register("JAR-3")
def _key_terms_limits(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    long_defs = [
        t.term
        for t in lesson.key_terms
        if len(tx.words(t.definition)) > params["max_definition_words"]
    ]
    too_many = len(lesson.key_terms) > params["max_terms"]
    if too_many or long_defs:
        return (
            False,
            f"{len(lesson.key_terms)} key words (limit {params['max_terms']}); "
            f"{len(long_defs)} definitions are too long.",
            "Teach fewer new terms and shorten the listed definitions.",
            long_defs,
        )
    return True, f"{len(lesson.key_terms)} key words with short definitions.", "", []


@_register("COV-2")
def _required_sections(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    roles = [s.role.value for s in lesson.sections]
    problems = [r for r in params["required_roles"] if roles.count(r) != 1]
    if problems:
        return (
            False,
            f"Each role must appear exactly once. Wrong count for: {problems}.",
            "Provide exactly one section for each listed role.",
            problems,
        )
    return True, "All required sections are present.", "", []


@_register("COV-3")
def _quiz_present(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    count = len(lesson.quiz)
    blank = [q.question for q in lesson.quiz if not q.question.strip() or not q.answer.strip()]
    if not params["min_questions"] <= count <= params["max_questions"] or blank:
        return (
            False,
            f"{count} questions, {len(blank)} incomplete. Need "
            f"{params['min_questions']}-{params['max_questions']} complete questions.",
            "Provide the required number of questions, each with an answer.",
            blank,
        )
    return True, f"{count} complete questions.", "", []


@_register("FLOW-1")
def _order_and_length(lesson: Lesson, _: FactPack, params: dict) -> Outcome:
    roles = [s.role.value for s in lesson.sections]
    rank = {role: i for i, role in enumerate(params["order"])}
    in_order = all(rank[a] <= rank[b] for a, b in zip(roles, roles[1:], strict=False))
    word_count = len(tx.words(lesson.teaching_text()))
    in_range = params["min_words"] <= word_count <= params["max_words"]
    if in_order and in_range:
        return True, f"Sections in order; {word_count} words.", "", []
    problems = []
    if not in_order:
        problems.append(f"sections are in the order {roles}")
    if not in_range:
        problems.append(f"{word_count} words, needs {params['min_words']}-{params['max_words']}")
    fix = f"Use this section order: {params['order']}." if not in_order else ""
    if word_count < params["min_words"]:
        fix += " Add more teaching, with a further example or explanation in the thinnest sections."
    elif word_count > params["max_words"]:
        fix += " Cut repeated explanations so the lesson fits the word limit."
    return False, "; ".join(problems) + ".", fix.strip(), []


def run_deterministic_checks(lesson: Lesson, pack: FactPack, rubric: Rubric) -> list[CheckResult]:
    return [_run_one(check, lesson, pack) for check in rubric.by_kind("deterministic")]


def _run_one(check: Check, lesson: Lesson, pack: FactPack) -> CheckResult:
    passed, reason, fix, evidence = _REGISTRY[check.id](lesson, pack, check.params)
    return CheckResult(
        check_id=check.id,
        dimension=check.dimension,
        passed=passed,
        reason=reason,
        fix=fix,
        evidence=evidence,
        source="deterministic",
    )


def section_rule_failures(
    section: Section, pack: FactPack, rubric: Rubric, check_ids: tuple[str, ...]
) -> list[CheckResult]:
    """Runs local rule checks on one section, as soon as it has been written."""
    single = Lesson(title="", sections=[section], key_terms=[], quiz=[])
    results = [_run_one(rubric.get(check_id), single, pack) for check_id in check_ids]
    return [r for r in results if not r.passed]


def registered_check_ids() -> set[str]:
    return set(_REGISTRY)
