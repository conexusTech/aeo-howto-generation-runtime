"""The house voice rules, in one place, for both the prompt and the check.

Two readers, one source. The prompt text below is GENERATED from these same
constants, so "the prompt names what the detector looks for" is true by
construction rather than by somebody remembering. A previous change in this
repo shipped instructions whose only reader was a human: reverting the prose
left every test green while the model was told the opposite of the schema.

⚠️ **THIS RUNTIME SERVES EVERY TRADE, AND THAT RULES OUT MOST OF A GOOD
AI-TELL LIST.** The house list flags abstract metaphor nouns -- substrate,
harness, scaffolding, ratchet, wedge, flywheel, bedrock, vector, surface,
primitive, tapestry, landscape. Every one of those is LITERAL vocabulary for
some business we generate for:

    harness      a wiring harness            scaffolding  a builder's platform
    ratchet      a hand tool                 wedge        a hand tool
    flywheel     an engine part              bedrock      what a landscaper digs to
    substrate    flooring and print stock    landscape    a landscaper's whole trade
    tapestry     an upholsterer's material   surface      a worktop or a road

So they are NOT in the automated detector. Flagging them would fire on correct
copy for a real customer, and a check with that false-positive rate teaches
people to ignore it. They stay in the prompt, where the model has the trade in
front of it and can tell a wiring harness from a metaphor.

`NOT_AUTOMATED` records each exclusion with the word that forced it, so the
next person can see this was a decision rather than an oversight.
"""

from __future__ import annotations

import re

#: Characters that mark machine-written text on sight. Absolute, every tier.
#: The em dash is the strongest single signal in the house rules; curly quotes
#: come from the same generator defaults.
BANNED_CHARACTERS: tuple[tuple[str, str], ...] = (
    ("—", "a period or a comma"),
    ("–", "a period or a comma"),
    ("‘", "a straight apostrophe"),
    ("’", "a straight apostrophe"),
    ("“", "a straight quote"),
    ("”", "a straight quote"),
)

#: Multi-word tells. Safe across every trade because the PHRASE carries the
#: tell, not any single word in it: a flooring business may write "surface",
#: but none of them writes "in today's fast-paced world".
PHRASE_TELLS: tuple[str, ...] = (
    # signposting -- announcing the writing instead of doing it
    "let's dive in",
    "let's break this down",
    "let's take a look",
    "here's what you need to know",
    "in this article",
    "in this guide",
    "by the end of this",
    "in today's fast-paced",
    "in today's world",
    # puffery
    "testament to",
    "pivotal moment",
    "evolving landscape",
    "setting the stage",
    "indelible mark",
    "plays a vital role",
    "plays a crucial role",
    "when it comes to",
    # vague attribution -- we are forbidden from inventing facts anyway, so
    # these phrases can only ever be dressing on something unsourced
    "experts believe",
    "experts agree",
    "industry reports suggest",
    "studies show",
    "research suggests",
    "it is widely known",
    # the "not just X but Y" family
    "not just about",
    "not only about",
    "isn't just",
    "is not just",
    # authority tropes -- ceremony in front of an ordinary point
    "the real question is",
    "at its core",
    "what really matters",
    "the deeper issue",
    # filler
    "it is important to note",
    "it's important to note",
    "it is worth noting",
    "due to the fact that",
    "in order to",
    # chatbot leakage
    "i hope this helps",
    "let me know if",
    "great question",
    # generic conclusion
    "the future looks bright",
    "at the end of the day",
    "rest assured",
)

#: Single words, kept to ones that are not a tool, a part, a material or a
#: trade anywhere. Each was checked against "could a real business write this
#: about its own work?" before being included.
WORD_TELLS: tuple[str, ...] = (
    "delve",
    "crucial",
    "utilize",
    "utilise",
    "furthermore",
    "moreover",
    "seamless",
    "seamlessly",
    "myriad",
    "plethora",
    "breathtaking",
    "groundbreaking",
    "unparalleled",
    "meticulous",
    "meticulously",
    "elevate",
    "elevating",
    "unlock",
    "unlocking",
)

#: Rules from the house list deliberately left to the model's judgement, with
#: the trade word that makes each unsafe to automate here.
NOT_AUTOMATED: tuple[tuple[str, str], ...] = (
    ("abstract metaphor nouns", "harness, ratchet, wedge, flywheel, substrate"),
    ("landscape as an abstraction", "a landscaper's actual trade"),
    ("tapestry as an abstraction", "an upholsterer's material"),
    ("surface as an abstraction", "a worktop, a road, a wall"),
    ("nestled", "a part genuinely sits nestled behind another"),
    ("leverage", "physical leverage is how half these jobs get done"),
    ("enhance", "too ordinary in plain copy to flag without noise"),
    ("rule of three", "structure, not wording -- no reliable text signal"),
    ("boldface and heading case", "markdown styling, not prose"),
)


def _word_pattern(word: str) -> re.Pattern[str]:
    """Word-boundary, plural-tolerant, and NOT a substring match.

    ⚠️ A substring check here is the bug this repo has already paid for once:
    `tire` matches `entire`, and `car` matches `carry` and `character`. The
    lookarounds are what make the difference between a finding and a false
    alarm.
    """
    return re.compile(
        r"(?<![a-z])" + re.escape(word) + r"(?:s|es|d|ed|ing)?(?![a-z])",
        re.IGNORECASE,
    )


_WORD_PATTERNS = tuple((w, _word_pattern(w)) for w in WORD_TELLS)


def find_tells(text: str) -> list[str]:
    """Every house-voice tell present in `text`, sorted, deduplicated.

    Returns names, not positions: this is a signal for an operator reviewing a
    draft, not a linter with line numbers. An empty list is the ordinary case.
    """
    if not isinstance(text, str) or text == "":
        return []

    found: set[str] = set()

    for char, _ in BANNED_CHARACTERS:
        if char in text:
            found.add("character:" + char)

    # ⚠️ Curly punctuation is FOLDED to straight before phrase matching, and
    # this is a fix rather than tidiness. `PHRASE_TELLS` holds straight
    # apostrophes, so `Let's dive in` typed with a curly one matched nothing --
    # the character rule fired and the phrase rule silently did not. Found by
    # probing the detector rather than by reading it, on the first run.
    lowered = text.lower()
    for curly in ("‘", "’"):
        lowered = lowered.replace(curly, "'")
    for curly in ("“", "”"):
        lowered = lowered.replace(curly, '"')

    for phrase in PHRASE_TELLS:
        if phrase in lowered:
            found.add("phrase:" + phrase)

    for word, pattern in _WORD_PATTERNS:
        if pattern.search(text):
            found.add("word:" + word)

    return sorted(found)


def voice_rules_for_prompt() -> str:
    """The WRITING VOICE section of the prompt, built from the lists above.

    Generated rather than written out so the instruction and the check cannot
    drift apart. The examples are deliberately trade-neutral: this string is
    part of the baseline prompt, and a baseline that names one industry is the
    defect `tests/test_industry_neutral.py` exists to catch.
    """
    chars = ", ".join(
        "%s (use %s)" % (char, instead) for char, instead in BANNED_CHARACTERS
    )
    phrases = "; ".join(PHRASE_TELLS)
    words = ", ".join(WORD_TELLS)

    # 🔴 `NOT_AUTOMATED` is documentation for whoever reads THIS FILE, and it
    # deliberately does NOT reach the prompt. Its examples are concrete trade
    # nouns -- harness, ratchet, flywheel, substrate -- and interpolating them
    # would drop mechanical vocabulary into the baseline every business shares,
    # including a dental practice's. That is prompt contamination toward one
    # trade, which is the exact defect `tests/test_industry_neutral.py` exists
    # to catch; it does not catch this one because its word list is
    # automotive-specific and these words are not on it.
    #
    # The model gets the RULE without the examples. It has the trade in front
    # of it and does not need ours.

    return """\
WRITE LIKE A PERSON AT THIS BUSINESS, NOT LIKE A CONTENT MILL.
A customer reading this should not be able to tell it was generated. That is a
requirement, not a preference: the whole point of the article is that the
business can put its own name on it.

NEVER use these characters: %s.

NEVER use these phrases: %s.

NEVER use these words: %s.

Say what a thing IS and DOES. "This is" rather than "this serves as" or "this
stands as". Name the actor: "the technician checks the seal", not "the seal is
checked". Cut an adverb propping up a weak verb -- if you need "significantly",
the verb is wrong or a number belongs there.

Vary the rhythm. Some sentences short. Others take longer to arrive somewhere,
the way a person explaining their own work does. Every sentence the same length
is the clearest sign nobody wrote it.

Do not force ideas into threes. Use the number there actually are, even when it
is two or five.

Do not announce what you are about to say. Say it.

Use plain words. "use" not "utilize", "help" not "facilitate", "many" not
"numerous", "if" not "in the event that", "to" not "in order to".

REVIEW YOUR OWN COPY BEFORE YOU EMIT IT. Read each section back and ask: would
a customer think a person at this business wrote this? If a sentence could
appear unchanged in another business's article, it says nothing about this one
-- cut it or make it specific. Then fix what you find, and only then call the
tool.

One rule needs your judgement rather than a list. A word that is a real tool,
part, material or task in THIS trade is a real word: write it plainly when you
mean the thing. Avoid the same word when you mean it as a metaphor or an
abstraction. Nobody can give you that list from outside your trade, which is
why it is yours to apply.
""" % (chars, phrases, words)
