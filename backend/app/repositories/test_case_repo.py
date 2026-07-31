"""Queries for generated test assets."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.test_case import GeneratedFile, TestCase, TestStep, TestSuite
from app.repositories.base import BaseRepository


class TestSuiteRepository(BaseRepository[TestSuite]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TestSuite)

    def get_full(self, suite_id: int) -> TestSuite | None:
        stmt = (
            select(TestSuite)
            .where(TestSuite.id == suite_id)
            .options(
                selectinload(TestSuite.cases).selectinload(TestCase.steps),
                selectinload(TestSuite.files),
            )
        )
        return self.db.scalars(stmt).first()

    def list_for_projects(
        self, project_ids: list[int], skip: int = 0, limit: int = 100
    ) -> list[TestSuite]:
        if not project_ids:
            return []
        stmt = (
            select(TestSuite)
            .where(TestSuite.project_id.in_(project_ids))
            .order_by(TestSuite.created_at.desc())
            .offset(skip)
            .limit(limit)
            .options(selectinload(TestSuite.cases))
        )
        return list(self.db.scalars(stmt))

    def get_by_recording(self, recording_id: int) -> TestSuite | None:
        stmt = select(TestSuite).where(TestSuite.recording_id == recording_id)
        return self.db.scalars(stmt).first()

    def delete_generated(self, suite: TestSuite) -> None:
        """Wipe cases and files before regenerating, keeping the suite row."""
        for case in list(suite.cases):
            self.db.delete(case)
        for file in list(suite.files):
            self.db.delete(file)
        self.db.flush()


class TestCaseRepository(BaseRepository[TestCase]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TestCase)

    def get_with_steps(self, case_id: int) -> TestCase | None:
        stmt = (
            select(TestCase)
            .where(TestCase.id == case_id)
            .options(selectinload(TestCase.steps))
        )
        return self.db.scalars(stmt).first()

    def list_for_project(self, project_id: int, skip: int = 0, limit: int = 100) -> list[TestCase]:
        stmt = (
            select(TestCase)
            .where(TestCase.project_id == project_id)
            .order_by(TestCase.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def add_step(self, **values) -> TestStep:
        step = TestStep(**values)
        self.db.add(step)
        self.db.flush()
        return step


class GeneratedFileRepository(BaseRepository[GeneratedFile]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, GeneratedFile)

    def list_for_suite(self, suite_id: int) -> list[GeneratedFile]:
        stmt = (
            select(GeneratedFile)
            .where(GeneratedFile.suite_id == suite_id)
            .order_by(GeneratedFile.path)
        )
        return list(self.db.scalars(stmt))
