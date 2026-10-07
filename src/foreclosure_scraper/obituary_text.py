"""Pure text parsing for heir work: obituary survivor lists and probate-notice representatives.

No I/O, no network. Two readers:

  parse_survivors(text)        the "survived by ..." sentences of an obituary, as named relatives
                               with the relation the obituary states ("his wife", "two sons",
                               "a sister"). Unnamed counts ("seven grandchildren") come back as
                               counts, never as people. "Preceded in death by" relatives are read
                               the same way and returned separately: they are not survivors.
  parse_probate_notice(text)   a "Notice to Creditors" style estate notice: the decedent, and each
                               executor / administrator / personal representative with the address
                               the notice itself prints (none is ever looked up or inferred).
  parse_obituary_lede(text)    age, residence, birth and death dates from the opening sentence.

WHAT THESE ARE NOT. A name in a survivor list is what the obituary says, nothing more: it is not a
finding that the person is an heir, is alive today, or is the person of that name in any other
record. Callers label every name a CANDIDATE.

Messy real-world phrasing this handles (see tests/test_obituary_text.py): semicolon and comma lists,
"two sons, John and James Doe" (shared surname), "a daughter, Mary Jones (Bob) of Asheville"
(spouse in parentheses, residence), "son and daughter-in-law, John and Mary Doe", "his wife of
52 years, Jane", "Also surviving are ...", "left to cherish her memory", quoted nicknames,
titles, ages in parentheses, "and husband Bob" (an in-law, kept apart), "numerous nieces and
nephews" (a count, not a name), all-caps notices, and "c/o" attorney addresses in probate notices.
"""
from __future__ import annotations

import html as _html
import re
from typing import Optional

# --------------------------------------------------------------------------- text cleanup

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean_text(raw: Optional[str]) -> str:
    """HTML -> one line of plain text (entities decoded, tags dropped, whitespace collapsed)."""
    t = raw or ""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", " ", t)
    t = _TAG.sub(" ", t)
    t = _html.unescape(t).replace("\xa0", " ")
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", " - ")
    return _WS.sub(" ", t).strip()


# --------------------------------------------------------------------------- relations

#: phrase (regex, lower case, singular or plural) -> normalized relation. Longest first matters:
#: "daughter-in-law" must win over "daughter", "great-grandchildren" over "grandchildren".
_REL_TABLE: list[tuple[str, str]] = [
    (r"great[- ]great[- ]grand(?:children|child|sons?|daughters?)", "great_great_grandchild"),
    (r"great[- ]grand(?:children|child|sons?|daughters?|kids)", "great_grandchild"),
    (r"step[- ]?grand(?:children|child|sons?|daughters?)", "step_grandchild"),
    (r"grand(?:children|child|kids|sons?|daughters?)", "grandchild"),
    (r"daughters?[- ]in[- ]law", "daughter_in_law"),
    (r"sons?[- ]in[- ]law", "son_in_law"),
    (r"sisters?[- ]in[- ]law", "sister_in_law"),
    (r"brothers?[- ]in[- ]law", "brother_in_law"),
    (r"mothers?[- ]in[- ]law", "mother_in_law"),
    (r"fathers?[- ]in[- ]law", "father_in_law"),
    (r"half[- ](?:brothers?|sisters?|siblings?)", "half_sibling"),
    (r"step[- ]?(?:sons?|daughters?|children|child|kids)", "stepchild"),
    (r"step[- ]?(?:mother|father|parents?)", "step_parent"),
    (r"step[- ]?(?:brothers?|sisters?|siblings?)", "step_sibling"),
    (r"wife|husband|spouse", "spouse"),
    (r"companion|partner|significant other|fianc[ée]e?", "companion"),
    (r"sons?", "son"),
    (r"daughters?", "daughter"),
    (r"children|child|kids", "child"),
    (r"brothers?", "brother"),
    (r"sisters?", "sister"),
    (r"siblings?", "sibling"),
    (r"mother|mom", "mother"),
    (r"father|dad", "father"),
    (r"parents", "parent"),
    (r"nephews?", "nephew"),
    (r"nieces?", "niece"),
    (r"aunts?", "aunt"),
    (r"uncles?", "uncle"),
    (r"cousins?", "cousin"),
    (r"godchildren|godchild|god(?:son|daughter)s?", "godchild"),
]
_REL_ALT = "|".join(f"(?:{p})" for p, _ in _REL_TABLE)
_REL_WORD = re.compile(rf"\b(?:{_REL_ALT})\b", re.I)

#: relations that are by marriage to a relative, not a relative of the decedent: never candidates
IN_LAW = {"son_in_law", "daughter_in_law", "sister_in_law", "brother_in_law", "mother_in_law",
          "father_in_law", "in_law"}

_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
                 "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
                 "eighteen": 18, "nineteen": 19, "twenty": 20}
_QUANT = (r"(?:\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
          r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|several|many|"
          r"numerous|a\s+host\s+of|a\s+number\s+of|special|beloved|loving|devoted|dear|precious|"
          r"cherished|adoring|faithful|wonderful|his|her|their|the|our|also|best\s+friend\s+and)")


def relation_of(phrase: str) -> Optional[str]:
    """The normalized relation a phrase names ('two sons' -> 'son'), or None."""
    p = (phrase or "").lower()
    for rx, rel in _REL_TABLE:
        if re.search(rf"\b(?:{rx})\b", p):
            return rel
    return None


def _number_in(phrase: str) -> Optional[int]:
    m = re.search(r"\b(\d{1,3})\b", phrase)
    if m:
        return int(m.group(1))
    for w in re.findall(r"[a-z]+", phrase.lower()):
        if w in _NUMBER_WORDS and w not in ("a", "an"):
            return _NUMBER_WORDS[w]
    return None


# --------------------------------------------------------------------------- clause finding

_TRIGGER = re.compile(
    r"\b(?:(?:is|are|was|were)\s+)?survived\s+by\b|\bsurvivors?\s+(?:include|including|are|is)\b|"
    r"\bsurvivors?\s*:|\balso\s+surviving(?:\s+(?:are|is|him|her|them))?\b|\bsurviving\s+(?:are|is|him|her|them)\b|"
    r"\b(?:left|leaves?)\s+to\s+(?:cherish|mourn|treasure|celebrate)\s+(?:his|her|their)\s+"
    r"(?:memory|memories|life|loss)(?:\s+(?:are|is|include|includes))?\b|"
    r"\b(?:he|she|they)\s+(?:leaves?|left)\s+(?:behind\s+)?(?=(?:his|her|their|a|an|one|two|three|four|five|\d))|"
    r"\bleaves?\s+behind\b|\bthose\s+left\s+(?:behind\s+)?to\s+cherish\s+(?:his|her|their)\s+memory\s+(?:are|include)\b",
    re.I)
_PRECEDED = re.compile(
    r"\b(?:was\s+|is\s+)?(?:preceded|predeceased)\s+in\s+death\s+by\b|\bwas\s+predeceased\s+by\b|"
    r"\bpredeceased\s+by\b|\bjoined\s+in\s+heaven\s+by\b|\breunited\s+(?:in\s+heaven\s+)?with\b",
    re.I)
#: sentences that end a survivor clause (services, memorials, biography restarting, ...)
_STOP = re.compile(
    r"\b(?:funeral|memorial\s+service|services?\s+(?:will|are|was|were)|a\s+service|graveside|"
    r"visitation|the\s+family\s+will|receiving\s+friends|in\s+lieu\s+of|celebration\s+of\s+(?:life|his|her)|"
    r"interment|burial|entombment|inurnment|arrangements|condolences|memorials?\s+(?:may|can)|"
    r"donations|online\s+(?:condolences|guestbook)|a\s+private|he\s+was\s+born|she\s+was\s+born|"
    r"born\s+(?:on|in)\b|he\s+(?:was|loved|enjoyed|worked|served|retired|graduated|attended)\b|"
    r"she\s+(?:was|loved|enjoyed|worked|served|retired|graduated|attended)\b|"
    r"(?:he|she)\s+will\s+be|the\s+family\s+(?:would|wishes|extends)|special\s+thanks|"
    r"rest\s+in\s+peace|may\s+(?:he|she)\b)",
    re.I)
_MAX_CLAUSE = 900

#: a sentence ends at '.', '!' or '?' followed by space and a capital, but not after an initial
#: ('John Q. Doe'), a title or suffix ('Mrs.', 'Jr.'), or a state abbreviation ('N.C. Smith')
_SENT_END = re.compile(
    r"(?<!\b[A-Za-z])(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bJr)(?<!\bSr)(?<!\bSt)(?<!\bRev)(?<!\bLt)"
    r"(?<!\bCol)(?<!\bSgt)(?<!\bMt)(?<!\bFt)(?<!\bNo)(?<!\bVol)[.!?](?=\s+[\"'(]?[A-Z0-9])")


def sentences(text: str) -> list[str]:
    out, last = [], 0
    for m in _SENT_END.finditer(text):
        out.append(text[last:m.end()].strip())
        last = m.end()
    tail = text[last:].strip()
    if tail:
        out.append(tail)
    return [s for s in out if s]


def _opens_with(rx: re.Pattern, sentence: str, words: int = 8) -> bool:
    head = " ".join(sentence.split()[:words])
    return bool(rx.search(head))


def _clause_after(text: str, start: int) -> str:
    """From `start` (just after a survivor trigger) to the end of the survivor clause. The clause is
    the rest of the trigger's sentence plus any following sentence that continues the list
    ('Two brothers, X and Y, also survive.'). It ends at a sentence that opens with a stop phrase
    (services, memorials, biography), a 'preceded in death' or another trigger (read on its own)."""
    seg = text[start:start + _MAX_CLAUSE]
    sents = sentences(seg)
    if not sents:
        return ""
    keep = [sents[0]]
    for s in sents[1:]:
        if _opens_with(_STOP, s) or _opens_with(_PRECEDED, s) or _TRIGGER.search(s):
            break
        if not _REL_WORD.search(" ".join(s.split()[:6])):
            break
        keep.append(s)
    clause = " ".join(keep)
    # a stop phrase or 'preceded in death' INSIDE the first sentence ('..., and a sister; she was
    # preceded in death by ...') ends it there too
    for rx in (_PRECEDED,):
        m = rx.search(clause)
        if m:
            clause = clause[:m.start()]
    return clause.strip(" .;:,")


def survivor_clauses(text: str) -> list[str]:
    t = clean_text(text)
    out, seen = [], set()
    for m in _TRIGGER.finditer(t):
        c = _clause_after(t, m.end())
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def predeceased_clauses(text: str) -> list[str]:
    t = clean_text(text)
    out = []
    for m in _PRECEDED.finditer(t):
        sents = sentences(t[m.end():m.end() + 600])
        if not sents:
            continue
        c = sents[0]
        tm = _TRIGGER.search(c)
        if tm:
            c = c[:tm.start()]
        c = c.strip(" .;:,")
        if c:
            out.append(c)
    return out


# --------------------------------------------------------------------------- names

_TITLES = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Rev|Reverend|Pastor|Elder|Deacon|Sgt|Capt|Col|Lt|Maj|"
                     r"Judge|Hon|Honorable|Sister|Brother)\.?\s+(?=[A-Z])")
_SUFFIX = re.compile(r",?\s+(Jr|Sr|JR|SR|II|III|IV|V)\.?\s*$")
_NICK = re.compile(r"\s*[\"']([A-Z][A-Za-z.\- ]{0,20})[\"']\s*")
_PAREN = re.compile(r"\s*\(([^)]{0,60})\)\s*")
_RESIDENCE = re.compile(
    r"\s*,?\s*\b(?i:(?:all|both)\s+)?(?i:of|from|in|residing\s+in|who\s+resides?\s+in)\s+"
    r"(?:the\s+home\b|[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,3})"
    r"(?:\s*,?\s*(?:[A-Z]{2}|N\.?\s?C\.?|S\.?\s?C\.?|North Carolina|South Carolina|Georgia|Tennessee|Virginia|"
    r"Florida|Texas|California|Ohio|[A-Z][a-z]+))?\b.*$")
_INLAW_TAIL = re.compile(r"\s*,?\s*(?:and|&)\s+(?:his|her)?\s*(?:wife|husband|spouse|partner|fianc[ée]e?)\b.*$", re.I)
_PARTICLES = {"de", "da", "del", "della", "der", "di", "du", "la", "le", "van", "von", "st", "st."}
_NAME_WORD = re.compile(r"^(?:[A-Z][A-Za-z'\-]*\.?|[A-Z]\.|Mc[A-Z][a-z]+|O'[A-Z][a-z]+)$")
_BAD_NAME_WORDS = {"And", "The", "His", "Her", "Their", "Of", "In", "Many", "Several", "Numerous",
                   "Special", "Friends", "Friend", "Family", "Church", "Grandchildren", "Children",
                   "Nieces", "Nephews", "Cousins", "Great", "Also", "Other", "Others", "Host",
                   "Survived", "Preceded", "Death", "Home", "Lord", "God", "Jesus", "Heaven", "Mother",
                   "Father", "Sister", "Brother", "Wife", "Husband", "Son", "Daughter", "Both",
                   "All", "Two", "Three", "Four", "Five", "One", "Loving", "Beloved", "Devoted"}


def _title_caps(s: str) -> str:
    """'URSULA ABERNATHY KEMP OF KINGS MOUNTAIN' -> 'Ursula Abernathy Kemp of Kings Mountain'
    (all-caps notices). Roman suffixes and single initials stay as they are."""
    small = {"OF", "AND", "IN", "FROM", "BOTH", "ALL", "HIS", "HER", "THEIR", "THE", "A", "AN"}
    out = []
    for w in s.split():
        core = w.strip(",.;:()\"'")
        if core in ("II", "III", "IV") or len(core) == 1:
            out.append(w)
        elif core in small:
            out.append(w.lower())
        elif core.startswith("MC") and len(core) > 3:
            out.append(w.replace(core, "Mc" + core[2:].capitalize()))
        else:
            out.append("-".join(x.capitalize() for x in w.split("-")).replace("'S", "'s"))
    return " ".join(out)


def tidy_name(piece: str) -> tuple[Optional[str], dict]:
    """One list piece -> (a person's name as written, notes). None when the piece is not a name
    ('numerous nieces', 'of Asheville', 'and many friends')."""
    notes: dict = {}
    s = piece.strip(" ,;:.-")
    if not s:
        return None, notes
    if sum(c.isupper() for c in s) > 3 and not any(c.islower() for c in s):
        s = _title_caps(s)
    m = _INLAW_TAIL.search(s)
    if m:
        notes["with_spouse_text"] = True
        s = s[:m.start()]
    nick = _NICK.search(s)
    if nick:
        notes["nickname"] = nick.group(1).strip()
        s = (s[:nick.start()] + " " + s[nick.end():]).strip()
    for pm in list(_PAREN.finditer(s)):
        inner = pm.group(1).strip()
        if re.fullmatch(r"\d{1,3}", inner):
            notes["age"] = int(inner)
        elif inner:
            notes.setdefault("parenthetical", []).append(inner)
    s = _PAREN.sub(" ", s)
    s = _RESIDENCE.sub("", s)
    s = re.sub(r"\s*,?\s*\b(?:age|aged)\s+\d{1,3}\b.*$", "", s, flags=re.I)
    s = re.sub(r",?\s*\d{1,3}\s*$", "", s)
    s = _TITLES.sub("", s)
    suf = None
    sm = _SUFFIX.search(s)
    if sm:
        suf = sm.group(1)
        s = s[:sm.start()] + s[sm.end():]
    s = _WS.sub(" ", s).strip(" ,;:.-")
    words = s.split()
    if not words or len(words) > 5:
        return None, notes
    for w in words:
        if w.lower() in _PARTICLES:
            continue
        if not _NAME_WORD.match(w) or w.strip(".") in _BAD_NAME_WORDS:
            return None, notes
    if len(words) == 1 and len(words[0].strip(".")) < 2:
        return None, notes
    if s.isupper() and len(s) > 3:
        s = " ".join(w.capitalize() if len(w) > 2 else w for w in words)
    if suf:
        s = f"{s} {suf}."  if suf in ("Jr", "Sr") else f"{s} {suf}"
    return s, notes


def _split_names(rest: str) -> list[str]:
    """'John Doe (Mary) of Asheville, Jane Smith and Bob Jones' -> pieces. Commas inside
    parentheses and 'of City, ST' tails do not split."""
    protected = re.sub(r"\(([^)]*)\)", lambda m: "(" + m.group(1).replace(",", "\x00") + ")", rest)
    # "of Asheville, NC" / "of Marion, N.C." keep the state with the residence
    protected = re.sub(r"(\b(?:of|in|from)\s+[A-Z][A-Za-z.'\- ]{1,40}),\s*(?=(?:[A-Z]{2}|N\.\s?C\.|S\.\s?C\.|"
                       r"North Carolina|South Carolina|Georgia|Tennessee|Virginia|Florida)\b)",
                       lambda m: m.group(1) + "\x00", protected)
    parts = re.split(r",|;|\s+&\s+|\s+and\s+(?!(?:his|her)\s+(?:wife|husband|spouse)\b)(?!(?:wife|husband|spouse)\b)",
                     protected, flags=re.I)
    return [p.replace("\x00", ",").strip() for p in parts if p and p.strip(" ,;.")]


#: a relation phrase at the head of a segment: 'his loving wife of 52 years,' / 'two sons,'
_HEAD = re.compile(
    rf"^\s*(?:and\s+|also\s+)?(?:(?:are|is|include|includes|including)\s+)?(?:{_QUANT}\s+)*(?P<rel>(?:{_REL_ALT})"
    rf"(?:\s*(?:,|and|&)\s*(?:{_QUANT}\s+)*(?:{_REL_ALT}))*)"
    rf"(?:\s+of\s+(?:\d+|[a-z\-]+)\s+(?:years?|yrs?\.?|months?|decades?))?(?:\s*(?:,|:|-)\s*|\s+|$)",
    re.I)


def _segments(clause: str) -> list[str]:
    """Split a survivor clause into one segment per stated relation.

    Semicolons are the strongest separator. Inside a semicolon part, a new relation phrase that
    follows a comma or 'and' starts a new segment ('his wife Jane, two sons John and Bob, and a
    sister Ann')."""
    out: list[str] = []
    for part in re.split(r";|\.\s+(?=(?:Also|Additional|He|She|They|Surviving)\b)", clause):
        part = part.strip(" ,.")
        if not part:
            continue
        cuts = [0]
        for m in _REL_WORD.finditer(part):
            if m.start() == 0:
                continue
            before = part[:m.start()]
            # a relation word directly after a separator (+ quantifier/possessive) opens a segment
            tail = before[-40:]
            if re.search(rf"(?:,|\band\b|&|:)\s*(?:{_QUANT}\s+)*$", tail, re.I) and not re.search(
                    r"\b(?:and|&)\s+(?:his|her)?\s*$", tail, re.I) or re.search(r";\s*$", tail):
                cuts.append(m.start() - len(re.search(rf"(?:(?:{_QUANT})\s+)*$", before, re.I).group(0)))
        cuts = sorted(set(c for c in cuts if c >= 0))
        for a, b in zip(cuts, cuts[1:] + [len(part)]):
            seg = part[a:b].strip(" ,.&")
            seg = re.sub(r"^(?:and|&)\s+", "", seg, flags=re.I)
            if seg:
                out.append(seg)
    return out


def _parse_segment(seg: str, surname_hint: Optional[str]) -> tuple[list[dict], list[dict]]:
    """One relation segment -> (named people, unnamed counts)."""
    people: list[dict] = []
    counts: list[dict] = []
    m = _HEAD.match(seg)
    if not m:
        return people, counts
    head = seg[:m.end()]
    rel_phrase = m.group("rel")
    rels = [relation_of(r) for r in re.split(r"\s*(?:,|\band\b|&)\s*", rel_phrase) if relation_of(r)]
    rest = seg[m.end():].strip(" ,:;.-")
    if not rels:
        return people, counts
    # "his wife of 52 years" can leave "of 52 years," in rest when the HEAD regex missed it
    rest = re.sub(r"^of\s+\d+\s+(?:years?|yrs?\.?)\s*,?\s*", "", rest, flags=re.I)
    pieces = _split_names(rest) if rest else []
    names: list[tuple[str, dict]] = []
    for p in pieces:
        nm, notes = tidy_name(p)
        if nm:
            names.append((nm, notes))
    if not names:
        n = _number_in(head)
        counts.append({"relation": rels[0], "count": n, "named": False, "phrase": seg[:80]})
        return people, counts
    # shared surname: 'sons John and James Doe' / 'John, Bill & Sue Smith'
    last_multi = names[-1][0].split() if names else []
    for i, (nm, notes) in enumerate(names):
        if len(nm.split()) == 1 and len(last_multi) >= 2 and i < len(names) - 1 \
                and not notes.get("parenthetical"):
            surname = last_multi[-1] if last_multi[-1].rstrip(".") not in ("Jr", "Sr", "II", "III", "IV") \
                else last_multi[-2]
            names[i] = (f"{nm} {surname}", {**notes, "surname_from_list": True})
    paired = len(rels) > 1 and len(rels) == len(names)
    for i, (nm, notes) in enumerate(names):
        rel = rels[i] if paired else rels[0]
        person = {"name": nm, "relation": rel}
        if len(nm.split()) == 1:
            person["surname_stated"] = False
        if notes.get("surname_from_list"):
            person["surname_from_list"] = True
        if notes.get("nickname"):
            person["nickname"] = notes["nickname"]
        if notes.get("age") is not None:
            person["age"] = notes["age"]
        if notes.get("parenthetical"):
            person["parenthetical"] = notes["parenthetical"]
        people.append(person)
        if notes.get("with_spouse_text"):
            # 'Mary Jones and husband Bob': Bob is the relative's spouse (an in-law)
            sp = re.search(r"(?:and|&)\s+(?:his|her)?\s*(?:wife|husband|spouse|partner)\s*,?\s*"
                           r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,3})", pieces[i] if i < len(pieces) else "")
            if sp:
                inl, _ = tidy_name(sp.group(1))
                if inl:
                    people.append({"name": inl, "relation": "in_law", "spouse_of": nm})
    if surname_hint:
        pass
    return people, counts


def _parse_clauses(clauses: list[str], surname_hint: Optional[str]) -> dict:
    people: list[dict] = []
    counts: list[dict] = []
    for c in clauses:
        for seg in _segments(c):
            p, k = _parse_segment(seg, surname_hint)
            people += p
            counts += k
    # one entry per (name, relation)
    seen, uniq = set(), []
    for p in people:
        key = (p["name"].lower(), p["relation"])
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return {"people": uniq, "counts": counts}


def parse_survivors(text: Optional[str], decedent_surname: Optional[str] = None) -> dict:
    """{'survivors': [{name, relation, ...}], 'unnamed': [{relation, count}], 'predeceased': [...],
    'clauses': n}. Every name is what the obituary prints, relation as it states it."""
    clauses = survivor_clauses(text or "")
    surv = _parse_clauses(clauses, decedent_surname)
    pre = _parse_clauses(predeceased_clauses(text or ""), decedent_surname)
    pre_names = {p["name"].lower() for p in pre["people"]}
    # a person named in both lists is read as predeceased (the obituary lists the dead first)
    survivors = [p for p in surv["people"] if p["name"].lower() not in pre_names]
    return {"survivors": survivors, "unnamed": surv["counts"], "predeceased": pre["people"],
            "clauses": len(clauses)}


# --------------------------------------------------------------------------- obituary lede

_MONTHS = (r"January|February|March|April|May|June|July|August|September|October|November|December|"
           r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?")
_DATE = rf"(?:(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})"
_DIED = re.compile(rf"\b(?:passed\s+away|died|went\s+to\s+be\s+with\s+the\s+Lord|entered\s+(?:into\s+)?"
                   rf"(?:eternal\s+rest|heaven)|departed\s+this\s+life|went\s+home\s+to\s+be\s+with\s+"
                   rf"(?:the|her|his)\s+Lord)\b[^.]{{0,80}}?\b({_DATE})", re.I)
_BORN = re.compile(rf"\bborn\b[^.]{{0,60}}?\b({_DATE})", re.I)
_AGE = re.compile(r"^[^,]{3,80},\s*(?:age\s+)?(\d{1,3}),|\b(?:age|aged)\s+(\d{1,3})\b|\bat\s+the\s+age\s+of\s+(\d{1,3})\b",
                  re.I)
_OF = re.compile(r"^[^,]{3,80},\s*(?:age\s+)?\d{1,3},\s*of\s+([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,3})")


def parse_obituary_lede(text: Optional[str]) -> dict:
    t = clean_text(text)
    out: dict = {}
    m = _AGE.search(t[:600])
    if m:
        age = int(next(g for g in m.groups() if g))
        if 0 < age <= 120:
            out["age"] = age
    d = _DIED.search(t)
    if d:
        out["death_date_text"] = d.group(1)
    b = _BORN.search(t)
    if b:
        out["birth_date_text"] = b.group(1)
    o = _OF.search(t[:400])
    if o:
        out["residence"] = o.group(1)
    return out


# --------------------------------------------------------------------------- probate notices

_ROLE_WORDS = (r"(?i:Co-?\s?Executors?|Co-?\s?Executrix(?:es)?|Co-?\s?Administrators?|Co-?\s?Administratrix|"
               r"Executors?|Executrix|Executrices|Administrators?(?:\s+(?:CTA|C\.T\.A\.|DBN|D\.B\.N\.))?|"
               r"Administratrix|Ancillary\s+(?:Executor|Administrator)|Collectors?(?:\s+by\s+Affidavit)?|"
               r"(?:Co-?\s?)?Personal\s+Representatives?|Successor\s+Personal\s+Representative|"
               r"Public\s+Administrator)")
_NAME = r"[A-Z][A-Za-z.'\-]+(?:\s+(?:[A-Z][A-Za-z.'\-]+|[A-Z]\.)){1,4}(?:,?\s+(?:Jr|Sr|II|III|IV)\.?)?"
_DECEDENT = re.compile(
    r"\b(?i:(?:the\s+)?estate\s+of)\s*:?\s*(" + _NAME + r")(?=\s*,?\s*(?:(?i:a/k/a|aka|deceased|late\s+of|who\s+died|"
    r"of\s+\w+\s+county|this\b|hereby\b|notice\b|date\b|case\b)|\(|\n|$))|"
    r"\b(?i:estate)\s*:\s*(" + _NAME + r")(?=\s*(?:(?i:date|case|death|personal|pr\b)|\n|$))")
_DOD = re.compile(rf"\b(?i:date\s+of\s+death|dod|death|died\s+on|who\s+died)\s*:?\s*({_DATE}|\d{{1,2}}-\d{{1,2}}-\d{{2,4}})",
                  re.I)
_CASE = re.compile(r"\b(\d{4}\s?ES\s?\d{5,10}|\d{2}\s?E\s?\d{1,6}|\d{2,4}\s?-?\s?E\s?(?:S|ST)\s?-?\s?\d{2,6})\b", re.I)
_ADDRESS = re.compile(
    r"((?i:c/o)\s+[^,]{3,80},\s*)?((?:\d{1,6}\s+[A-Za-z0-9.'\- ]{2,60}?|(?i:P\.?\s?O\.?\s+Box)\s+\d+|(?i:Post\s+Office\s+Box)\s+\d+)"
    r"(?:,?\s*(?i:Suite|Ste\.?|Apt\.?|Unit|#)\s*[\w-]+)?"
    r",?\s+[A-Z][A-Za-z.'\- ]{2,30},?\s+(?:N\.?\s?C\.?|S\.?\s?C\.?|North\s+Carolina|South\s+Carolina|[A-Z]{2})\.?\s+\d{5}(?:-\d{4})?)")
_UNDERSIGNED = re.compile(r"\b(?i:(?:the\s+)?undersigned),?\s+(" + _NAME + r"),\s*(?i:having|as)\b")
_QUALIFIED = re.compile(rf"\b(?i:having\s+qualified\s+as\s+(?:the\s+)?)({_ROLE_WORDS})\b")
_PR_LABEL = re.compile(rf"\b(?:{_ROLE_WORDS}|PR)\s*:\s*(" + _NAME + r")(?=\s*(?:,|\n|(?i:address)|$|\d|(?i:p\.?\s?o)))")
_SIG = re.compile(r"(" + _NAME + rf")\s*,\s*({_ROLE_WORDS})\b")
_ATTORNEY = re.compile(r"\b(?:attorney|counsel|law\s+(?:firm|office|group)|PLLC|P\.A\.|LLP|Esq)\b", re.I)


def _norm_role(role: str) -> str:
    r = re.sub(r"\s+", " ", role.strip()).lower().replace("co ", "co-")
    co = "co-" if r.startswith("co-") or r.startswith("co") and not r.startswith("col") else ""
    for key, name in (("personal representative", "personal representative"), ("executri", "executrix"),
                      ("executor", "executor"), ("administratrix", "administratrix"),
                      ("administrator", "administrator"), ("collector", "collector")):
        if key in r:
            return co + name
    return r


def _address_after(text: str, start: int, window: int = 60) -> Optional[dict]:
    """The address a notice prints right after a representative's name (within `window`
    characters), with a note when it is printed in care of an attorney or firm."""
    tail = text[start:start + 260]
    am = _ADDRESS.search(tail)
    if not am or am.start() > window:
        return None
    co, addr = am.group(1), am.group(2)
    full = re.sub(r"\s+", " ", ((co or "") + addr)).strip(" ,")
    out = {"address": full}
    if co or _ATTORNEY.search(tail[:am.start()]):
        out["address_note"] = "the notice prints this address in care of an attorney or firm"
    return out


def parse_probate_notice(text: Optional[str]) -> dict:
    """{'decedent', 'date_of_death', 'case_number', 'representatives': [{name, role, address?,
    address_note?}]}. The address is kept only when the notice prints one right after the
    representative's name (or under a PR / Address label); a 'c/o' attorney address is kept and
    labelled as such. Nothing is inferred."""
    raw = text or ""
    lines = "\n" in raw
    t = clean_text(raw)
    out: dict = {"decedent": None, "date_of_death": None, "case_number": None, "representatives": []}
    if not re.search(r"notice\s+to\s+creditors|creditors|qualified\s+as|personal\s+representative|estate\s+of|"
                     r"estate\s*:", t, re.I):
        return out
    src = raw if lines else t
    dm = _DECEDENT.search(src)
    if dm:
        nm = next(g for g in dm.groups() if g)
        out["decedent"] = tidy_name(nm)[0] or nm.strip(" ,.")
    d = _DOD.search(t)
    if d:
        out["date_of_death"] = d.group(1)
    c = _CASE.search(t)
    if c:
        out["case_number"] = re.sub(r"\s+", "", c.group(1))
    role_q = _QUALIFIED.search(t)
    default_role = _norm_role(role_q.group(1)) if role_q else None
    reps: list[dict] = []

    def add(name: str, role: Optional[str], addr: Optional[dict]) -> None:
        nm, _ = tidy_name(name)
        if not nm or _ATTORNEY.search(name):
            return
        if out["decedent"] and nm.lower() == str(out["decedent"]).lower():
            return
        for r in reps:
            if r["name"].lower() == nm.lower():
                if addr and "address" not in r:
                    r.update(addr)
                return
        rep = {"name": nm, "role": role or default_role or "personal representative"}
        if addr:
            rep.update(addr)
        reps.append(rep)

    # labelled form (SC): 'Personal Representative: NAME' then 'Address: ...' on the next lines
    for m in _PR_LABEL.finditer(src):
        label = m.group(0).split(":")[0].strip()
        role = "personal representative" if label.upper() == "PR" else _norm_role(label)
        after = clean_text(src[m.end():m.end() + 260])
        after = re.sub(r"^(?i:address)\s*:\s*", "", after.strip(" ,"))
        am = _ADDRESS.search(after)
        addr = None
        if am and am.start() <= 20:
            addr = {"address": re.sub(r"\s+", " ", (am.group(1) or "") + am.group(2)).strip(" ,")}
        add(m.group(1), role, addr)
    # 'Personal Representative:' with the name on the next line (Pickens style)
    for m in re.finditer(rf"\b({_ROLE_WORDS}|PR)\s*:\s*\n\s*(" + _NAME + r")\s*\n", raw):
        after = clean_text(raw[m.end():m.end() + 260])
        after = re.sub(r"^(?i:address)\s*:\s*", "", after)
        am = _ADDRESS.search(after)
        addr = {"address": re.sub(r"\s+", " ", (am.group(1) or "") + am.group(2)).strip(" ,")} \
            if am and am.start() <= 20 else None
        add(m.group(2), "personal representative" if m.group(1).upper() == "PR" else _norm_role(m.group(1)), addr)
    um = _UNDERSIGNED.search(t)
    if um:
        add(um.group(1), default_role, _address_after(t, um.end(), window=10))
    for m in _SIG.finditer(t):
        nxt = t[m.end():m.end() + 40]
        if re.match(r"\s*(?i:of\s+the\s+estate)", nxt) and re.search(r"(?i:qualified\s+as\s*(?:the\s+)?)$",
                                                                       t[max(0, m.start() - 40):m.start()]):
            continue
        add(m.group(1), _norm_role(m.group(2)), _address_after(t, m.end()))
    out["representatives"] = reps
    return out
