"""What a recorded value or target *means*, so a test can run more than once.

A recording says what somebody did. Replayed literally, it asks the application
to do that same thing again - create the same account, take the same item, book
the same slot - and a great many applications are right to refuse. The run goes
red against software that is working perfectly, on the second run and every run
after it, which is the most expensive way for a test to be wrong: it is red for
a reason nobody can act on, so within a fortnight nobody looks.

The fix is not to ignore the refusal. It is to notice that the recording never
meant "this exact account". It meant "an account", and the address in it was
one example of one. So every recorded value and every recorded target is given
a *role* saying how faithfully it has to be reproduced:

    STATIC            reproduce it exactly - a password, a search term, a country
    UNIQUE            must be new each run - the application rejects a duplicate
    EXISTING          must already be there - a credential, a saved record
    STATE_DEPENDENT   one of a set whose members come and go - an item, a slot
    UNKNOWN           not enough evidence, so reproduce it exactly

Nothing here knows what any application sells, books or registers. Every signal
is structural - how many elements a selector matched, whether a form carries a
password, whether a field describes itself with `autocomplete` - or is the
application's own words about what just happened. The same rules decide a
shopping cart, a room booking, a customer record and a seat reservation,
because none of the rules can tell those apart in the first place.

Two things this file is careful *not* to do.

It does not decide anything at run time. A role is worked out once, while the
suite is generated, from evidence that is all in the recording; the generated
test carries the answer rather than re-deriving it against a live page. A test
that reclassifies its own data mid-run is a test that can talk itself into
anything.

And a role is permission, never instruction. STATE_DEPENDENT does not mean "use
a different item"; it means "if, and only if, this step is refused, a different
member of the set may be tried". The recorded value is always what runs first.
See `templates/state.py.j2` for the half that decides whether a refusal really
happened, and `RECOVERABLE` below for the roles allowed to act on one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.models.enums import ActionType, SelectorStrategy


class DataRole(str, Enum):
    """How faithfully a recorded value or target has to be reproduced."""

    STATIC = "static"
    UNIQUE = "unique"
    EXISTING = "existing"
    STATE_DEPENDENT = "state_dependent"
    UNKNOWN = "unknown"


#: The roles a test is allowed to vary when a step is refused. The other three
#: are all forms of "reproduce it exactly", and a step that fails on one of them
#: has failed - see the recovery gate in `templates/state.py.j2`.
RECOVERABLE = frozenset({DataRole.UNIQUE, DataRole.STATE_DEPENDENT})

#: How sure a UNIQUE has to be before the recorded value is replaced *before*
#: the test runs, rather than only after the application has refused it.
#:
#: The distinction is the difference between a test that reproduces the
#: recording and one that improves on it. Below the line, the recorded value
#: still runs first and is only replaced once the application says it will not
#: accept it - which costs one round trip and gives up nothing, because the
#: evidence arrives before anything is changed. Above it, the recording itself
#: shows the value being consumed - a form that asked for it twice, an address
#: that only creates - and replaying it would fail every run for a reason
#: already known at generation time.
SUBSTITUTE_ABOVE = 0.8


@dataclass(frozen=True)
class Decision:
    """A role, and why - in a sentence that goes into the generated code.

    The reason is not decoration. Somebody reading a generated test needs to
    know why one line replays a recorded address and the next invents one, and a
    role name on its own does not tell them.
    """

    role: DataRole
    why: str
    confidence: float = 1.0
    #: For STATE_DEPENDENT only: (strategy, value) of the recorded selector that
    #: other elements of the same shape also answer to. This is what the test
    #: reaches for after a refusal, and nothing else ever reads it.
    shape: tuple[str, str] | None = None

    @property
    def recoverable(self) -> bool:
        return self.role in RECOVERABLE


STATIC = Decision(DataRole.STATIC, "reproduced as recorded")
UNKNOWN = Decision(DataRole.UNKNOWN, "not enough evidence, so reproduced as recorded")


# ---------------------------------------------------------------------------
# What an application says when it will not do the same thing twice
# ---------------------------------------------------------------------------
#: A refusal on the grounds that the data or the state is already the way the
#: request wants it. This is a vocabulary of *refusal*, not of any domain: it
#: says nothing about carts, rooms, courses or customers, and every phrase in it
#: would read the same on any of them.
#:
#: Deliberately about collision and availability only. "Invalid", "required" and
#: "too short" are all absent, and their absence is the point - those are the
#: application telling you the data is wrong, which is a real finding, not a
#: reason to try different data until one gets through.
CONFLICT = re.compile(
    r"already\s+(been\s+)?"
    r"(exist|taken|register|use|in\s+use|purchas|bought|own|book|reserv|enroll|enrol"
    r"|subscrib|assign|claim|apply|applied|added|selected|member)"
    r"|\b(is|are|has|have)\s+already\b"
    r"|\bduplicate\b"
    r"|\balready\s+\w+ed\b"
    r"|\b(not|no longer|currently\s+not)\s+available\b"
    r"|\bunavailable\b"
    r"|\bout\s+of\s+stock\b"
    r"|\bsold\s+out\b"
    r"|\bfully\s+booked\b"
    r"|\bno\s+(longer\s+)?(seats|places|spaces|slots|rooms|tickets)\b"
    r"|\btaken\b"
    r"|\bin\s+use\s+by\b"
    r"|\bmust\s+be\s+unique\b"
    r"|\bcannot\s+be\s+(re)?used\b",
    re.IGNORECASE,
)


def is_conflict(text: str) -> bool:
    """Is this the application refusing because of data or state, not merit?

    The one question the whole recovery path turns on, kept in one place so that
    the generated helper and the generator itself can never disagree about it.
    """
    return bool(CONFLICT.search(text or ""))


# ---------------------------------------------------------------------------
# Reading a field
# ---------------------------------------------------------------------------
#: Separators inside a machine-readable field name. `reference_number` and
#: `reference-number` are the same two words as "Reference Number", and a token
#: test that cannot see that misses most of the forms on the internet.
_SEPARATORS = re.compile(r"[-_.]+")


def field_words(element: dict[str, Any] | None) -> str:
    """Everything the recorder knows about what a field is called, lowercased.

    Punctuation between words is flattened to spaces, so a field named
    `account_number` reads as "account number" and answers to the same tokens
    its label does.
    """
    if not element:
        return ""
    attributes = element.get("attributes") or {}
    parts = [
        element.get("input_type"),
        element.get("accessible_name"),
        attributes.get("name"),
        attributes.get("id"),
        attributes.get("placeholder"),
        attributes.get("data-testid"),
        attributes.get("autocomplete"),
    ]
    joined = " ".join(str(part) for part in parts if part).lower()
    return _SEPARATORS.sub(" ", joined)


#: Fields whose value identifies one record rather than describing it. An
#: application that stores records keeps these unique almost without exception -
#: which is precisely why a recording of one being created cannot be replayed.
#:
#: The words are the ones browsers and form authors already use for these
#: fields, so they are as close to a standard as this gets. `autocomplete` in
#: particular is the field describing itself, in a vocabulary the HTML spec
#: fixed and every site shares.
_IDENTITY = {
    "email": ("email", "e-mail", "mail"),
    "mobile": ("tel", "phone", "mobile", "contact", "msisdn"),
    "username": ("username", "user_name", "user name", "login", "handle", "nickname"),
    "document": (
        "national", "passport", "nid", "identity", "id number", "id_number",
        "idnumber", "licence", "license", "kra", "aadhaar", "aadhar", "ssn",
        "tax", "vat", "registration number", "reference number", "account number",
    ),
}

#: Never varied, whatever else is true of it. Changing a password locks the test
#: out of the account it just made, and a one-time code is not ours to invent.
_SECRET = ("password", "passcode", "pin", "secret", "cvv", "cvc", "otp", "captcha")

_LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def identity_kind(value: str, element: dict[str, Any] | None) -> str | None:
    """Which sort of identity this field holds, or None if it is not one.

    The value is consulted as well as the field, because a form whose inputs are
    called `f1` and `f2` still cannot hide an email address.
    """
    words = field_words(element)
    if any(secret in words for secret in _SECRET):
        return None

    if "email" in words or _LOOKS_LIKE_EMAIL.match((value or "").strip()):
        return "email"

    for kind, tokens in _IDENTITY.items():
        if kind == "email":
            continue
        if any(token in words for token in tokens):
            if kind == "mobile" and not (value or "").strip().isdigit():
                continue
            return kind

    return None


def _is_password(element: dict[str, Any] | None) -> bool:
    return str((element or {}).get("input_type") or "").lower() == "password"


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------
def classify_values(actions: list[dict[str, Any]]) -> dict[int, Decision]:
    """A role for every typed value in the recording, keyed by action index.

    The reasoning runs from the strongest evidence to the weakest, and stops at
    the first that answers.

    **The application already said so.** If a conflict message was captured on
    this page during recording, the person recording hit the collision
    themselves and typed something else. Nothing beats being told.

    **The field is not an identity.** A password, an address line, a quantity, a
    search term: reproduced exactly, because the application is not keeping them
    unique and inventing new ones would change what the test is testing.

    **The form is creating something.** It asks for a password twice, or for the
    same value twice, or it is at an address applications only ever use for
    making a new record. The identifier in it belongs to that record from the
    first run onwards, so a new one is generated before the test even starts.

    **The address says the page signs in**, or a password was presented
    alongside. A credential, then, and the account behind it has to already
    exist. Inventing a new address here would lock the test out of the account
    it needs.

    **An identifier, and nothing else known.** The honest case, and the common
    one: a reference number typed into a form that says nothing about itself.
    It might be kept unique and it might not. So the recorded value runs, exactly
    as recorded - and if the application refuses it as a duplicate, *then* a new
    one is generated and the step retried. Evidence first, substitution second.
    That is `confidence` below, and `SUBSTITUTE_ABOVE` is what reads it.
    """
    pages = _pages_of(actions)
    decisions: dict[int, Decision] = {}

    for index, action in enumerate(actions):
        if ActionType(action["action_type"]) is not ActionType.INPUT:
            continue

        value = str((action.get("payload") or {}).get("value") or "")
        element = action.get("element")
        if not value.strip():
            continue

        page = pages[index]

        if page.saw_conflict:
            decisions[index] = Decision(
                DataRole.UNIQUE,
                "the application refused a value on this form as already taken "
                "while it was being recorded",
            )
            continue

        kind = identity_kind(value, element)
        if kind is None:
            decisions[index] = STATIC
            continue

        creating, because = page.creating()

        if page.signing_in and not creating:
            decisions[index] = Decision(
                DataRole.EXISTING,
                "presented at an address that signs in, so the account has to "
                "already exist and the recorded value is reproduced exactly",
            )
            continue

        if creating:
            decisions[index] = Decision(
                DataRole.UNIQUE, f"identifies a record being created ({because})"
            )
        elif page.has_password:
            decisions[index] = Decision(
                DataRole.EXISTING,
                "presented alongside a password, so it signs in to an account "
                "that has to already exist and is reproduced exactly",
            )
        else:
            # Nothing says this creates anything, and nothing says it signs in.
            # An identifier all the same, so the application may well refuse a
            # second one - but on evidence this thin the recorded value is what
            # runs, and a new one is invented only if the application actually
            # objects. See `SUBSTITUTE_ABOVE`.
            decisions[index] = Decision(
                DataRole.UNIQUE,
                f"identifies a record ({kind}), though nothing in the recording "
                "says whether the application keeps it unique",
                confidence=0.5,
            )

    return {
        index: _never_invent_a_credential(decision, pages[index])
        for index, decision in decisions.items()
    }


def _never_invent_a_credential(decision: Decision, page: _Page) -> Decision:
    """Nothing on a form that carries a password is replaced before the test runs.

    The one rule in this file that is not a judgement, and the reason it exists
    is that everything above it is. The rules read a form and decide whether it
    creates a record or opens one; get that backwards and the test signs in with
    an address that has never existed, and fails on every run, on every site,
    with the application looking like the thing that is broken.

    That failure actually happened here. A recording flushed its input buffer
    twice into one password box - somebody typed, tabbed away, came back - so a
    sign-in form counted two password fields, read as a sign-up, and had its
    email replaced. The counting is fixed. This exists so that the next thing
    that reads a sign-in as a sign-up cannot do the same damage.

    The asymmetry is what makes the rule cheap. Replacing a credential that
    should have been kept fails immediately and always, and reads as an
    application defect. *Keeping* an identifier that should have been replaced
    costs one round trip: the application says it is already taken, the step is
    refused in the application's own words, and `submit` enters a fresh value
    and sends it again - which is the recovery path this was built around, and
    is what the recorded value was always going to do on its second run anyway.

    So the recorded value goes in first. Always, on any form with a password, on
    any site. The only thing that overrides it is the application itself having
    refused that value while the recording was made - evidence, rather than
    another inference about what kind of form this is.
    """
    if not page.has_password or page.saw_conflict:
        return decision
    if decision.role is not DataRole.UNIQUE:
        return decision
    if decision.confidence < SUBSTITUTE_ABOVE:
        return decision

    return Decision(
        role=decision.role,
        why=(
            f"{decision.why}, but a password is filled in on this form too, so "
            "the recorded value is used as it stands and replaced only if the "
            "application refuses it"
        ),
        confidence=SUBSTITUTE_ABOVE - 0.1,
        shape=decision.shape,
    )


#: An address that is somebody creating an account. One signal among several
#: rather than the gate it used to be: plenty of applications create records at
#: addresses that look nothing like this.
_CREATING = re.compile(
    r"regist|sign[-_]?up|signup|create[-_]?account|join"
    # A path segment, so `/customers/add` and `/users/new` are creation and
    # `/address-book` is not. Applications name these pages from a very short
    # list of verbs, whatever the records underneath them are.
    r"|[/\-_](add|new|create)([/\-_?.]|$)",
    re.I,
)

#: An address that is somebody presenting a credential they already hold. The
#: mirror of the one above, and it has to exist separately: "there is no
#: password field on this page" is otherwise read as "this is not a sign-in",
#: which is true of almost every page and false of a sign-in form recorded by
#: somebody whose browser filled the password in for them.
_SIGNING_IN = re.compile(
    r"log[-_]?in|login|sign[-_]?in|signin|/auth|/session|authenticate", re.I
)


@dataclass
class _Page:
    """The run of actions on one address, and what it collectively looked like."""

    url: str
    signing_in: bool = False
    has_password: bool = False
    #: Distinct password *fields*, not password-typing *actions*. The recorder
    #: flushes an input buffer more than once - a person types, tabs away, comes
    #: back - so one box routinely arrives as two actions. Counting those, a
    #: sign-in form read as a sign-up, its email was classified as an identity
    #: being created, and the test signed in with an invented address on every
    #: run. See `_field_id` for what tells two fields apart.
    password_fields: set = field(default_factory=set)
    saw_conflict: bool = False
    repeated_value: bool = False

    def creating(self) -> tuple[bool, str]:
        """Was this form making an account rather than opening one?

        A sign-in form asks for one password. A sign-up asks for it twice, or
        asks for the address twice, because it has no other way to catch a typo
        in something it can never show back to you.
        """
        if len(self.password_fields) > 1:
            return True, "the form asks for a password twice"
        if self.repeated_value:
            return True, "the form asks for the same value twice"
        if _CREATING.search(self.url):
            return True, "the address says so"
        return False, ""


def _pages_of(actions: list[dict[str, Any]]) -> list[_Page]:
    """One `_Page` per action, shared by every action on the same address.

    A page stands in for a form. The recording carries no form grouping - the
    recorder captures elements, not the tree above them - and "the fields filled
    in without leaving the page" is the same thing nearly every time, on every
    site, with nothing to configure.
    """
    pages: dict[str, _Page] = {}
    order: list[_Page] = []

    for action in actions:
        url = str(action.get("url") or "")
        page = pages.get(url)
        if page is None:
            page = pages[url] = _Page(url=url, signing_in=bool(_SIGNING_IN.search(url)))
        order.append(page)

        element = action.get("element")
        if _is_password(element):
            page.has_password = True
            page.password_fields.add(_field_id(element))

        for message in (action.get("response") or {}).get("messages") or []:
            if is_conflict(str(message)):
                page.saw_conflict = True

    _mark_repeated_values(actions, order)
    return order


def _mark_repeated_values(actions: list[dict[str, Any]], pages: list[_Page]) -> None:
    """A value typed into two different fields on one page.

    An email and its confirmation, a password and its confirmation. Only a form
    creating something asks twice; nothing checks that you have retyped your
    credentials correctly when it is about to tell you whether they worked.
    """
    seen: dict[tuple[int, str], set[str]] = {}
    for index, action in enumerate(actions):
        if ActionType(action["action_type"]) is not ActionType.INPUT:
            continue
        value = str((action.get("payload") or {}).get("value") or "").strip()
        if not value:
            continue
        key = (id(pages[index]), value)
        where = seen.setdefault(key, set())
        where.add(_field_id(action.get("element")))
        if len(where) > 1:
            pages[index].repeated_value = True


def _field_id(element: dict[str, Any] | None) -> str:
    """Enough to tell two fields apart, and stable across a recording."""
    attributes = (element or {}).get("attributes") or {}
    return (
        str(attributes.get("id") or "")
        or str(attributes.get("name") or "")
        or str((element or {}).get("accessible_name") or "")
        or str(attributes.get("placeholder") or "")
    )


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------
#: Selectors that answer "this exact element" rather than "an element of this
#: kind". A path through the tree or an id addresses one node by construction,
#: so neither can ever tell us that a set exists.
_ADDRESSES_ONE = {
    SelectorStrategy.CSS_ID,
    SelectorStrategy.XPATH,
    SelectorStrategy.NTH_CHILD,
}

#: Elements a person can act on. A heading that happens to sit in a repeated
#: block is not a member of anything the test can choose between.
_ACTIONABLE = {"a", "button", "input", "select", "option", "label", "summary"}

#: Input types that are a place to type rather than a thing to choose. Clicking
#: one is putting the cursor in it, and a form of six text fields is not a set of
#: six comparable records however alike their markup makes them look.
_TYPING = {
    "text", "email", "password", "tel", "url", "search", "number", "date",
    "datetime-local", "month", "week", "time", "textarea",
}

#: Landmarks whose contents are the site rather than its records. A navigation
#: bar is a set of repeated links by construction, and swapping one for another
#: is never what a refusal calls for.
_CHROME_ROLES = {"navigation", "banner", "contentinfo", "complementary"}
_CHROME_TAGS = {"nav", "header", "footer", "aside"}


def classify_targets(actions: list[dict[str, Any]]) -> dict[int, Decision]:
    """A role for every element the recording acted on, keyed by action index.

    Only one role is interesting here, and it rests on a fact the recorder
    already collects for a different reason. Every selector is stored with the
    number of elements it matched at the moment of the click, so a selector
    built out of class names that matched more than one element is a selector
    describing the *shape* of a thing there are several of - a row, a card, a
    tile, a slot. Which is the definition of a set, arrived at without knowing
    what the set contains.

    That is a broad test, and it is meant to be, because being in a set is only
    ever permission to try another member *after* a refusal. The recorded
    element is what runs first, every time. A test that reached for a different
    member before anything went wrong would be a test that no longer replays the
    journey it was given.

    Two exclusions keep it honest. The element has to be something a person can
    act on, and it must not be part of the site's own furniture: a navigation bar
    is a set of repeated links by construction, and no refusal is ever answered
    by clicking a different tab.
    """
    decisions: dict[int, Decision] = {}

    for index, action in enumerate(actions):
        if ActionType(action["action_type"]) is not ActionType.CLICK:
            continue

        element = action.get("element") or {}
        if str(element.get("tag") or "").lower() not in _ACTIONABLE:
            continue
        if str(element.get("input_type") or "").lower() in _TYPING:
            continue
        if _is_chrome(element):
            continue

        shared = _shared_shape(action.get("selectors") or [])
        if shared is None:
            continue

        decisions[index] = Decision(
            DataRole.STATE_DEPENDENT,
            f"one of several elements matching {shared[1]!r} when recorded, so a "
            "comparable one can be tried if this one is refused",
            shape=shared,
        )

    return decisions


def _shared_shape(selectors: list[dict[str, Any]]) -> tuple[str, str] | None:
    """A recorded selector that other elements of the same shape also answer to.

    Not merely any selector that matched twice. It has to be one that describes
    the element rather than locating it, or the "set" is an accident of two
    unrelated things sharing a name.
    """
    for raw in selectors:
        try:
            strategy = SelectorStrategy(raw.get("strategy"))
        except ValueError:
            continue
        if strategy in _ADDRESSES_ONE:
            continue
        if raw.get("unique", True):
            continue
        value = str(raw.get("value") or "")
        return (strategy.value, value) if value else None
    return None


def _is_chrome(element: dict[str, Any]) -> bool:
    """Is this part of the site's furniture rather than its records?"""
    if str(element.get("role") or "").lower() in _CHROME_ROLES:
        return True

    # The recorder stores the element's own classes, and a link inside a
    # navigation almost always wears one that says so. Weaker than the role
    # above and used only as a second opinion.
    classes = str((element.get("attributes") or {}).get("class") or "").lower()
    return any(f"{tag}-" in classes or f"{tag}__" in classes for tag in _CHROME_TAGS)
