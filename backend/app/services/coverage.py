"""What only the happy path touches.

The first version of this compared every element in the page objects against
every element the tests drive, and reported 100% on every suite in the
database. It had to: the page objects are *built from* the recorded actions, so
an element exists in them only because something already used it. The number
was arithmetic, not information.

What is worth counting is narrower and true. The recording walks one path and
everything on it works — that is what a recording is. The value of the suite is
in the cases written *around* it: the empty field, the wrong password, the
address that already exists. So the question is which elements the recording
touched that no other case ever does, because those are the parts of the flow
with exactly one test, and that test is the one that was always going to pass.

Deliberately plain counting, with no model involved. A gap here is a fact about
two lists, and it is worth more for being checkable than for being phrased well.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Elements nobody writes a test *about*, which would otherwise fill the list
#: and bury the ones that matter. A page's own navigation is on every page; a
#: test that clicks the logo is not the test anybody was missing.
_INCIDENTAL = (
    "logo",
    "footer",
    "copyright",
    "cookie",
    "breadcrumb",
    "skip_to",
    "scroll_to_top",
)


@dataclass(frozen=True)
class Untouched:
    """One element only the recorded happy path drives."""

    page: str
    page_url: str
    element: str
    label: str
    #: True when the only ways of finding it were positional. Worth saying: a
    #: test written against it would be brittle from the day it was written, so
    #: this is as much a note for whoever owns the page as for the tester.
    fragile: bool


@dataclass
class Coverage:
    """How much of the recorded flow has a test other than the recording."""

    touched: int
    total: int
    untouched: list[Untouched]

    @property
    def percent(self) -> int:
        """Rounded down, so 99 never reads as 100 with something still missing."""
        if not self.total:
            return 100
        return int(self.touched * 100 / self.total)


def coverage(pages, cases) -> Coverage:
    """Which elements of the recorded flow no case beyond the recording drives.

    `pages` is the PageSpec list the suite was generated from; `cases` are its
    stored test cases with their steps. A step records its element as
    `page_var.locator_name`, the same name the editor offers, so the comparison
    is on the name a person would recognise rather than on a selector.

    The recorded case is excluded from what counts as covered — including it
    would make every element covered by definition, which is what the first
    version of this did and why it reported 100% on everything.
    """
    from app.codegen.synth import elements
    from app.models.enums import CaseCategory

    available = [
        item
        for item in elements(pages)
        if not _is_incidental(str(item["target"]))
    ]
    driven = {
        str(step.locator)
        for case in cases
        if getattr(case, "category", None) is not CaseCategory.RECORDED
        for step in getattr(case, "steps", []) or []
        if getattr(step, "locator", None)
    }

    untouched = [
        Untouched(
            page=str(item["page"]),
            page_url=str(item.get("page_url") or ""),
            element=str(item["target"]),
            label=str(item["label"]),
            fragile=bool(item.get("fragile")),
        )
        for item in available
        if str(item["target"]) not in driven
    ]

    # Fragile ones last: they are the least useful thing to go and write a test
    # against, and putting them first would send someone at the worst target on
    # the list.
    untouched.sort(key=lambda u: (u.fragile, u.page, u.label))

    return Coverage(
        touched=len(available) - len(untouched),
        total=len(available),
        untouched=untouched,
    )


def _is_incidental(target: str) -> bool:
    name = target.lower()
    return any(word in name for word in _INCIDENTAL)
