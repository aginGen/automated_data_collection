"""Render report.md to a five-page PDF. Requires reportlab and Windows Times fonts."""

import html
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LAB = Path(__file__).resolve().parents[1]


def inline(text):
    text = text.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    value = html.escape(text)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#204c73">\1</link>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r"<i>\1</i>", value)
    return value


def build():
    for name, file in [("Report", "times.ttf"), ("ReportBold", "timesbd.ttf"), ("ReportItalic", "timesi.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / file)))
    pdfmetrics.registerFontFamily("Report", normal="Report", bold="ReportBold", italic="ReportItalic", boldItalic="ReportBold")
    document = SimpleDocTemplate(str(LAB / "report.pdf"), pagesize=A4, leftMargin=42, rightMargin=42,
                                 topMargin=35, bottomMargin=35,
                                 title="Лабораторная работа 5 Промышленный краулинг Scrapy и n8n", author="")
    body = ParagraphStyle("Body", fontName="Report", fontSize=10.4, leading=12.6, spaceAfter=4.4, alignment=TA_LEFT)
    title = ParagraphStyle("Title", parent=body, fontName="ReportBold", fontSize=14.6, leading=17.2, spaceAfter=8, keepWithNext=True)
    heading = ParagraphStyle("Heading", parent=body, fontName="ReportBold", fontSize=11.8, leading=14, spaceBefore=6.5, spaceAfter=4, keepWithNext=True)
    cell = ParagraphStyle("Cell", parent=body, fontSize=8.7, leading=10.2, spaceAfter=0)
    story = []
    lines = (LAB / "report.md").read_text(encoding="utf-8").splitlines()
    i = 0
    width = A4[0] - 84
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line == "<!-- pagebreak -->":
            story.append(PageBreak()); i += 1; continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), title)); i += 1; continue
        if line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), heading)); i += 1; continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [part.strip() for part in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", part) for part in cells):
                    rows.append([Paragraph(inline(part), cell) for part in cells])
                i += 1
            n = len(rows[0])
            proportions = {2: [0.37, 0.63], 3: [0.42, 0.29, 0.29], 4: [0.37, 0.13, 0.37, 0.13],
                           5: [0.32, 0.17, 0.17, 0.17, 0.17], 6: [0.34, 0.12, 0.14, 0.13, 0.13, 0.14]}.get(n, [1 / n] * n)
            if n == 4 and rows[0][0].getPlainText() == "Прогон":
                proportions = [0.22, 0.34, 0.12, 0.32]
            table = Table(rows, colWidths=[width * value for value in proportions], repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9D9D9")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f5")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.extend([table, Spacer(1, 5)])
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("#", "|", "<!--")):
            paragraph.append(lines[i].strip()); i += 1
        story.append(Paragraph(inline(" ".join(paragraph)), body))

    def footer(canvas, doc):
        canvas.setFont("Report", 8.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        
        canvas.drawRightString(A4[0] - 42, 19, str(doc.page))

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(LAB / "report.pdf")


if __name__ == "__main__":
    build()
