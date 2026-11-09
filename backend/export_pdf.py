"""Server-side PDF export (M9/M14) with Symbiosis examination header.

Uses reportlab (pure Python, offline) to render the final paper and the
separate answer key. Plain-text flowables only — no HTML parsing, so LLM
characters (&, <, >) can never break the export. Missing header fields render
as blank underlines; nothing is invented.
"""

import io
from typing import Dict, Any
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, KeepTogether,
)
from reportlab.lib import colors

SERIF = "Times-Roman"
SERIF_B = "Times-Bold"
SERIF_I = "Times-Italic"

FOOTER_LEFT = "SYMBIOSIS INSTITUTE OF TECHNOLOGY, NAGPUR"


def _default_exam_title(meta: dict) -> str:
    if str((meta or {}).get("exam_type", "")).strip().lower().startswith("end"):
        return "END-SEMESTER EXAMINATION"
    return "MID-SEMESTER EXAMINATION"


class _NumberedCanvas(pdf_canvas.Canvas):
    """Across-page footer: institute left, 'Page X of Y' right (Times, subtle)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages: list = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for i, state in enumerate(self._saved_pages, 1):
            self.__dict__.update(state)
            self.setFont(SERIF, 8)
            self.setFillColor(colors.HexColor("#333333"))
            self.drawString(18 * mm, 12 * mm, FOOTER_LEFT)
            self.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {i} of {total}")
            super().showPage()
        super().save()


def _duration_str(minutes) -> str:
    try:
        m = int(minutes or 0)
    except (TypeError, ValueError):
        m = 0
    if m <= 0:
        return ""
    h, rem = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h} Hour{'s' if h != 1 else ''}")
    if rem:
        parts.append(f"{rem} Minutes")
    return " ".join(parts)


def _blank(value: Any, width: int = 30) -> str:
    """Header helper: real value or a blank underline (never invent data)."""
    v = str(value or "").strip()
    return escape(v) if v else "_" * width


def _plain_option(opt: Any, idx: int) -> str:
    """Normalize 'A. text' / 'A) text' to academic 'a) text'."""
    import re
    s = str(opt or "").strip()
    s = re.sub(r"^[A-Za-z][\.\)]\s*", "", s)
    letters = "abcd"
    tag = letters[idx] if idx < len(letters) else f"{idx + 1}"
    return f"{tag})  {s}"


def _exam_header_flowables(paper: Dict[str, Any], include_answers: bool,
                           styles: Dict[str, ParagraphStyle]) -> list:
    """Symbiosis header block mirroring frontend ExamHeader.jsx.

    Answer-key variant keeps the university/field band (context) but omits the
    student-information section and is labelled ANSWER KEY.
    """
    meta = paper.get("exam_meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    subject = str(paper.get("subject", "") or "")
    total_marks = paper.get("total_marks", "")
    time_val = str(meta.get("time_slot", "") or "").strip() or _duration_str(paper.get("duration_minutes"))

    thin_box = TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])
    out = []
    # University band: crest cell + titles + seat boxes.
    seat_cells = [Paragraph("", styles["cell"]) for _ in range(6)]
    band = Table([
        [Paragraph("<b><font size=16>S</font></b><br/><font size=6>SYMBIOSIS</font>", styles["center"]),
         Paragraph("<b><font size=13>SYMBIOSIS INTERNATIONAL (DEEMED UNIVERSITY)</font></b>"
                   "<br/><font size=8>(Established under section 3 of the UGC Act, 1956)</font>"
                   "<br/><font size=8>Re-accredited by NAAC with 'A++' Grade Awarded Category - I by UGC</font>",
                   styles["center"]),
         [Paragraph("<b><font size=8>Seat No.</font></b>", styles["center"]),
          Table([seat_cells], colWidths=[7 * mm] * 6, style=thin_box)]],
    ], colWidths=[28 * mm, 108 * mm, 44 * mm])
    band.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, colors.black),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 4),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    out.append(KeepTogether(band))
    out.append(Spacer(1, 2))

    def row(label: str, value: str, width: int = 40) -> Paragraph:
        return Paragraph(f"<b>{escape(label)}:</b> {_blank(value, width)}", styles["field"])

    fields = [
        row("Institute", str(paper.get("institution", "") or meta.get("institute", "")), 60),
        row("Programme", meta.get("programme", ""), 60),
        row("Batch", meta.get("batch", ""), 25),
        row("Semester", meta.get("semester", ""), 25),
        row("Course", subject, 60),
        row("Course Code", meta.get("course_code", ""), 30),
        row("Date", meta.get("exam_date", ""), 25),
        Paragraph(f"<b>Maximum Marks:</b> {escape(str(total_marks))}", styles["field"]),
        row("Day", meta.get("day", ""), 25),
        row("Time", time_val, 30),
    ]
    # Two-column pairing for compact A4 rows: Batch|Semester, Date|Max Marks, Day|Time.
    paired = Table([
        [fields[0]], [fields[1]],
        [fields[2], fields[3]],
        [fields[4]], [fields[5]],
        [fields[6], fields[7]],
        [fields[8], fields[9]],
    ], colWidths=[90 * mm, 90 * mm])
    paired.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, colors.black),
                                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("SPAN", (0, 0), (-1, 0)),
                                ("SPAN", (0, 1), (-1, 1)),
                                ("SPAN", (0, 3), (-1, 3)),
                                ("SPAN", (0, 4), (-1, 4))]))
    out.append(KeepTogether(paired))

    if not include_answers:
        student = [
            [Paragraph("<b>STUDENT INFORMATION</b>", styles["center"])],
            [row("Student Name", "", 60)],
            [row("PRN Number", "", 25), row("Seat No.", "", 15)],
            [row("Roll No.", "", 25), row("Division / Class", "", 20)],
            [row("Date", meta.get("exam_date", ""), 25),
             Paragraph("<b>Signature of Student:</b> __________________", styles["field"])],
        ]
        st = Table(student, colWidths=[90 * mm, 90 * mm])
        st.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, colors.black),
                                ("SPAN", (0, 0), (-1, 0)),
                                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                                ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        out.append(KeepTogether(st))
        out.append(Paragraph("<b>NOTE : DO NOT WRITE ANYTHING ON THE QUESTION PAPER</b>",
                             styles["notebar"]))
    else:
        out.append(Paragraph("<b>ANSWER KEY — FOR EXAMINER USE ONLY</b>", styles["notebar"]))
    return out


def build_pdf(paper: Dict[str, Any], include_answers: bool = False) -> bytes:
    """Render paper dict to PDF bytes. Raises ValueError on empty paper."""
    sections = paper.get("sections", []) or []
    n_q = sum(len(s.get("questions", [])) for s in sections)
    if n_q == 0:
        raise ValueError("Paper has no questions to export.")

    subject = str(paper.get("subject", ""))
    meta = paper.get("exam_meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    exam_title = str(paper.get("exam_name") or paper.get("title")
                     or _default_exam_title(meta))
    if include_answers:
        exam_title = f"{exam_title} — ANSWER KEY"
    total_marks = paper.get("total_marks", "")

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=15 * mm, bottomMargin=18 * mm,
                          title=exam_title[:80], author="Question Paper Generator")

    s_title = ParagraphStyle("Title2", fontSize=14, leading=17, alignment=1, spaceAfter=2, fontName=SERIF_B)
    s_h1 = ParagraphStyle("H1", fontSize=11, leading=14, fontName=SERIF_B, spaceBefore=8, spaceAfter=2)
    s_sec = ParagraphStyle("Sec", fontSize=11, leading=14, fontName=SERIF_B)
    s_secmarks = ParagraphStyle("SecMarks", fontSize=10, leading=14, alignment=2, fontName=SERIF_B)
    s_q = ParagraphStyle("Q", fontSize=11, leading=14, fontName=SERIF)
    s_marks = ParagraphStyle("Marks", fontSize=11, leading=14, alignment=2, fontName=SERIF_B)
    s_opt = ParagraphStyle("Opt", fontSize=11, leading=14, leftIndent=12, fontName=SERIF)
    s_key = ParagraphStyle("Key", fontSize=10, leading=13, leftIndent=12, fontName=SERIF)
    s_instr = ParagraphStyle("Instr", fontSize=10, leading=13, leftIndent=12, fontName=SERIF)
    s_foot = ParagraphStyle("Foot", fontSize=10, leading=14, alignment=1, fontName=SERIF_B)
    # Symbiosis header styles (Times to match the academic body).
    s_center = ParagraphStyle("Center", fontSize=9, leading=11, alignment=1, fontName=SERIF)
    s_field = ParagraphStyle("Field", fontSize=9, leading=12, fontName=SERIF)
    s_cell = ParagraphStyle("Cell", fontSize=8, leading=9, alignment=1, fontName=SERIF)
    s_notebar = ParagraphStyle("NoteBar", fontSize=9, leading=12, alignment=1,
                               fontName=SERIF_B, borderWidth=1.2,
                               borderColor=colors.black, spaceBefore=0, spaceAfter=6,
                               backColor=colors.white)
    styles = {"center": s_center, "field": s_field, "cell": s_cell, "notebar": s_notebar}

    story = []
    story.extend(_exam_header_flowables(paper, include_answers, styles))
    story.append(Spacer(1, 4))
    story.append(Paragraph(escape(exam_title), s_title))
    story.append(HRFlowable(width="100%", thickness=1.0, spaceAfter=4))

    # Traditional instructions: fixed academic lines + any extra paper-specific ones.
    traditional = [
        "Attempt all questions.",
        "Figures to the right indicate maximum marks.",
        "Make suitable assumptions wherever necessary and state them clearly.",
    ]
    extras = []
    for inst in paper.get("instructions", []) or []:
        s = str(inst).strip()
        if not s:
            continue
        low = s.lower()
        if any(k in low for k in ("attempt all", "figures to the right", "assumption")):
            continue
        if s not in extras:
            extras.append(s)
    story.append(Paragraph("Instructions:", s_h1))
    letters = "abcdefghijklmnopqrstuvwxyz"
    for i, line in enumerate(traditional + extras):
        tag = letters[i] if i < len(letters) else f"{i + 1}"
        story.append(Paragraph(f"{tag})&nbsp;&nbsp;{escape(line)}", s_instr))
    story.append(Spacer(1, 4))

    q_no = 0
    for s_idx, section in enumerate(sections):
        stitle = str(section.get("section_title") or f"Section {chr(65 + s_idx)}").upper()
        mpq = section.get("marks_per_question", "")
        questions = section.get("questions", []) or []
        try:
            sec_total = sum(int(q.get("marks", mpq) or 0) for q in questions)
        except (TypeError, ValueError):
            sec_total = ""
        head = Table([[Paragraph(escape(stitle), s_sec),
                       Paragraph(escape(f"[{sec_total} Marks]" if sec_total != "" else ""), s_secmarks)]],
                     colWidths=[145 * mm, 35 * mm])
        story.append(head)
        story.append(Paragraph("Answer all questions.", s_instr))
        for q in questions:
            q_no += 1
            qmarks = q.get("marks", mpq)
            body = escape(str(q.get("question", "")))
            opts = q.get("options", []) or []
            if opts:
                opt_lines = "<br/>".join(
                    escape(_plain_option(o, i)) for i, o in enumerate(opts))
                body = f"{body}<br/>{opt_lines}"
            if include_answers:
                body += f"<br/><b>Answer:</b> {escape(str(q.get('answer', '')))}"
                if q.get("explanation"):
                    body += f"<br/><i>Explanation:</i> {escape(str(q.get('explanation')))}"
            row = Table([[Paragraph(f"<b>Q.{q_no}</b>&nbsp;&nbsp;{body}", s_q),
                          Paragraph(f"<b>{escape(str(qmarks))}</b>", s_marks)]],
                        colWidths=[150 * mm, 30 * mm])
            row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 2),
                                     ("TOPPADDING", (0, 0), (-1, -1), 3),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.append(row)

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.8, spaceAfter=4))
    story.append(Paragraph("*** END OF QUESTION PAPER ***" if not include_answers else "*** END OF ANSWER KEY ***", s_foot))

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame])])
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
