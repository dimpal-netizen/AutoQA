"""Explaining failures.

Analysis is on demand, not automatic. Every call costs money, a run can fail
thirteen times at once, and spending on someone's behalf without asking is not
a default anyone should have to discover from their bill. `analyse_run` exists
for when you do want all of them, and it says up front how many that is.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.ai.analyser import analyse, category_of, confidence_of, severity_of
from app.models.ai_analysis import AIAnalysis
from app.models.enums import ResultStatus
from app.models.user import User
from app.repositories.analysis_repo import AnalysisRepository
from app.repositories.test_case_repo import TestCaseRepository
from app.repositories.test_run_repo import TestResultRepository
from app.services.exceptions import NotFound, ValidationError
from app.services.execution_service import ExecutionService

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.analyses = AnalysisRepository(db)
        self.results = TestResultRepository(db)
        self.cases = TestCaseRepository(db)
        self.execution = ExecutionService(db)

    # ------------------------------------------------------------------
    def analyse_result(self, result_id: int, user: User) -> AIAnalysis:
        """Explain one failure, and store the explanation."""
        result = self.results.get_full(result_id)
        if result is None:
            raise NotFound(f"Result {result_id} not found")

        run = self.execution.get(result.run_id, user)  # authorises

        if result.status not in (ResultStatus.FAILED, ResultStatus.ERROR):
            raise ValidationError(
                f"This test {result.status.value}. Only failures can be analysed."
            )

        outcome = analyse(
            result,
            # The same test in the other browsers: "passes in Chrome, fails in
            # WebKit" is the strongest signal there is, and it is unavailable
            # to anyone looking at a single result.
            siblings=self.results.list_for_run(result.run_id),
            steps=self._steps_for(result),
            base_url=run.project.base_url if run.project else None,
        )
        if outcome.skipped:
            raise ValidationError(outcome.skipped)

        found = outcome.analysis
        analysis = self.analyses.create(
            result_id=result.id,
            run_id=result.run_id,
            provider=outcome.provider,
            model=outcome.model,
            root_cause=found.root_cause.strip(),
            suggested_fix=found.suggested_fix.strip(),
            category=category_of(found.category),
            severity=severity_of(found.severity),
            priority=severity_of(found.priority),
            is_product_bug=bool(found.is_product_bug),
            confidence=confidence_of(found.confidence),
            tokens=outcome.tokens,
            cost_usd=outcome.cost_usd,
            raw=found.model_dump(),
        )
        self.db.commit()
        return analysis

    # ------------------------------------------------------------------
    def analyse_run(self, run_id: int, user: User) -> list[AIAnalysis]:
        """Explain every failure in a run, skipping ones already explained."""
        self.execution.get(run_id, user)  # authorises

        failures = self.results.list_failures(run_id)
        if not failures:
            raise ValidationError("Nothing failed in this run.")

        analyses: list[AIAnalysis] = []
        for result in failures:
            if self.analyses.latest_for_result(result.id) is not None:
                continue  # already explained; re-analysing is an explicit action
            try:
                analyses.append(self.analyse_result(result.id, user))
            except ValidationError as exc:
                # One failure the model would not explain must not cost the
                # explanations of the others.
                logger.info("Result %s: not analysed - %s", result.id, exc)

        if not analyses:
            raise ValidationError(
                "Every failure in this run has already been analysed."
            )
        return analyses

    # ------------------------------------------------------------------
    def get_for_result(self, result_id: int, user: User) -> AIAnalysis | None:
        result = self.results.get_full(result_id)
        if result is None:
            raise NotFound(f"Result {result_id} not found")

        self.execution.get(result.run_id, user)  # authorises
        return self.analyses.latest_for_result(result_id)

    def _steps_for(self, result) -> list:
        """The test's own steps, which say what it was trying to do."""
        if result.test_case_id is None:
            return []
        case = self.cases.get_with_steps(result.test_case_id)
        return list(case.steps) if case else []
