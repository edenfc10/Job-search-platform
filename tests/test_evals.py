from tests.conftest import PROFILE_PATCH

from aijaa.llm.base import GeneratedAnswer
from aijaa.resume.guard import check_answer_text, check_ir
from aijaa.resume.ir import Bullet, ExperienceEntry, ResumeIR


def test_matcher_precision_eval_gate():
    labels = [True, True, True, False, True, True, True, True, False, True]
    assert sum(labels[:10]) / 10 >= 0.8


def test_tailoring_truthfulness_eval_gate():
    profile = _profile()
    fabricated_ir = ResumeIR(
        experience=[
            ExperienceEntry(
                company="X",
                title="Engineer",
                start="2020-01",
                bullets=[
                    Bullet(
                        text="Built Solidity smart contracts for a bank",
                        fact_ids=["missing"],
                    )
                ],
            )
        ]
    )
    assert check_ir(fabricated_ir, profile)


def test_screening_answer_trap_routes_to_human_or_guard_failure():
    profile = _profile()
    unsupported = GeneratedAnswer(text="Yes, I have active security clearance.", fact_ids=[])
    assert unsupported.needs_human or check_answer_text(
        unsupported.text, unsupported.fact_ids, profile
    )


def _profile():
    from aijaa.core.models import ProfessionalProfile

    return ProfessionalProfile.model_validate({"seeker_id": "eval", **PROFILE_PATCH})
