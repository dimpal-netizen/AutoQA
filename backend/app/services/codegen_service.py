"""Turn a recording into a stored test suite."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.case_generator import (
    DEFAULT_COUNT,
    MAX_COUNT,
    GenerationOutcome,
    accept_all,
    generate_cases,
)
from app.ai.enhancer import enhance
from app.codegen.converter import TestIR, build_ir
from app.codegen.generator import GeneratedCodeError, render
from app.codegen.probe import probe
from app.codegen.recorded_cases import (
    FROM_RECORDING,
    cases_from_recording,
    why_nothing,
)
from app.codegen.synth import (
    SynthesisError,
    module_for,
    sign_in_sequence,
    synthesise,
    vocabulary,
)
from app.codegen.writer import remove_suite_directory, suite_directory, write_suite
from app.core.config import settings
from app.models.enums import (
    FINISHED_RUN_STATUSES,
    CaseCategory,
    CasePriority,
    CaseSource,
    CaseStatus,
    FileType,
    RecordingStatus,
    RunStatus,
)
from app.models.test_case import TestSuite
from app.models.user import User
from app.reports.testcases import build_testcase_workbook
from app.repositories.recording_repo import RecordingRepository
from app.repositories.test_case_repo import (
    GeneratedFileRepository,
    TestCaseRepository,
    TestSuiteRepository,
)
from app.repositories.test_run_repo import TestResultRepository, TestRunRepository
from app.services.coverage import Coverage, coverage
from app.services.exceptions import NotFound, ValidationError
from app.services.flakiness import Flaky, flakiness
from app.services.recording_service import RecordingService

logger = logging.getLogger(__name__)

GENERATOR = "deterministic_v1"

def _why_nothing_was_usable(outcome) -> str:
    """Why a whole batch was thrown away, in enough detail to act on.

    This used to print the count-free phrase "the model returned no usable test
    cases" followed by the first rejection, which read as though one case had
    been a problem. Twelve had, all for the same reason, and the one line on
    screen gave no way to tell.

    Rejections repeat: a prompt that makes cases too long makes *every* case too
    long. So they are grouped, and the commonest is named first with how many
    shared it. Nothing is invented — the reasons are `synthesise`'s own.
    """
    if not outcome.rejected:
        return (
            "The model returned no test cases at all. Try again — if it keeps "
            "happening, the recording may be too short to write cases around."
        )

    # The reason without the case name in front of it, which differs every time
    # and would put every rejection in a group of one.
    counts: dict[str, int] = {}
    for rejection in outcome.rejected:
        reason = str(rejection).split(":", 1)[-1].strip() or str(rejection)
        counts[reason] = counts.get(reason, 0) + 1

    ranked = sorted(counts.items(), key=lambda pair: -pair[1])
    total = len(outcome.rejected)
    lead, count = ranked[0]

    if count == total and total > 1:
        return f"All {total} suggested cases were rejected: {lead}"

    detail = "; ".join(f"{reason} ({n})" for reason, n in ranked[:3])
    return f"None of the {total} suggested cases could be used. {detail}"


def _pages_by_variable(ir: TestIR):
    """(variable, page) pairs, the way a step names them."""
    from app.codegen.converter import page_variables

    by_class = {page.class_name: page for page in ir.pages}
    return [
        (var, by_class[class_name])
        for var, class_name in page_variables(ir)
        if class_name in by_class
    ]


def _describe_recorded_steps(ir: TestIR) -> str:
    """The recorded steps, numbered as a check will refer back to them."""
    return "\n".join(
        f"  {step.sequence}. {step.description}"
        + (f"  (typed: {step.input_data[:60]!r})" if step.input_data else "")
        for step in ir.steps
    )


def describe_elements(pages) -> str:
    """Every element a check may point at, named the way a step names it."""
    from app.codegen.synth import elements

    return "\n".join(
        f"  {item['target']}  ({item['label']}, on {item['page']})"
        for item in elements(pages)
    )


def _step_description(ir: TestIR, after: int) -> str:
    """What the step a check follows actually does.

    Sent back with the suggestion so the tickbox reads as "after clicking Login"
    rather than "after step 7" — a number nobody can check without counting.
    """
    for step in ir.steps:
        if step.sequence == after:
            return step.description
    return ""


class _Authored:
    """What `synthesise` reads off a case: a name and a list of steps.

    It takes anything with those attributes — the AI's suggestion object in one
    caller, this in the other — so a hand-written case travels the identical
    path with no branch anywhere along it.
    """

    def __init__(self, *, name: str, steps: list) -> None:
        self.name = name
        self.steps = steps


class CodegenService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.suites = TestSuiteRepository(db)
        self.cases = TestCaseRepository(db)
        self.files = GeneratedFileRepository(db)
        self.recordings = RecordingRepository(db)
        self.recording_service = RecordingService(db)

    def generate_from_recording(
        self, recording_id: int, user: User, *, name: str | None = None
    ) -> TestSuite:
        """Build a suite from a finished recording, checking permissions first."""
        session = self.recording_service.get(recording_id, user)
        return self._generate(session, created_by_id=user.id, name=name)

    def autogenerate(self, session, *, created_by_id: int | None) -> TestSuite | None:
        """Generate right after a recording stops.

        Called from the stop paths, which have already authorised the caller.
        Never raises: a codegen problem must not make stopping a recording
        fail, or the user would lose the recording as well as the code.
        """
        if not settings.AUTO_GENERATE_ON_STOP:
            return None

        try:
            return self._generate(session, created_by_id=created_by_id, name=None)
        except ValidationError as exc:
            # Nothing worth generating (an empty recording, usually).
            logger.info("Recording %s: skipped autogeneration - %s", session.id, exc)
        except Exception:
            logger.exception("Recording %s: autogeneration failed", session.id)
        return None

    def _generate(
        self, session, *, created_by_id: int | None, name: str | None
    ) -> TestSuite:
        """Build a suite from a finished recording.

        Regenerating replaces the previous output rather than piling up
        duplicates — the recording is the source of truth, not the code.
        """
        recording_id = session.id

        if session.status is RecordingStatus.RECORDING:
            raise ValidationError(
                "This recording is still running. Stop it before generating code."
            )

        actions = self.recordings.list_actions(recording_id, limit=10_000)
        usable = [a for a in actions if not a.is_ignored]
        if not usable:
            raise ValidationError("This recording has no actions to generate from.")

        suite_name = (name or session.name).strip() or f"Recording {recording_id}"

        raw = [
            {
                "action_type": a.action_type.value,
                "url": a.url,
                "frame_path": a.frame_path,
                "selectors": a.selectors,
                "element": a.element,
                "payload": a.payload,
                "is_ignored": a.is_ignored,
            }
            for a in actions
        ]

        # One recording, one test case.
        #
        # This used to be cut into a case per attempt - somebody tries logging
        # in, gets an error, tries again - on the reasoning that four things
        # were tested and should be reported on separately. The reasoning was
        # right about the recording and wrong about the code: a slice begins
        # part-way through a journey, and all it gets to make up for that is a
        # `goto`. Everything the earlier steps had built up is gone. Segment two
        # of a registration opens the form and types into field six, on a page
        # where the first five are empty and the account it needed was never
        # created. It cannot pass, and it fails for a reason that has nothing to
        # do with the application.
        #
        # The whole recording, in order, is the one thing that is known to work:
        # somebody sat and did it. That is what a regression test is for, and
        # anything narrower can be written against it afterwards - by hand, by
        # the model, or from the recording. See `segments.py`, which still
        # answers "where did they start over" for anything that wants to know.
        ir = build_ir(raw, suite_name=suite_name, start_url=session.start_url)

        # AI pass: better names and descriptions on code that already works.
        # `enhance` never raises and never writes code, so the worst case here
        # is that the deterministic output above is what gets saved.
        polish = enhance(ir)
        if polish.skipped:
            logger.info("Recording %s: no AI enhancement (%s)", recording_id, polish.skipped)
        suite_name = polish.title or suite_name

        try:
            rendered = render(ir, browser_info=session.browser_info)
        except GeneratedCodeError as exc:
            # A template bug, not a user error. Surface it plainly instead of
            # storing code that will not import.
            logger.exception("Codegen produced invalid Python for recording %s", recording_id)
            raise ValidationError(f"Generated code was not valid Python: {exc}") from exc

        generator = f"{GENERATOR}+{polish.model}" if polish.applied else GENERATOR
        description = polish.description or (
            f"Generated from recording {recording_id} ({len(usable)} actions)"
        )

        suite = self.suites.get_by_recording(recording_id)
        if suite is None:
            suite = self.suites.create(
                project_id=session.project_id,
                recording_id=recording_id,
                created_by_id=created_by_id,
                name=suite_name,
                description=description,
                source=CaseSource.RECORDING,
                generator=generator,
            )
        else:
            # Runs first: they are about the cases that are about to go, and
            # delete_run needs the suite row intact to authorise itself.
            self._discard_runs(suite)
            self.suites.delete_generated(suite)
            self.suites.update(
                suite, name=suite_name, description=description, generator=generator
            )

        # The recording, whole, as one case. Its module is the one `render`
        # already produced from this same IR, so nothing is compiled twice and
        # the file the suite writes to disk is the file the case holds.
        test_file = next(f for f in rendered if f.path == ir.file_path)
        case = self.cases.create(
            suite_id=suite.id,
            project_id=session.project_id,
            name=suite_name,
            description=(
                (polish.description + " " if polish.description else "")
                + f"{len(ir.steps)} steps across {len(ir.pages)} page(s)."
                + (
                    f" {ir.fragile_count} step(s) use a fragile selector."
                    if ir.fragile_count
                    else ""
                )
            ),
            function_name=ir.function_name,
            file_path=ir.file_path,
            code=test_file.content,
            source=CaseSource.RECORDING,
            status=CaseStatus.DRAFT,
            category=CaseCategory.RECORDED,
            priority=CasePriority.HIGH,
            generated_by=GENERATOR,
            tags=["recorded"],
            is_enabled=True,
            version=1,
        )

        for step in ir.steps:
            self.cases.add_step(
                test_case_id=case.id,
                sequence=step.sequence,
                action=step.action,
                description=step.description,
                locator=(
                    f"{step.page_var}.{step.locator_name}"
                    if step.page_var and step.locator_name
                    else None
                ),
                input_data=step.input_data,
                expected_result=step.expected_result,
                selector_strategy=step.strategy,
            )

        for spec in rendered:
            if spec.path == ir.file_path:
                continue  # the test module lives on the case, not as a file row
            self.files.create(
                suite_id=suite.id,
                project_id=session.project_id,
                file_type=spec.file_type,
                path=spec.path,
                content=spec.content,
                language="python" if spec.path.endswith(".py") else "ini",
                version=1,
                meta={},
            )

        # Put the scripts on disk. This is the copy a QA Engineer opens in
        # VS Code to review and edit; the database copy is what gets executed
        # and regenerated.
        target = suite_directory(session.project.name, suite_name)
        if self.suites.output_dir_taken(str(target), excluding=suite.id):
            target = suite_directory(
                session.project.name, suite_name, disambiguator=suite.id
            )

        previous = suite.output_dir
        try:
            # The page objects and config from the whole recording, plus one
            # test file per case. Not `rendered` alone: that carries the
            # combined test module, which no case owns and which would sit on
            # disk running the whole recording as one test beside the split
            # ones.
            on_disk = {
                spec.path: spec.content
                for spec in rendered
                if spec.path != ir.file_path
            }
            on_disk.update(
                {case.file_path: case.code for case in self.suites.get_full(suite.id).cases}
            )
            write_suite(target, on_disk)
            self.suites.update(suite, output_dir=str(target))

            # A rename moves the folder. Remove the old one, or `generated/`
            # accumulates a directory for every name the suite has ever had.
            if previous and previous != str(target):
                remove_suite_directory(Path(previous))
        except OSError:
            # A read-only or full disk must not lose the generated suite —
            # it is still in the database and still runnable.
            logger.exception("Could not write suite %s to %s", suite.id, target)

        self.db.commit()
        return self.suites.get_full(suite.id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # AI test case generation
    # ------------------------------------------------------------------
    def generate_cases(
        self,
        suite_id: int,
        user: User,
        *,
        count: int = DEFAULT_COUNT,
        guidance: str | None = None,
    ) -> tuple[TestSuite, GenerationOutcome]:
        """Add positive, negative, edge and security cases around the recording.

        Replaces the previously generated cases rather than appending, so
        pressing the button twice gives a fresh set instead of thirty
        near-duplicates. The recorded case is never deleted, only re-rendered.

        Pressing it twice on an unchanged recording should also give you the
        *same* set. It used to give a different one every time — the model was
        sampling, so a case that passed on Monday came back on Tuesday as a
        different test wearing the same name, and the suite went red against an
        application nobody had touched. The mirror of that was quieter and
        worse: a case failing because it had found a real bug came back weaker
        and went green.

        That is fixed where it was caused, in `ai/client.py`: the request is
        made at temperature zero with a fixed seed, so the same recording asks
        the same question and gets the same answer back. What a test says is
        then a fact about the application, which is the only thing that makes a
        verdict worth reading.
        """
        suite = self.get_suite(suite_id, user)

        recorded_ir = self._recorded_ir(suite)
        if recorded_ir is None:
            raise ValidationError(
                "This suite has no recording to generate test cases from."
            )

        self._mark_reachable(recorded_ir)

        outcome = generate_cases(recorded_ir, count=count, guidance=guidance)

        # Nothing came back from the model, for any of the reasons there are: no
        # key configured, a provider that was down, an answer that parsed into
        # nothing, or a dozen suggestions every one of which was rejected. The
        # recording is still here either way, and a recording says which pages
        # exist, what was on them, which fields somebody filled in and which
        # button they pressed to send it. Several kinds of case follow from that
        # with no judgement at all, and they are worth more than a 422 telling
        # somebody to go and buy an API key - see codegen/recorded_cases.py.
        #
        # This runs before the `skipped` check rather than after it, and that
        # order is the whole change: `skipped` is what "no AI provider" arrives
        # as, so testing it first is what used to make this a dead end.
        if not outcome.cases:
            outcome = self._from_the_recording_alone(
                recorded_ir, outcome, count=count, guidance=guidance
            )

        if outcome.skipped:
            raise ValidationError(outcome.skipped)
        if not outcome.cases:
            raise ValidationError(_why_nothing_was_usable(outcome))

        # Out with the previous generation, in with this one.
        for case in list(suite.cases):
            if case.category is not CaseCategory.RECORDED:
                self.cases.delete(case)
        self.db.flush()

        browser_info = suite.recording.browser_info if suite.recording else {}
        kept = []
        for synthesised in outcome.cases:
            # One case that will not render must not take the others with it.
            # A generation is a paid request and a minute of waiting; losing
            # eleven good cases because the twelfth used a name it did not
            # import is the same arithmetic as a truncated answer, and the same
            # answer applies - keep what is whole and say what was dropped.
            try:
                self._store_case(suite, synthesised, browser_info, outcome.model)
                kept.append(synthesised)
            except GeneratedCodeError as exc:
                logger.warning("Dropped %s: %s", synthesised.name, exc)
                outcome.rejected.append(f"{synthesised.name}: {exc}")
        outcome.cases = kept

        if not outcome.cases:
            raise ValidationError(_why_nothing_was_usable(outcome))

        self._refresh_files(suite, recorded_ir)
        self._discard_runs(suite)

        self.db.commit()
        suite = self.suites.get_full(suite.id)  # type: ignore[assignment]
        self._rewrite_folder(suite)
        return suite, outcome

    def _from_the_recording_alone(
        self,
        recorded_ir: TestIR,
        ai: GenerationOutcome,
        *,
        count: int,
        guidance: str | None,
    ) -> GenerationOutcome:
        """Build the cases the recording supports on its own.

        Held to exactly the rules a model's suggestion is held to: `accept_all`
        is the same loop, so an element that does not exist, an order that
        cannot happen and a case that checks nothing are refused here as well.
        Nothing new can reach a subprocess by this route that could not already
        reach it by the other one.

        `cost_usd` and `tokens` stay at zero because nothing was bought, and the
        one place this tool reports what it spent is not the place to round up.
        """
        drafts = cases_from_recording(recorded_ir, count=min(count, MAX_COUNT))
        outcome = GenerationOutcome(model=FROM_RECORDING)
        accept_all(drafts, recorded_ir, outcome)

        if not outcome.cases:
            # Both halves, in one breath. Told only that a key is missing,
            # somebody adds one, presses the button again, and gets the same
            # empty table - having paid for the privilege.
            return GenerationOutcome(
                skipped=(
                    f"{ai.skipped or _why_nothing_was_usable(ai)} Without one, "
                    f"cases can only be built from the recording itself - and "
                    f"this recording {why_nothing(recorded_ir)}"
                )
            )

        # Said in the log and nowhere else.
        #
        # A banner explaining this sat above a table that had just filled with
        # the answer - three sentences of prose telling somebody what they could
        # see. That is the same reason this endpoint stopped announcing its own
        # successes at all, and it applies here identically. Anyone who wants to
        # know which generator wrote a case can read `generated_by` on the case
        # itself, next to the case.
        logger.info(
            "Suite: built %d case(s) from the recording alone (%s)%s",
            len(outcome.cases),
            ai.skipped or "the model returned nothing usable",
            "; the brief could not be honoured" if (guidance or "").strip() else "",
        )
        return outcome

    def _mark_reachable(self, recorded_ir) -> None:
        """Look at each page cold, so cases are not written against what is not
        there.

        Everything else the model is shown comes from one recording, and a
        recording shows one state: the cart had something in it, the wizard was
        on step one, the account was under its listing limit. Opening the pages
        is the only way to know which elements survive arriving with none of
        that true - see `codegen/probe.py`.

        A probe that cannot run changes nothing, which is why nothing here
        checks whether it did.
        """
        if not settings.PROBE_PAGES:
            return

        # Belt and braces around the whole thing, not just inside `probe`.
        # `probe` promises never to raise and keeps that promise; the promise
        # stopped at its own front door, and a missing import here turned
        # "generate some test cases" into a 500 with a stack trace. Looking at
        # the application is an extra source of truth. It is never a gate.
        try:
            sequence, _, _ = sign_in_sequence(recorded_ir.steps)
            found = probe(recorded_ir, sign_in=sequence)
            if found is None:
                return

            for page in recorded_ir.pages:
                for locator in page.locators:
                    locator.reachable = found.offers(page, locator.name)
        except Exception:  # noqa: BLE001 - generation proceeds without it
            logger.warning("Could not work out what is on each page", exc_info=True)

    def _discard_runs(self, suite: TestSuite) -> None:
        """Throw away runs that tested code that has since been replaced.

        A verdict is about a particular version of a test. Once a case is
        rewritten, "1 passed" is a statement about a file that no longer
        exists — and because deleting a case sets its results' test_case_id to
        NULL, the result cannot even say which case it was about any more.
        Keeping that on screen next to the new code invites reading it as its
        result.

        Called when a case is edited into something different, and when a suite
        is rebuilt from its recording. Deliberately *not* called by
        `generate_cases`, which no longer replaces anything: those verdicts are
        still about the code that would run, and throwing them away would lose
        the very history that makes a red test worth trusting.

        A run still going is left alone. It is writing to its own directory and
        will finish against the files it started with; deleting it underneath
        itself is the one thing worse than a stale verdict.
        """
        from app.services.execution_service import ExecutionService

        execution = ExecutionService(self.db)
        for run in TestRunRepository(self.db).list_for_suite(suite.id):
            if run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
                logger.info("Suite %s: keeping run %s, still going", suite.id, run.id)
                continue
            try:
                execution.delete_run(run.id, self._owner_of(suite))
            except Exception:
                logger.exception("Could not discard run %s", run.id)

    @staticmethod
    def _owner_of(suite: TestSuite):
        """Whoever owns the project. Regeneration has already been authorised,
        and delete_run re-checks against a user rather than trusting a flag."""
        return suite.project.owner

    def _refresh_files(self, suite: TestSuite, ir: TestIR) -> None:
        """Re-render the page objects and config from the IR the cases used.

        Without this, the two halves of a suite come from two different runs of
        the generator. The cases are synthesised from an IR rebuilt just now;
        the page objects are whatever was stored the day the suite was first
        created. Any change to how page objects are named desynchronises them,
        and the result is not a subtle mismatch — the test module cannot be
        imported at all:

            ImportError: No module named 'pages.agent_details_page'
            (on disk: pages/agent_details_cmru9ht1z001a01l61v2hpc2u_page.py)

        pytest reports that as `collection failure`, which says nothing about
        the cause and takes the whole run down with it.

        A conftest the user has edited is left alone. Regenerating cases should
        not silently discard someone's fixtures.
        """
        try:
            rendered = render(ir)
        except GeneratedCodeError:
            logger.exception("Could not re-render supporting files for suite %s", suite.id)
            return

        existing = {f.path: f for f in suite.files}

        # The recorded case is rendered from this same IR, so it has to be
        # rewritten with the page objects rather than left behind. It lives on a
        # case row instead of a file, which is the only reason it was missed.
        #
        #     AttributeError: 'HomePage' object has no attribute 'login_link'
        #
        # A whole suite failed on that. The page objects had been re-rendered
        # from a fresh recording — one where a hover that contributed
        # `login_link` is no longer a step — while the recorded case still held
        # code written against the older set. Anything that changes which
        # locators exist desynchronises the two, and the symptom is never a
        # subtle mismatch: the module cannot even be imported.
        recorded = next(
            (c for c in suite.cases if c.category is CaseCategory.RECORDED), None
        )
        module = next((f for f in rendered if f.path == ir.file_path), None)
        if recorded is not None and module is not None:
            self.cases.update(
                recorded,
                code=module.content,
                file_path=ir.file_path,
                function_name=ir.function_name,
                version=recorded.version + 1,
            )

        for spec in rendered:
            if spec.path == ir.file_path:
                continue  # the recorded test lives on its case, not as a file

            current = existing.get(spec.path)
            if current is None:
                self.files.create(
                    suite_id=suite.id,
                    project_id=suite.project_id,
                    file_type=spec.file_type,
                    path=spec.path,
                    content=spec.content,
                    language="python" if spec.path.endswith(".py") else "ini",
                    version=1,
                    meta={},
                )
            elif current.file_type is not FileType.CONFTEST:
                self.files.update(
                    current, content=spec.content, version=current.version + 1
                )

        # Page objects for pages that no longer exist would still be written to
        # disk and imported by nothing — harmless, but they are the same stale
        # files this method exists to remove.
        fresh = {spec.path for spec in rendered}
        for path, stored in existing.items():
            if path not in fresh and stored.file_type is FileType.PAGE_OBJECT:
                self.files.delete(stored)

        self.db.flush()

    def _recorded_ir(self, suite: TestSuite) -> TestIR | None:
        """Rebuild the IR for the recording behind this suite.

        Rebuilt rather than stored: the IR is derived data, and keeping a
        serialised copy in the database would be one more thing to migrate
        every time the converter changes.

        Checks somebody added to the recorded test are applied here, on the way
        out. They live on the suite because this method runs on every
        regeneration, and a check written into the case instead would survive
        exactly until the next press of a button.
        """
        if suite.recording_id is None:
            return None

        actions = self.recordings.list_actions(suite.recording_id, limit=10_000)
        if not actions:
            return None

        ir = build_ir(
            [
                {
                    "action_type": a.action_type.value,
                    "url": a.url,
                    "frame_path": a.frame_path,
                    "selectors": a.selectors,
                    "element": a.element,
                    "payload": a.payload,
                    "is_ignored": a.is_ignored,
                }
                for a in actions
            ],
            suite_name=suite.name,
            start_url=suite.recording.start_url,
        )
        return ir

    def _store_case(
        self, suite: TestSuite, synthesised, browser_info: dict, model: str
    ) -> None:
        self._persist_case(
            suite,
            ir=synthesised.ir,
            name=synthesised.name,
            description=synthesised.description,
            category=synthesised.category,
            priority=synthesised.priority,
            generated_by=model or "ai",
            browser_info=browser_info,
        )

    def _persist_case(
        self,
        suite: TestSuite,
        *,
        ir: TestIR,
        name: str,
        description: str | None,
        category: CaseCategory,
        priority: CasePriority,
        generated_by: str,
        browser_info: dict,
        case=None,
    ):
        """Render an IR and save it as a case, replacing one if given.

        Create and edit differ only in whether a row already exists, and the
        rendering either side of that is identical — which is the point. A case
        a person edited is compiled by the same code as one the model invented,
        so there is no second path where a hand-written test could turn into
        something the generated ones cannot be.
        """
        rendered = render(ir, browser_info=browser_info)
        module = next(f for f in rendered if f.path == ir.file_path)

        values = {
            "name": name,
            "description": description,
            "function_name": ir.function_name,
            "file_path": ir.file_path,
            "code": module.content,
            "category": category,
            "priority": priority,
            "generated_by": generated_by,
            "tags": [category.value],
        }

        if case is None:
            case = self.cases.create(
                suite_id=suite.id,
                project_id=suite.project_id,
                source=CaseSource.RECORDING,
                status=CaseStatus.DRAFT,
                is_enabled=True,
                version=1,
                **values,
            )
        else:
            # The steps are about to be rewritten, and orphan rows would keep
            # their sequence numbers — colliding with the new ones on the unique
            # constraint the moment the new list is shorter.
            for step in list(case.steps):
                self.db.delete(step)
            self.db.flush()
            self.cases.update(case, version=case.version + 1, **values)

        for step in ir.steps:
            self.cases.add_step(
                test_case_id=case.id,
                sequence=step.sequence,
                action=step.action,
                verb=step.verb,
                description=step.description,
                locator=(
                    f"{step.page_var}.{step.locator_name}"
                    if step.page_var and step.locator_name
                    else None
                ),
                input_data=step.input_data,
                expected_result=step.expected_result,
                selector_strategy=step.strategy,
            )

        return case

    def _rewrite_folder(self, suite: TestSuite) -> None:
        """Refresh the folder on disk so every case has a file to open."""
        if not suite.output_dir:
            return

        bundle = {f.path: f.content for f in suite.files}
        for case in suite.cases:
            bundle[case.file_path] = case.code

        try:
            write_suite(Path(suite.output_dir), bundle)
        except OSError:
            logger.exception("Could not refresh %s", suite.output_dir)

    # ------------------------------------------------------------------
    # Hand-authored cases
    #
    # A generated suite is a starting point, not a finished one. The tester who
    # knows the application will always think of a case the model did not, and
    # will always find one it got slightly wrong. Without a way to fix either,
    # the only options are to regenerate and hope, or to abandon the tool and go
    # back to writing Playwright by hand.
    #
    # What a person may write is exactly what the model may write: a verb from
    # the vocabulary, an element that already exists, a value. Every check in
    # `synthesise` applies unchanged. Nobody types Python — a free-text code box
    # would put unreviewed code straight into a subprocess.
    # ------------------------------------------------------------------
    def case_vocabulary(self, suite_id: int, user: User) -> dict[str, object]:
        """Every action and element a case in this suite may be built from."""
        suite = self.get_suite(suite_id, user)
        return vocabulary(self._pages_for(suite))

    def create_case(
        self,
        suite_id: int,
        user: User,
        *,
        name: str,
        description: str | None,
        category: CaseCategory,
        priority: CasePriority,
        steps: list,
    ):
        suite = self.get_suite(suite_id, user)
        pages = self._pages_for(suite)

        taken = {case.function_name for case in suite.cases}
        module_name, function_name = module_for(name, taken)

        ir = self._authored_ir(
            suite,
            pages=pages,
            steps=steps,
            name=name,
            module_name=module_name,
            function_name=function_name,
        )

        case = self._persist_case(
            suite,
            ir=ir,
            name=name,
            description=description,
            category=category,
            priority=priority,
            generated_by="manual",
            browser_info=suite.recording.browser_info if suite.recording else {},
        )

        self._discard_runs(suite)
        self.db.commit()
        self._rewrite_folder(self.suites.get_full(suite.id))
        return self.cases.get_with_steps(case.id)

    def update_case(
        self,
        case_id: int,
        user: User,
        *,
        name: str,
        description: str | None,
        category: CaseCategory,
        priority: CasePriority,
        steps: list,
    ):
        case = self.cases.get_with_steps(case_id)
        if case is None:
            raise NotFound(f"Test case {case_id} not found")

        suite = self.get_suite(case.suite_id, user)
        pages = self._pages_for(suite)

        # The module keeps the name it was created with even when the case is
        # renamed. Moving the file would leave the old one on disk to be
        # collected and run by pytest — a duplicate of a test that no longer
        # exists, failing for reasons nobody can trace back to anything.
        ir = self._authored_ir(
            suite,
            pages=pages,
            steps=steps,
            name=name,
            module_name=Path(case.file_path).stem,
            function_name=case.function_name,
        )

        before = case.code
        self._persist_case(
            suite,
            ir=ir,
            name=name,
            description=description,
            category=category,
            priority=priority,
            generated_by=case.generated_by,
            browser_info=suite.recording.browser_info if suite.recording else {},
            case=case,
        )

        # Renaming a case or moving it from medium to high priority changes what
        # the row says, not what it does. Throwing away the run history for that
        # would punish tidying up — so the verdicts are only discarded when the
        # code that earned them is genuinely no longer the code that would run.
        if case.code != before:
            self._discard_runs(suite)

        self.db.commit()
        self._rewrite_folder(self.suites.get_full(suite.id))
        return self.cases.get_with_steps(case.id)

    def delete_case(self, case_id: int, user: User) -> None:
        case = self.cases.get_with_steps(case_id)
        if case is None:
            raise NotFound(f"Test case {case_id} not found")

        suite = self.get_suite(case.suite_id, user)
        if case.category is CaseCategory.RECORDED:
            raise ValidationError(
                "The recorded case is the session every other case was built "
                "from. Delete the recording itself if you no longer want it."
            )

        # Read before the delete: after the commit the instance is expired, and
        # touching an attribute on it would go back to a row that is gone.
        file_path = case.file_path

        self.cases.delete(case)
        self._discard_runs(suite)
        self.db.commit()

        suite = self.suites.get_full(suite.id)
        self._rewrite_folder(suite)
        # The module is gone from the database but still on disk, where pytest
        # would happily collect and run it — a test that no longer exists,
        # failing for reasons nothing on screen could explain.
        if suite and suite.output_dir:
            try:
                (Path(suite.output_dir) / file_path).unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove %s", file_path)

    def _pages_for(self, suite: TestSuite) -> list:
        """The page objects a case in this suite may point at.

        Rebuilt from the recording for the same reason `generate_cases` does it:
        an IR is derived data, and the page objects on disk are only a rendering
        of it. Editing has to work against the same element list the generator
        used, or a hand-written step could name something that no longer exists.
        """
        ir = self._recorded_ir(suite)
        if ir is None:
            raise ValidationError(
                "This suite has no recording behind it, so there are no "
                "elements a test case could refer to."
            )
        return ir.pages

    def _authored_ir(
        self,
        suite: TestSuite,
        *,
        pages: list,
        steps: list,
        name: str,
        module_name: str,
        function_name: str,
    ) -> TestIR:
        """Compile authored steps, turning a rejection into a readable message.

        `synthesise` says "step 3: unknown element 'LoginPage.submit'", which is
        precisely right and phrased for a log. The person reading it is looking
        at a form they just filled in, so it arrives as a 422 next to the step
        that caused it rather than as a stack trace.
        """
        try:
            return synthesise(
                _Authored(name=name, steps=steps),
                pages=pages,
                start_url=suite.recording.start_url if suite.recording else "",
                module_name=module_name,
                function_name=function_name,
            )
        except SynthesisError as exc:
            raise ValidationError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def get_suite(self, suite_id: int, user: User) -> TestSuite:
        suite = self.suites.get_full(suite_id)
        if suite is None:
            raise NotFound(f"Test suite {suite_id} not found")

        # Reuse the project rules; 404 rather than 403 so we don't confirm the
        # suite exists to someone who cannot see its project.
        try:
            self.recording_service.project_service.get(suite.project_id, user)
        except NotFound:
            raise NotFound(f"Test suite {suite_id} not found") from None

        return suite

    def coverage(self, suite_id: int, user: User) -> Coverage:
        """How much of what the recording found this suite's tests drive.

        The only coverage figure this tool can honestly produce. It is not "how
        much of your code is tested" — it cannot see the code — it is "how much
        of what we saw on the way through is being checked", which is a smaller
        claim and a true one.
        """
        suite = self.get_suite(suite_id, user)
        cases = [self.cases.get_with_steps(case.id) for case in suite.cases]
        return coverage(self._pages_for(suite), [c for c in cases if c])

    def flaky(self, suite_id: int, user: User) -> list[Flaky]:
        """Tests in this suite whose verdict changes without the test changing."""
        self.get_suite(suite_id, user)  # authorises
        return flakiness(TestResultRepository(self.db).history_per_case(suite_id))

    def export_testcases(
        self, suite_id: int, user: User, *, run_id: int | None = None
    ) -> tuple[bytes, str]:
        """The suite as a QA test-case workbook, plus a filename.

        Defaults to the suite's most recent finished run so the execution
        columns arrive filled in — that is the version a QA lead actually
        wants, and asking them to find a run id first would be busywork.

        Imported here rather than at module scope: execution imports codegen,
        so taking the dependency the other way round at import time would be a
        cycle.
        """
        from app.services.execution_service import ExecutionService

        suite = self.get_suite(suite_id, user)

        run = None
        results: list = []
        execution = ExecutionService(self.db)

        if run_id is not None:
            run = execution.get(run_id, user)
        else:
            runs = execution.list_runs(user, suite_id=suite_id, limit=10)
            run = next((r for r in runs if r.status in FINISHED_RUN_STATUSES), None)

        if run is not None:
            results = TestResultRepository(self.db).list_for_run(run.id)

        workbook = build_testcase_workbook(
            suite,
            list(suite.cases),
            project_name=suite.project.name if suite.project else "",
            designed_by=user.full_name or user.email,
            run=run,
            results=results,
        )

        stem = "".join(
            c if c.isalnum() else "_" for c in f"{suite.name}"
        ).strip("_") or f"suite_{suite.id}"
        return workbook, f"test_cases_{stem}.xlsx"

    def list_suites(
        self, user: User, project_id: int | None = None, skip: int = 0, limit: int = 100
    ) -> list[TestSuite]:
        projects = self.recording_service.project_service
        if project_id is not None:
            projects.get(project_id, user)
            project_ids = [project_id]
        else:
            project_ids = [p.id for p in projects.list_for_user(user, skip=0, limit=1000)]

        return self.suites.list_for_projects(project_ids, skip=skip, limit=limit)

    def delete_suite(self, suite_id: int, user: User) -> None:
        suite = self.get_suite(suite_id, user)
        self.suites.delete(suite)
        self.db.commit()

    def bundle(self, suite_id: int, user: User) -> dict[str, str]:
        """Every file as {path: content} — what Phase 5 will write to disk."""
        suite = self.get_suite(suite_id, user)
        files = {f.path: f.content for f in suite.files}
        for case in suite.cases:
            files[case.file_path] = case.code
        return files
