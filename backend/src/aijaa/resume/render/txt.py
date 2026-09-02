from aijaa.resume.ir import ResumeIR
from aijaa.resume.render.docx import HEADINGS


def render_txt(ir: ResumeIR, path: str) -> str:
    h = HEADINGS[ir.language]
    lines: list[str] = [ir.full_name, ir.contact_line]
    if ir.links:
        lines.append(" | ".join(ir.links))
    lines.append("")

    def section(title: str, rows: list[str]):
        if rows:
            lines.append(title.upper())
            lines.extend(rows)
            lines.append("")

    section(h["summary"], [ir.summary] if ir.summary else [])
    exp_rows: list[str] = []
    for e in ir.experience:
        exp_rows.append(f"{e.title} | {e.company} | {e.start} - {e.end or h['present']}")
        exp_rows.extend(f"  - {b.text}" for b in e.bullets)
    section(h["experience"], exp_rows)
    section(
        h["education"],
        [", ".join(str(x) for x in (ed.degree, ed.field, ed.institution, ed.year) if x) for ed in ir.education],
    )
    section(h["skills"], [", ".join(ir.skills)] if ir.skills else [])
    section(h["certifications"], [", ".join(ir.certifications)] if ir.certifications else [])

    content = "\n".join(lines).strip() + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
