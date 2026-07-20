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
