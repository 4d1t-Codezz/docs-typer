"""Readers for .docx, .odt, .html, .rtf and plain text, all producing a list of Paragraphs."""

import os
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

from .model import NOFMT, SOFT_BREAK, Paragraph, Unreadable, add_run, doc_from_plain

# ---------------------------------------------------------------------------
# .docx reader
# ---------------------------------------------------------------------------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
OFF_VALUES = ("0", "false", "off", "none")


def _wval(el):
    return el.get(W + "val") if el is not None else None


def _parse_rpr(rpr):
    """Return (on, off) sets of formatting toggles from a w:rPr element."""
    on, off = set(), set()
    if rpr is None:
        return on, off
    for tag, key in (("b", "b"), ("i", "i"), ("strike", "s"), ("dstrike", "s")):
        el = rpr.find(W + tag)
        if el is not None:
            v = _wval(el)
            (off if v is not None and v.lower() in OFF_VALUES else on).add(key)
    u = rpr.find(W + "u")
    if u is not None:
        (off if (_wval(u) or "single").lower() == "none" else on).add("u")
    va = rpr.find(W + "vertAlign")
    if va is not None:
        v = _wval(va)
        if v == "superscript":
            on.add("sup"); off.add("sub")
        elif v == "subscript":
            on.add("sub"); off.add("sup")
        else:
            off.update(("sup", "sub"))
    return on, off


def _apply(fmt, onoff):
    on, off = onoff
    return (fmt - off) | on


def _parse_ppr(ppr):
    props = {}
    if ppr is None:
        return props
    jc = ppr.find(W + "jc")
    if jc is not None:
        props["align"] = {"center": "center", "right": "right", "end": "right",
                          "both": "justify", "distribute": "justify"}.get(_wval(jc), "left")
    ol = ppr.find(W + "outlineLvl")
    if ol is not None:
        props["outline"] = int(_wval(ol) or 9)
    num = ppr.find(W + "numPr")
    if num is not None:
        nid = num.find(W + "numId")
        lvl = num.find(W + "ilvl")
        if nid is not None:
            props["numId"] = _wval(nid)
        if lvl is not None:
            props["ilvl"] = int(_wval(lvl) or 0)
    return props


class DocxReader:
    def __init__(self, path):
        try:
            z = zipfile.ZipFile(path)
            self.doc = ET.fromstring(z.read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
            raise Unreadable(str(e))
        self.styles = {}
        self.default_rpr = (set(), set())
        self.default_pstyle = None
        self._load_styles(z)
        self.num_to_abstract, self.level_formats = {}, {}
        self._load_numbering(z)

    def _load_styles(self, z):
        try:
            root = ET.fromstring(z.read("word/styles.xml"))
        except (KeyError, ET.ParseError):
            return
        dd = root.find(W + "docDefaults")
        if dd is not None:
            self.default_rpr = _parse_rpr(dd.find(f"{W}rPrDefault/{W}rPr"))
        for s in root.findall(W + "style"):
            sid = s.get(W + "styleId")
            name = _wval(s.find(W + "name")) or ""
            self.styles[sid] = {
                "type": s.get(W + "type"),
                "name": name.lower(),
                "basedOn": _wval(s.find(W + "basedOn")),
                "rpr": _parse_rpr(s.find(W + "rPr")),
                "ppr": _parse_ppr(s.find(W + "pPr")),
            }
            if s.get(W + "type") == "paragraph" and (s.get(W + "default") or "") in ("1", "true"):
                self.default_pstyle = sid

    def _load_numbering(self, z):
        try:
            root = ET.fromstring(z.read("word/numbering.xml"))
        except (KeyError, ET.ParseError):
            return
        for an in root.findall(W + "abstractNum"):
            aid = an.get(W + "abstractNumId")
            for lvl in an.findall(W + "lvl"):
                fmt = _wval(lvl.find(W + "numFmt")) or "decimal"
                self.level_formats[(aid, int(lvl.get(W + "ilvl") or 0))] = fmt
        for n in root.findall(W + "num"):
            self.num_to_abstract[n.get(W + "numId")] = _wval(n.find(W + "abstractNumId"))

    def _chain(self, sid):
        chain, seen = [], set()
        while sid and sid in self.styles and sid not in seen:
            seen.add(sid)
            chain.append(self.styles[sid])
            sid = self.styles[sid]["basedOn"]
        return list(reversed(chain))  # root first

    def read(self):
        body = self.doc.find(W + "body")
        paras = []
        self._walk_block(body, paras)
        return paras

    def _walk_block(self, el, paras):
        for child in el:
            tag = child.tag
            if tag == W + "p":
                paras.append(self._paragraph(child))
            elif tag in (W + "del", W + "moveFrom", W + "sectPr"):
                continue
            elif tag == MC + "AlternateContent":
                choice = child.find(MC + "Choice")
                if choice is not None:
                    self._walk_block(choice, paras)
            else:  # tables, rows, cells, sdt, ins ...
                self._walk_block(child, paras)

    def _paragraph(self, p):
        ppr = p.find(W + "pPr")
        direct = _parse_ppr(ppr)
        sid = _wval(ppr.find(W + "pStyle")) if ppr is not None else None
        sid = sid or self.default_pstyle
        chain = self._chain(sid)

        merged = {}
        for st in chain:
            merged.update(st["ppr"])
        merged.update(direct)

        para = Paragraph(align=merged.get("align", "left"))
        for st in reversed(chain):
            m = re.fullmatch(r"heading ?(\d)", st["name"])
            if m:
                para.heading = min(int(m.group(1)), 6)
                break
            if st["name"] == "title":
                para.heading = 1
                break
            if st["name"] == "subtitle":
                para.heading = 2
                break
        if not para.heading and merged.get("outline", 9) < 6:
            para.heading = merged["outline"] + 1

        num_id = merged.get("numId")
        if num_id and num_id != "0":
            level = merged.get("ilvl", 0)
            fmt = self.level_formats.get((self.num_to_abstract.get(num_id), level), "decimal")
            if fmt != "none":
                para.list = "bullet" if fmt == "bullet" else "numbered"
                para.level = level

        base = set(self.default_rpr[0])
        if not para.heading:  # let Google Docs' heading style do the styling
            for st in chain:
                base = _apply(base, st["rpr"])
        self._walk_inline(p, para, base)
        return para

    def _walk_inline(self, el, para, base):
        for child in el:
            tag = child.tag
            if tag == W + "r":
                self._run(child, para, base)
            elif tag in (W + "pPr", W + "del", W + "moveFrom"):
                continue
            elif tag == MC + "AlternateContent":
                choice = child.find(MC + "Choice")
                if choice is not None:
                    self._walk_inline(choice, para, base)
            else:  # hyperlink, ins, smartTag, fldSimple, sdt ...
                self._walk_inline(child, para, base)

    def _run(self, r, para, base):
        rpr = r.find(W + "rPr")
        fmt = set(base)
        rstyle = _wval(rpr.find(W + "rStyle")) if rpr is not None else None
        for st in self._chain(rstyle):
            fmt = _apply(fmt, st["rpr"])
        fmt = frozenset(_apply(fmt, _parse_rpr(rpr)))
        for c in r:
            tag = c.tag
            if tag == W + "t":
                add_run(para, c.text or "", fmt)
            elif tag in (W + "tab", W + "ptab"):
                add_run(para, "\t", fmt)
            elif tag == W + "br":
                if c.get(W + "type") in (None, "textWrapping"):
                    add_run(para, SOFT_BREAK, fmt)
            elif tag == W + "cr":
                add_run(para, SOFT_BREAK, fmt)
            elif tag == W + "noBreakHyphen":
                add_run(para, "-", fmt)
            elif tag == MC + "AlternateContent":
                choice = c.find(MC + "Choice")
                if choice is not None:
                    self._run(_wrap_run(choice, rpr), para, base)
            # w:drawing, w:pict, w:object, w:instrText, w:delText,
            # footnote/endnote references: skipped


def _wrap_run(children_parent, rpr):
    r = ET.Element(W + "r")
    if rpr is not None:
        r.append(rpr)
    for c in children_parent:
        r.append(c)
    return r


# ---------------------------------------------------------------------------
# .odt reader
# ---------------------------------------------------------------------------

TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
STYLE = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
FO = "{urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"


class OdtReader:
    def __init__(self, path):
        try:
            z = zipfile.ZipFile(path)
            self.content = ET.fromstring(z.read("content.xml"))
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
            raise Unreadable(str(e))
        self.styles, self.list_styles = {}, {}
        try:
            self._load_styles(ET.fromstring(z.read("styles.xml")))
        except (KeyError, ET.ParseError):
            pass
        self._load_styles(self.content)

    def _load_styles(self, root):
        for s in root.iter(STYLE + "style"):
            on, off = set(), set()
            tp = s.find(STYLE + "text-properties")
            if tp is not None:
                w = tp.get(FO + "font-weight")
                if w:
                    bold = w == "bold" or (w.isdigit() and int(w) >= 600)
                    (on if bold else off).add("b")
                fs = tp.get(FO + "font-style")
                if fs:
                    (on if fs in ("italic", "oblique") else off).add("i")
                for attr, key in (("text-underline-style", "u"), ("text-line-through-style", "s")):
                    v = tp.get(STYLE + attr)
                    if v:
                        (off if v == "none" else on).add(key)
                pos = tp.get(STYLE + "text-position")
                if pos:
                    first = pos.split()[0]
                    if first == "super" or (first.endswith("%") and float(first[:-1] or 0) > 0):
                        on.add("sup"); off.add("sub")
                    elif first == "sub" or (first.endswith("%") and float(first[:-1] or 0) < 0):
                        on.add("sub"); off.add("sup")
                    else:
                        off.update(("sup", "sub"))
            align = None
            pp = s.find(STYLE + "paragraph-properties")
            if pp is not None and pp.get(FO + "text-align"):
                align = {"center": "center", "end": "right", "right": "right",
                         "justify": "justify"}.get(pp.get(FO + "text-align"), "left")
            self.styles[s.get(STYLE + "name")] = {
                "parent": s.get(STYLE + "parent-style-name"),
                "rpr": (on, off),
                "align": align,
            }
        for ls in root.iter(TEXT + "list-style"):
            levels = {}
            for child in ls:
                lvl = int(child.get(TEXT + "level") or 1)
                levels[lvl] = "numbered" if child.tag == TEXT + "list-level-style-number" else "bullet"
            self.list_styles[ls.get(STYLE + "name")] = levels

    def _chain(self, name):
        chain, seen = [], set()
        while name and name in self.styles and name not in seen:
            seen.add(name)
            chain.append(self.styles[name])
            name = self.styles[name]["parent"]
        return list(reversed(chain))

    def _fmt(self, base, style_name):
        fmt = set(base)
        for st in self._chain(style_name):
            fmt = _apply(fmt, st["rpr"])
        return fmt

    def read(self):
        body = self.content.find(f"{OFFICE}body/{OFFICE}text")
        paras = []
        if body is not None:
            self._walk_block(body, paras, None, 0)
        return paras

    def _walk_block(self, el, paras, list_style, depth):
        for child in el:
            tag = child.tag
            if tag in (TEXT + "p", TEXT + "h"):
                paras.append(self._paragraph(child, list_style, depth))
            elif tag == TEXT + "list":
                self._walk_block(child, paras, child.get(TEXT + "style-name") or list_style, depth + 1)
            elif tag in (TEXT + "tracked-changes", TEXT + "sequence-decls", OFFICE + "annotation",
                         OFFICE + "forms") or tag.startswith(DRAW):
                continue
            else:  # list-item, section, table, rows, cells ...
                self._walk_block(child, paras, list_style, depth)

    def _paragraph(self, p, list_style, depth):
        sname = p.get(TEXT + "style-name")
        para = Paragraph()
        for st in self._chain(sname):
            if st["align"]:
                para.align = st["align"]
        if p.tag == TEXT + "h":
            para.heading = min(int(p.get(TEXT + "outline-level") or 1), 6)
        if depth:
            para.list = self.list_styles.get(list_style, {}).get(depth, "bullet")
            para.level = depth - 1
        base = set() if para.heading else self._fmt(set(), sname)
        self._inline(p, para, base)
        return para

    def _inline(self, el, para, fmt):
        add_run(para, el.text or "", frozenset(fmt))
        for child in el:
            tag = child.tag
            if tag == TEXT + "span":
                self._inline(child, para, self._fmt(fmt, child.get(TEXT + "style-name")))
            elif tag == TEXT + "s":
                add_run(para, " " * int(child.get(TEXT + "c") or 1), frozenset(fmt))
            elif tag == TEXT + "tab":
                add_run(para, "\t", frozenset(fmt))
            elif tag == TEXT + "line-break":
                add_run(para, SOFT_BREAK, frozenset(fmt))
            elif tag in (TEXT + "note", OFFICE + "annotation") or tag.startswith(DRAW):
                pass
            else:  # links, bookmarks, fields ...
                self._inline(child, para, fmt)
            add_run(para, child.tail or "", frozenset(fmt))


# ---------------------------------------------------------------------------
# HTML reader (files and rich clipboard, e.g. copied from Google Docs or Word)
# ---------------------------------------------------------------------------

BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "blockquote",
              "pre", "table", "tr", "td", "th", "section", "article", "header", "footer",
              "dd", "dt", "dl", "figure", "figcaption", "address", "main", "nav", "aside"}
VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "wbr", "col", "area", "base",
             "source", "embed", "param", "track"}
SKIP_TAGS = {"script", "style", "head", "title", "noscript", "template", "svg", "object"}
TAG_FMT = {"b": "b", "strong": "b", "i": "i", "em": "i", "cite": "i", "u": "u", "ins": "u",
           "s": "s", "strike": "s", "del": "s", "sup": "sup", "sub": "sub"}
BULLET_TYPES = ("disc", "circle", "square", "none")


def _css(style):
    out = {}
    for decl in (style or "").split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip().lower()] = v.strip().lower()
    return out


class HtmlReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras = []
        self.cur = None
        self.stack = [{"tag": "#root", "fmt": frozenset(), "skip": False, "pre": False}]
        self.ignored = ""  # Word's list marker text (mso-list:Ignore)

    # -- helpers
    def _top(self):
        return self.stack[-1]

    def _props(self):
        para = Paragraph()
        list_depth = 0
        for e in reversed(self.stack):
            if not para.heading and e.get("heading"):
                para.heading = e["heading"]
            if para.align == "left" and e.get("align"):
                para.align = e["align"]
        for e in self.stack:
            if e["tag"] in ("ul", "ol"):
                list_depth += 1
        for e in reversed(self.stack):
            if e["tag"] == "li":
                para.list = e["list"]
                para.level = e["level"] if e["level"] is not None else max(list_depth - 1, 0)
                break
            if e.get("mso_level") is not None:
                para.list = "numbered" if re.search(r"\d", self.ignored) else "bullet"
                para.level = e["mso_level"]
                break
        self.ignored = ""
        return para

    def _break(self):
        if self.cur is not None:
            runs = self.cur.runs
            while runs and not runs[-1][0].rstrip(" "):
                runs.pop()
            if runs:
                runs[-1] = (runs[-1][0].rstrip(" "), runs[-1][1])
            self.paras.append(self.cur)
            self.cur = None

    def _text(self, text):
        top = self._top()
        if top["skip"]:
            if top.get("mso_ignore"):
                self.ignored += text
            return
        if not top["pre"]:
            text = re.sub(r"\s+", " ", text)
            if self.cur is None or not self.cur.runs or self.cur.runs[-1][0].endswith((" ", SOFT_BREAK)):
                text = text.lstrip(" ")
        if not text:
            return
        if self.cur is None:
            self.cur = self._props()
        if top["pre"]:
            parts = text.replace("\r\n", "\n").split("\n")
            for i, part in enumerate(parts):
                if i:
                    self._break()
                    self.cur = self._props()
                add_run(self.cur, part, top["fmt"])
        else:
            add_run(self.cur, text, top["fmt"])

    # -- parser callbacks
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "br":
            if self.cur is not None and self.cur.runs:
                add_run(self.cur, SOFT_BREAK, self._top()["fmt"])
            else:
                self.paras.append(self._props())
            return
        if tag in VOID_TAGS:
            return
        parent = self._top()
        css = _css(a.get("style"))
        fmt = set(parent["fmt"])
        if tag in TAG_FMT:
            fmt.add(TAG_FMT[tag])
            if tag == "sup":
                fmt.discard("sub")
            if tag == "sub":
                fmt.discard("sup")
        w = css.get("font-weight")
        if w:
            bold = w in ("bold", "bolder") or (w.isdigit() and int(w) >= 600)
            (fmt.add if bold else fmt.discard)("b")
        if "font-style" in css:
            (fmt.add if css["font-style"] in ("italic", "oblique") else fmt.discard)("i")
        deco = css.get("text-decoration") or css.get("text-decoration-line")
        if deco:
            if "none" in deco:
                fmt.discard("u"); fmt.discard("s")
            if "underline" in deco:
                fmt.add("u")
            if "line-through" in deco:
                fmt.add("s")
        va = css.get("vertical-align")
        if va in ("super", "sub"):
            fmt.discard("sub" if va == "super" else "sup"); fmt.add("sup" if va == "super" else "sub")
        elif va == "baseline":
            fmt.discard("sup"); fmt.discard("sub")

        entry = {"tag": tag, "fmt": frozenset(fmt),
                 "skip": parent["skip"] or tag in SKIP_TAGS,
                 "pre": parent["pre"] or tag == "pre" or "pre" in css.get("white-space", "")}
        if re.fullmatch(r"h[1-6]", tag):
            entry["heading"] = int(tag[1])
        if css.get("text-align"):
            entry["align"] = {"center": "center", "right": "right", "end": "right",
                              "justify": "justify"}.get(css["text-align"], "left")
        elif a.get("align"):
            entry["align"] = {"center": "center", "right": "right", "justify": "justify"}.get(a["align"].lower(), "left")
        if tag == "li":
            lst = next((e for e in reversed(self.stack) if e["tag"] in ("ul", "ol")), None)
            lt = css.get("list-style-type") or (lst or {}).get("type")
            if lt:
                entry["list"] = "bullet" if lt in BULLET_TYPES else "numbered"
            else:
                entry["list"] = "numbered" if lst and lst["tag"] == "ol" else "bullet"
            lvl = a.get("aria-level")
            entry["level"] = int(lvl) - 1 if lvl and lvl.isdigit() else None
        if tag in ("ul", "ol"):
            entry["type"] = css.get("list-style-type")
        m = re.search(r"mso-list:\s*l\d+\s+level(\d+)", a.get("style") or "", re.I)
        if m:
            entry["mso_level"] = int(m.group(1)) - 1
        if "mso-list:ignore" in (a.get("style") or "").lower().replace(" ", ""):
            entry["skip"] = True
            entry["mso_ignore"] = True
        if tag in BLOCK_TAGS:
            if tag in ("p", "div") and self.cur is not None and not self.cur.runs:
                pass
            else:
                self._break()
        self.stack.append(entry)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break
        else:
            return
        if tag in BLOCK_TAGS:
            self._break()

    def handle_data(self, data):
        self._text(data)

    def read(self, html):
        self.feed(html)
        self.close()
        self._break()
        # Drop leading and trailing empty paragraphs.
        while self.paras and not self.paras[0].runs:
            self.paras.pop(0)
        while self.paras and not self.paras[-1].runs:
            self.paras.pop()
        return self.paras


def read_html(html):
    return HtmlReader().read(html)


# ---------------------------------------------------------------------------
# .rtf reader
# ---------------------------------------------------------------------------

RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "headerl", "headerr",
            "headerf", "footer", "footerl", "footerr", "footerf", "footnote", "listtable",
            "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "themedata",
            "colorschememapping", "datastore", "latentstyles", "fldinst", "object", "shp",
            "nonshppict", "revtbl", "filetbl", "mmathPr", "pgdsctbl", "expandedcolortbl"}
RTF_SPECIAL = {"emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022", "lquote": "\u2018",
               "rquote": "\u2019", "ldblquote": "\u201c", "rdblquote": "\u201d", "tab": "\t",
               "line": SOFT_BREAK, "emspace": " ", "enspace": " ", "qmspace": " "}


def read_rtf(data):
    text = data.decode("latin-1")
    m = re.search(r"\\ansicpg(\d+)", text)
    codepage = f"cp{m.group(1)}" if m else "cp1252"
    token = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}\r\n]+)|[\r\n]+", re.S)

    paras = []
    state = {"fmt": frozenset(), "skip": False, "uc": 1, "listtext": False}
    pstate = {"align": "left", "list": None, "level": 0, "heading": 0}
    stack = []
    cur = Paragraph()
    listtext = ""
    pending_skip = 0
    group_start = False

    def emit(s):
        nonlocal pending_skip, listtext
        if pending_skip:
            n = min(pending_skip, len(s))
            s, pending_skip = s[n:], pending_skip - n
        if not s:
            return
        if state["listtext"]:
            listtext += s
        elif not state["skip"]:
            add_run(cur, s, state["fmt"])

    def end_para():
        nonlocal cur, listtext
        cur.align, cur.heading, cur.level = pstate["align"], pstate["heading"], pstate["level"]
        if pstate["list"]:
            cur.list = "numbered" if re.search(r"[0-9a-zA-Z]", listtext) else "bullet"
        paras.append(cur)
        cur = Paragraph()
        listtext = ""

    for mt in token.finditer(text):
        word, arg, hexc, sym, brace, plain = mt.groups()
        if not any(mt.groups()):
            continue  # raw line breaks are not content in RTF
        first = group_start
        group_start = False
        if brace == "{":
            stack.append(dict(state))
            group_start = True
        elif brace == "}":
            if stack:
                state = stack.pop()
        elif plain is not None:
            emit(plain)
        elif hexc is not None:
            emit(bytes([int(hexc, 16)]).decode(codepage, errors="replace"))
        elif sym is not None:
            if sym == "*":
                state["skip"] = True
            elif sym in "\\{}":
                emit(sym)
            elif sym == "~":
                emit("\u00a0")
            elif sym == "_":
                emit("-")
            elif sym in "\r\n":
                if not state["skip"]:
                    end_para()
        elif word is not None:
            n = int(arg) if arg is not None else None
            on = n != 0
            f = set(state["fmt"])
            if first and word in RTF_SKIP:
                state["skip"] = True
            elif word in ("listtext", "pntext"):
                state["listtext"] = True
            elif word == "par":
                if not state["skip"]:
                    end_para()
            elif word == "pard":
                pstate = {"align": "left", "list": None, "level": 0, "heading": 0}
            elif word in ("ql", "qc", "qr", "qj"):
                pstate["align"] = {"ql": "left", "qc": "center", "qr": "right", "qj": "justify"}[word]
            elif word == "ls":
                pstate["list"] = True
            elif word == "ilvl":
                pstate["level"] = n or 0
            elif word == "outlinelevel":
                if n is not None and n < 6:
                    pstate["heading"] = n + 1
            elif word == "plain":
                state["fmt"] = frozenset()
            elif word in ("b", "i", "strike", "striked"):
                key = {"b": "b", "i": "i", "strike": "s", "striked": "s"}[word]
                (f.add if on else f.discard)(key)
                state["fmt"] = frozenset(f)
            elif word == "ul":
                (f.add if on else f.discard)("u")
                state["fmt"] = frozenset(f)
            elif word in ("ulnone", "ul0"):
                f.discard("u"); state["fmt"] = frozenset(f)
            elif word.startswith("ul") and word not in ("ulc",):
                f.add("u"); state["fmt"] = frozenset(f)
            elif word == "super":
                f.discard("sub"); f.add("sup"); state["fmt"] = frozenset(f)
            elif word == "sub":
                f.discard("sup"); f.add("sub"); state["fmt"] = frozenset(f)
            elif word == "nosupersub":
                f.discard("sup"); f.discard("sub"); state["fmt"] = frozenset(f)
            elif word == "uc":
                state["uc"] = n or 0
            elif word == "u":
                emit(chr(n + 65536 if n < 0 else n))
                pending_skip = state["uc"]
            elif word in RTF_SPECIAL:
                emit(RTF_SPECIAL[word])
            continue
    if cur.runs:
        end_para()
    # Join UTF-16 surrogate pairs produced by \u escapes.
    for p in paras:
        p.runs = [(t.encode("utf-16", "surrogatepass").decode("utf-16"), f) for t, f in p.runs]
    while paras and not paras[-1].runs:
        paras.pop()
    return paras


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".gdoc", ".gsheet", ".gslides"):
        raise Unreadable("That's a Google Drive shortcut. In Google Docs use File \u2192 Download \u2192 "
                         "Microsoft Word (.docx), or just copy and paste.")
    try:
        if ext in (".docx", ".docm", ".dotx"):
            return DocxReader(path).read()
        if ext in (".odt", ".ott"):
            return OdtReader(path).read()
        if ext in (".html", ".htm", ".xhtml"):
            with open(path, "rb") as fh:
                raw = fh.read()
            m = re.search(rb'charset=["\']?([\w-]+)', raw[:4096])
            return read_html(raw.decode(m.group(1).decode() if m else "utf-8", errors="replace"))
        if ext == ".rtf":
            with open(path, "rb") as fh:
                return read_rtf(fh.read())
        if ext in (".txt", ".md", ".text", ""):
            with open(path, "rb") as fh:
                raw = fh.read()
            for enc in ("utf-8-sig", "utf-16", "cp1252"):
                try:
                    return doc_from_plain(raw.decode(enc))
                except UnicodeDecodeError:
                    continue
    except Unreadable:
        raise
    except Exception as e:  # noqa: BLE001 - any parser failure means "can't read"
        raise Unreadable(f"Couldn't read {os.path.basename(path)} ({e}).")
    raise Unreadable(f"Can't read {ext or 'that file'}. Try .docx, .rtf, .odt or .html.")
