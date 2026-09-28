import os
import tempfile
import unittest
import zipfile

from docstyper.model import Unreadable
from docstyper.readers import load_file, read_html, read_rtf

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def summary(paras):
    return [(p.heading, p.list, p.level, p.align, [(t, "".join(sorted(f))) for t, f in p.runs]) for p in paras]


class HtmlTests(unittest.TestCase):
    def test_google_docs_clipboard(self):
        html = ('<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1">'
                '<h1 dir="ltr"><span style="font-size:20pt;font-weight:400">My Title</span></h1>'
                '<p dir="ltr" style="text-align: center;"><span style="font-weight:700">Bold</span><span> and </span>'
                '<span style="font-style:italic">italic</span><span style="vertical-align:super">2</span></p><br>'
                '<ul><li aria-level="1" style="list-style-type:disc"><p><span>one</span></p></li>'
                '<li aria-level="2" style="list-style-type:circle"><p><span>two</span></p></li></ul>'
                '<ol><li aria-level="1" style="list-style-type:decimal"><p><span>num</span></p></li></ol>'
                '<p><span style="text-decoration:line-through">gone</span> &amp; done</p></b>')
        self.assertEqual(summary(read_html(html)), [
            (1, None, 0, "left", [("My Title", "")]),
            (0, None, 0, "center", [("Bold", "b"), (" and ", ""), ("italic", "i"), ("2", "sup")]),
            (0, None, 0, "left", []),
            (0, "bullet", 0, "left", [("one", "")]),
            (0, "bullet", 1, "left", [("two", "")]),
            (0, "numbered", 0, "left", [("num", "")]),
            (0, None, 0, "left", [("gone", "s"), (" & done", "")]),
        ])


class RtfTests(unittest.TestCase):
    def test_formatting_lists_and_unicode(self):
        rtf = (b"{\\rtf1\\ansi\\ansicpg1252{\\fonttbl\\f0 Helvetica;}{\\colortbl;\\red0\\green0\\blue0;}\n"
               b"\\pard\\qc\\b Hello\\b0  w\\'f6rld \\u8212? done\\par\n"
               b"\\pard\\ls1\\ilvl0{\\listtext \\'95\\tab}item\\par\n"
               b"{\\listtext 1.\\tab}\\i num\\i0\\par\n}")
        self.assertEqual(summary(read_rtf(rtf)), [
            (0, None, 0, "center", [("Hello", "b"), (" wörld — done", "")]),
            (0, "bullet", 0, "left", [("item", "")]),
            (0, "numbered", 0, "left", [("num", "i")]),
        ])


class ZipReaderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def write_zip(self, name, files):
        path = os.path.join(self.dir, name)
        with zipfile.ZipFile(path, "w") as z:
            for k, v in files.items():
                z.writestr(k, v)
        return path

    def test_docx(self):
        doc = f'''<w:document {W}><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Head</w:t></w:r></w:p>
<w:p><w:pPr><w:jc w:val="both"/></w:pPr><w:r><w:rPr><w:b/><w:u w:val="single"/></w:rPr><w:t xml:space="preserve">Bold under </w:t></w:r><w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t>plain</w:t></w:r><w:r><w:br/><w:t>line2</w:t></w:r><w:r><w:rPr><w:strike/></w:rPr><w:delText>x</w:delText></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr></w:pPr><w:hyperlink><w:r><w:t>bullet</w:t></w:r></w:hyperlink></w:p>
<w:p/>
</w:body></w:document>'''
        styles = f'<w:styles {W}><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:rPr><w:b/></w:rPr></w:style></w:styles>'
        num = (f'<w:numbering {W}><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/></w:lvl>'
               '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')
        path = self.write_zip("t.docx", {"word/document.xml": doc, "word/styles.xml": styles,
                                         "word/numbering.xml": num})
        self.assertEqual(summary(load_file(path)), [
            (2, None, 0, "left", [("Head", "")]),
            (0, None, 0, "justify", [("Bold under ", "bu"), ("plain\x0bline2", "")]),
            (0, "bullet", 1, "left", [("bullet", "")]),
            (0, None, 0, "left", []),
        ])

    def test_odt(self):
        odt = '''<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
<office:automatic-styles><style:style style:name="T1" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>
<style:style style:name="P1" style:family="paragraph"><style:paragraph-properties fo:text-align="end"/></style:style>
<text:list-style style:name="L1"><text:list-level-style-number text:level="1"/></text:list-style></office:automatic-styles>
<office:body><office:text><text:h text:outline-level="2">Heading</text:h>
<text:p text:style-name="P1">a<text:s text:c="2"/><text:span text:style-name="T1">bold</text:span> tail</text:p>
<text:list text:style-name="L1"><text:list-item><text:p>first</text:p></text:list-item></text:list></office:text></office:body></office:document-content>'''
        path = self.write_zip("t.odt", {"content.xml": odt})
        self.assertEqual(summary(load_file(path)), [
            (2, None, 0, "left", [("Heading", "")]),
            (0, None, 0, "right", [("a  ", ""), ("bold", "b"), (" tail", "")]),
            (0, "numbered", 0, "left", [("first", "")]),
        ])

    def test_drive_shortcut_message(self):
        with self.assertRaises(Unreadable) as ctx:
            load_file("notes.gdoc")
        self.assertIn("Google Drive shortcut", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
