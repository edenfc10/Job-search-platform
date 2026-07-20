from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from aijaa.cv_parser import CVParseError, extract_cv_text

router = APIRouter(prefix="/v1/cv", tags=["cv"])


class CVParseResponse(BaseModel):
    filename: str
    content_type: str
    text: str
    characters: int


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
