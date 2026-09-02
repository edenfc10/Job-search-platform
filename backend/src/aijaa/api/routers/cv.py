from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from aijaa.cv_parser import CVParseError, extract_cv_text
from aijaa.intake.local_parser import interpret_local_cv

router = APIRouter(prefix="/v1/cv", tags=["cv"])


class CVParseResponse(BaseModel):
    filename: str
    content_type: str
    text: str
    characters: int


class CVInterpretRequest(BaseModel):
    text: str


class CVInterpretResponse(BaseModel):
    profile_patch: dict
    preferences_patch: dict
    warnings: list[str]


@router.post("/parse", response_model=CVParseResponse)
async def parse_cv(file: UploadFile = File(...)):
    data = await file.read()
    try:
        text = extract_cv_text(file.filename or "", data)
    except CVParseError as e:
        raise HTTPException(422, str(e)) from e
    return CVParseResponse(
        filename=file.filename or "cv",
        content_type=file.content_type or "application/octet-stream",
        text=text,
        characters=len(text),
    )


@router.post("/interpret", response_model=CVInterpretResponse)
async def interpret_cv(body: CVInterpretRequest):
    """Produce an editable, truth-conservative draft for local/demo mode."""
    if not body.text.strip():
        raise HTTPException(422, "CV text is required")
    result = interpret_local_cv(body.text)
    return CVInterpretResponse(
        profile_patch=result.profile_patch,
        preferences_patch=result.preferences_patch,
        warnings=result.warnings,
    )
