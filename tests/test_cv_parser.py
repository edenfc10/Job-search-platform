from io import BytesIO

from docx import Document


async def test_parse_text_cv(client):
    files = {"file": ("cv.txt", b"Dana Levi\nSenior Backend Engineer", "text/plain")}
    r = await client.post("/v1/cv/parse", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "cv.txt"
    assert "Dana Levi" in body["text"]
    assert body["characters"] == len(body["text"])


async def test_parse_docx_cv(client):
    doc = Document()
    doc.add_heading("Dana Levi", level=1)
    doc.add_paragraph("Senior Backend Engineer with FastAPI experience.")
    buf = BytesIO()
    doc.save(buf)

    files = {
        "file": (
            "cv.docx",
            buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    r = await client.post("/v1/cv/parse", files=files)
    assert r.status_code == 200, r.text
    assert "Dana Levi" in r.json()["text"]
    assert "FastAPI" in r.json()["text"]


async def test_parse_rejects_unsupported_cv(client):
    files = {"file": ("cv.pages", b"not supported", "application/octet-stream")}
    r = await client.post("/v1/cv/parse", files=files)
    assert r.status_code == 422
    assert "supported CV formats" in r.json()["detail"]


async def test_local_interpret_handles_general_legal_cv(client):
    text = """SAMPLE RESUME
Daniel Cohen
LAWYER · TEL AVIV, ISRAEL · +972 50 123 4567
daniel@example.com

SKILLS
Legal Database
Government Relations
Regulation
Litigation

LANGUAGES
Hebrew
English

PROFILE
Experienced lawyer. Aspires to act as a VP government relations and regulatory.

EMPLOYMENT HISTORY
Regulation Manager, Trade Association
2019 — Present
• Represented industry members before government authorities and Knesset committees

EDUCATION
2010 - 2014 | LLB Bachelor of Laws, Reichman University
"""
    r = await client.post("/v1/cv/interpret", json={"text": text})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_patch"]["contact"]["full_name"] == "Daniel Cohen"
    assert body["profile_patch"]["work_history"][0]["title"] == "Regulation Manager"
    skills = {item["text"].casefold() for item in body["profile_patch"]["skills"]}
    assert {"regulation", "litigation", "government relations"} <= skills
    assert "aws" not in skills  # "Laws" must not be misread as the AWS acronym.
    assert body["preferences_patch"]["target_titles"][0].startswith("VP government")


async def test_local_interpret_requires_text(client):
    r = await client.post("/v1/cv/interpret", json={"text": "  "})
    assert r.status_code == 422
