from __future__ import annotations

import re
from pathlib import Path


def save_document(path: str | Path, content: str, title: str = "观海·听涛文稿") -> Path:
    """Save TXT, Markdown or a genuine Word/WPS-compatible DOCX document."""
    destination = Path(path)
    suffix = destination.suffix.lower()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".docx":
        from docx import Document
        from docx.enum.text import WD_LINE_SPACING
        from docx.oxml.ns import qn
        from docx.shared import Pt

        document = Document()
        normal = document.styles["Normal"]
        normal.font.name = "Microsoft YaHei UI"
        normal.font.size = Pt(11)
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei UI")
        normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        document.core_properties.title = title
        lines = content.splitlines()
        if not any(line.startswith("#") for line in lines):
            document.add_heading(title, level=0)
        for line in lines:
            heading = re.match(r"^(#{1,3})\s+(.+)$", line)
            if heading:
                document.add_heading(heading.group(2).strip(), level=min(3, len(heading.group(1))))
            elif re.match(r"^[-*]\s+", line):
                document.add_paragraph(re.sub(r"^[-*]\s+", "", line), style="List Bullet")
            elif re.match(r"^\d+[.、]\s*", line):
                document.add_paragraph(re.sub(r"^\d+[.、]\s*", "", line), style="List Number")
            elif line.strip() == "---":
                continue
            else:
                document.add_paragraph(line)
        document.save(destination)
    elif suffix == ".md":
        destination.write_text(content if content.startswith("#") else f"# {title}\n\n{content}", encoding="utf-8-sig")
    elif suffix == ".txt":
        destination.write_text(content, encoding="utf-8-sig")
    else:
        raise ValueError("仅支持 TXT、Markdown 和 DOCX（WPS 文字兼容）格式")
    return destination
