#!/usr/bin/env python3
"""Unpack Blackboard gradebook downloads into one folder per assignment.

Usage:
    python3 unpack-submissions.py GRADEBOOK.zip [GRADEBOOK.zip ...] [-o OUTPUT_DIR] [--force]

For each gradebook ZIP (gradebook_<course>_<assignment>_<timestamp>.zip):

  * Creates a CamelCase folder named after the assignment, with the Blackboard
    tags such as "[Assignment]", "(PDF)" or "(Quiz)" dropped
    ("Library Loans [Assignment] (PDF)" becomes LibraryLoans).
  * Puts source code (Java, C, C++, Python, HTML/CSS, JavaScript/TypeScript,
    SML, OCaml, Haskell, Prolog and some 60 other languages, plus build files
    such as Makefile) in a folder named after the student's username, under
    the name the student gave it (TemperatureApplication.java), so it can be
    compiled and run as submitted. Source code is archived as it is and not
    converted to PDF. Folders inside a submitted ZIP are kept
    (src/edu/smcm/Main.java). If two attempts contain a file with the same
    name, each attempt goes in its own subfolder (Attempt1, Attempt2, ...).
  * Renames every other submitted file after the student's username:
        username.ext                   one file of that type
        username-00.ext, -01, ...      several files of the same type, in the
                                       order they were submitted (attempt time,
                                       then upload order from the receipt)
    Extensions are lowercased.
  * Gives every file a single suffix for its real type, judged by its
    contents: "essay.doc.pdf" becomes .pdf if it holds a PDF and .doc if it
    holds a Word file; "Hello.java.txt" holding Java becomes Hello.java; a
    "report.pdf" that is really a Word file becomes .docx. A file with no
    suffix is assumed to be Word unless its contents show it is something
    else (a PDF, an image, plain text ...).
  * Removes built files wherever they appear: compiled code (.class, .jar,
    .o, .obj, .exe, .dll, .so, .pyc, .hi, .qlf, .beam ...), executables
    recognised by their contents even without a suffix, and build folders
    (__pycache__, target, node_modules, .stack-work, .cm ...). They are
    listed in manifest.csv as removed.
  * Converts audio to MP3 (username.mp3, VBR about 130 kbit/s) and video
    to MP4 (username.mp4: H.264, long side at most 1280 px, AAC sound),
    keeping the renamed original. Whether a file is audio or video is
    decided by what is in it (a .webm or .ogg may be either). MP3 and MP4
    originals are left as they are.
  * Keeps Apple Pages, Numbers and Keynote documents whole, however they
    arrive (essay.pages, essay.pages.zip, or an Essay.pages folder inside a
    student's ZIP), and converts them with LibreOffice. If LibreOffice can't
    read one, the preview stored inside the file is used instead: a full PDF
    in older iWork versions, only a picture of the first page in current ones
    (username-preview.jpg).
  * Looks inside JAR (and WAR/EAR) files: any source code in them goes into
    the student's folder, keeping its package folders (edu/smcm/Main.java),
    and the rest of the JAR (classes, manifest, resources, bundled
    libraries) is discarded. A JAR with no source is removed.
  * Expands ZIPs that students submitted and treats their contents as
    submitted files; the ZIPs themselves are not kept.
  * Converts every other file to PDF or JPEG, keeping the renamed original:
        Word, ODT, PowerPoint,
        Excel, RTF ...       -> username.pdf (via LibreOffice)
        PNG, GIF, HEIC ...   -> username.jpg
    A converted copy carries its source suffix (username-docx.pdf) only when
    the plain name would clash with an original or another copy. Files that
    are plain text (ASCII or Unicode: .txt, .md, .csv, .json ...) are kept as
    they are, with no PDF, and so are PDF and JPEG files.
  * Moves the Blackboard receipts (.txt) into a Receipts subfolder; if a
    receipt holds typed submission text or comments, these also go into
    username-text.pdf.
  * Writes manifest.csv listing every original name, new name and conversion.

Several ZIPs for the same assignment are merged and duplicate entries ignored,
so a re-download of the same gradebook does no harm.

Converters: ffmpeg (audio and video) and LibreOffice (Word, Pages and other
documents) are needed only when a batch of submissions contains such files.
If one is missing when it is needed, the program asks before downloading it
into the Tools folder next to this script (no administrator rights needed),
and prints step-by-step instructions for this computer if you say no.
  --download yes|no            download without asking, or never
  --remove-converters          delete the Tools folder when you have finished
  --instructions               show how to install both converters by hand

Requirements: Python 3.8+ with Pillow and reportlab. The wrapper scripts
(unpack-submissions.sh for macOS and Linux, unpack-submissions.cmd for
Windows) set these up, help install Python itself if it is missing, and
remove the Python environment too with --remove-converters.

Written with Claude Opus 5.5 (Anthropic).
"""

import argparse
import csv
import html
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

# --------------------------------------------------------------------------
# File-name patterns
# --------------------------------------------------------------------------

# "<assignment>_<username>_attempt_<timestamp>_<original name>" for a file,
# "<assignment>_<username>_attempt_<timestamp>.txt" for the receipt.
ENTRY_RE = re.compile(
    r"^(?P<assignment>.+?)_(?P<user>[^_/\\]+)_attempt_"
    r"(?P<ts>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})"
    r"(?:_(?P<orig>.+)|(?P<receipt>\.txt))$",
    re.DOTALL,
)

# Fallback when a ZIP has no entries to take the assignment name from.
ZIPNAME_RE = re.compile(
    r"gradebook_[A-Za-z0-9]+_\d+_(?P<enc>.+)_\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.zip$",
    re.IGNORECASE,
)
# Blackboard drops the "%" from URL escapes: "Valid20Date205bAssignment5d".
ZIPNAME_ESCAPES = {"20": " ", "5b": "[", "5d": "]", "28": "(", "29": ")",
                   "2c": ",", "26": "&", "27": "'", "3a": ":", "2d": "-"}

# Things to ignore inside student ZIPs.
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}

# --------------------------------------------------------------------------
# Conversion categories
# --------------------------------------------------------------------------

TARGET_EXTS = {"pdf", "jpg", "jpeg", "jpe", "jfif"}
OFFICE_EXTS = {"doc", "docx", "docm", "dot", "dotx", "odt", "ott", "rtf",
               "wpd", "pages", "numbers", "key", "ppt", "pptx", "pps", "ppsx", "odp",
               "xls", "xlsx", "xlsm", "ods", "odg", "vsd", "vsdx", "pub"}
IMAGE_EXTS = {"png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif",
              "ico", "jfif"}
# Source code: kept under its original name in a folder per student.
# Matched case-insensitively, so "Main.JAVA" and "prog.C" count.
SOURCE_EXTS = {
    "java", "jsh",                                         # Java
    "c", "h", "i",                                         # C
    "cpp", "cc", "cxx", "c++", "cp", "hpp", "hh", "hxx", "h++", "ipp",
    "tpp", "inl", "ino",                                   # C++, Arduino
    "py", "pyw", "pyi", "ipynb",                           # Python
    "html", "htm", "xhtml", "css", "scss", "sass", "less", # web pages
    "js", "mjs", "cjs", "jsx", "ts", "tsx", "vue", "svelte",  # JavaScript
    "sml", "sig", "fun", "ml", "mli", "mly", "mll",        # SML, OCaml
    "hs", "lhs", "hsc", "cabal",                           # Haskell
    "pl", "pro", "prolog", "p", "plt", "lgt",              # Prolog
    "cs", "fs", "fsi", "fsx", "vb",                        # .NET
    "kt", "kts", "scala", "sc", "groovy", "gradle", "clj", "cljs", "cljc",
    "edn",                                                 # other JVM
    "go", "rs", "swift", "m", "mm", "d", "zig", "nim", "v", "dart",
    "rb", "pm", "php", "lua", "r", "jl", "tcl", "awk", "sed",
    "lisp", "lsp", "cl", "el", "scm", "ss", "rkt", "erl", "hrl", "ex",
    "exs", "elm", "purs", "idr", "agda", "lean", "coq",
    "pas", "pp", "dpr", "f", "for", "f77", "f90", "f95", "f03", "f08",
    "cob", "cbl", "adb", "ads", "bas", "st",
    "asm", "s", "nasm", "a51",                             # assembly
    "vhd", "vhdl", "sv", "svh", "vh",                      # hardware
    "sql", "sh", "bash", "zsh", "ksh", "csh", "fish", "bat", "cmd", "ps1",
    "mk", "make", "cmake", "y", "yy", "l", "ll", "g4", "proto",
    "tex", "sty", "bib", "rmd", "qmd",
}
# Build files that have no useful extension.
SOURCE_NAMES = {"makefile", "gnumakefile", "cmakelists.txt", "dockerfile",
                "rakefile", "gemfile", "build.xml", "pom.xml", "package.json",
                "setup.py", "requirements.txt", "stack.yaml", "cabal.project"}

# Everything converted to a line-numbered PDF (source code plus plain text).
TEXT_EXTS = SOURCE_EXTS | {"txt", "text", "md", "csv", "tsv", "json", "xml",
                           "yml", "yaml", "toml", "ini", "cfg", "log",
                           "drawio", "properties", "iml", "out", "in", "dat"}


def safe_relpath(name):
    """Keep a file's own name (and folders inside a student ZIP), but never
    anything that could escape the student's folder."""
    parts = [p for p in re.split(r"[\\/]+", name)
             if p not in ("", ".", "..") and not p.endswith(":")]
    return "/".join(parts) or "unnamed"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def camel_case(title):
    """'Variables, Assignment and Main (Quiz)' -> 'VariablesAssignmentAndMain'."""
    title = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title)
    words = re.findall(r"[A-Za-z0-9]+", title)
    name = "".join(w[:1].upper() + w[1:] for w in words)
    return name or "Assignment"


def assignment_from_zipname(zip_path):
    m = ZIPNAME_RE.search(Path(zip_path).name)
    if not m:
        return Path(zip_path).stem
    enc = m.group("enc")
    out, i = [], 0
    while i < len(enc):
        pair = enc[i:i + 2].lower()
        if pair in ZIPNAME_ESCAPES:
            out.append(ZIPNAME_ESCAPES[pair])
            i += 2
        else:
            out.append(enc[i])
            i += 1
    return "".join(out)


# --------------------------------------------------------------------------
# What a file really is
# --------------------------------------------------------------------------

# Compiled output, removed wherever it turns up (by extension or contents).
BUILT_EXTS = {
    "class", "jar", "war", "ear",                          # Java
    "o", "obj", "a", "lib", "so", "dylib", "dll", "exe", "out",
    "pdb", "ilk", "exp", "idb", "pch", "gch", "ipch", "tlog",
    "lastbuildstate", "suo", "ncb", "sdf", "dsym",         # C, C++, Visual Studio
    "pyc", "pyo", "pyd",                                   # Python
    "hi", "dyn_hi", "dyn_o", "p_hi", "p_o",                # Haskell (GHC)
    "qlf", "wam", "po",                                    # Prolog
    "cmo", "cmi", "cmx", "cmxa", "cma", "cmt", "cmti",     # OCaml
    "beam", "elc", "fasl", "zo", "rlib", "rmeta",          # Erlang, Lisp, Racket, Rust
}
# Folders that hold nothing but build output (or downloaded packages).
BUILD_DIRS = {"__pycache__", ".cm", ".stack-work", "dist-newstyle",
              "node_modules", "target", ".gradle", "compiled", ".vs", "ipch"}
BUILT_CONTENT = {"class", "elf", "macho", "exe", "ar", "jar"}

# Suffixes whose contents can be checked, and what the contents must be.
OLE_SUFFIXES = {"doc", "dot", "xls", "xlt", "ppt", "pps", "pot", "vsd", "pub",
                "msg", "mpp", "wps"}
ZIP_KINDS = {"zip", "docx", "xlsx", "pptx", "odt", "ods", "odp", "odg", "jar",
             "epub"}
FAMILY = {"pdf": {"pdf"}, "rtf": {"rtf"},
          "docx": {"docx"}, "docm": {"docx"}, "dotx": {"docx"}, "dotm": {"docx"},
          "xlsx": {"xlsx"}, "xlsm": {"xlsx"}, "xltx": {"xlsx"},
          "pptx": {"pptx"}, "pptm": {"pptx"}, "ppsx": {"pptx"}, "potx": {"pptx"},
          "odt": {"odt"}, "ott": {"odt"}, "ods": {"ods"}, "odp": {"odp"},
          "odg": {"odg"}, "zip": ZIP_KINDS, "jar": {"jar", "zip"},
          "war": {"jar", "zip"}, "ear": {"jar", "zip"}, "epub": {"epub", "zip"},
          "pages": {"iwork", "zip"}, "key": {"iwork", "zip"},
          "numbers": {"iwork", "zip"}, "vsdx": {"zip"},
          "sb3": {"zip"}, "jpg": {"jpg"}, "jpeg": {"jpg"}, "jpe": {"jpg"},
          "jfif": {"jpg"}, "png": {"png"}, "gif": {"gif"}, "bmp": {"bmp"},
          "tif": {"tiff"}, "tiff": {"tiff"}, "webp": {"webp"},
          "heic": {"heic"}, "heif": {"heic"}, "class": {"class"},
          "exe": {"exe"}, "dll": {"exe"}}
FAMILY.update({s: {"ole"} for s in OLE_SUFFIXES})
# Name to give a file whose contents give it away and whose suffix lies.
CONTENT_EXT = {"ole": "doc", "tiff": "tif"}

# Audio and video. MP4-family files (mp4, mov, m4a, 3gp ...) share one format,
# as do Matroska and WebM. ".ts" is left out: it is far more often TypeScript.
ISO_MEDIA = {"mp4", "mov", "m4a"}
MEDIA_FAMILY = {
    "mp4": ISO_MEDIA, "m4v": ISO_MEDIA, "mov": ISO_MEDIA, "qt": ISO_MEDIA,
    "3gp": ISO_MEDIA, "3g2": ISO_MEDIA, "m4a": ISO_MEDIA, "m4b": ISO_MEDIA,
    "m4r": ISO_MEDIA, "mp3": {"mp3"}, "aac": {"aac"}, "wav": {"wav"},
    "avi": {"avi"}, "ogg": {"ogg"}, "oga": {"ogg"}, "ogv": {"ogg"},
    "opus": {"ogg"}, "spx": {"ogg"}, "flac": {"flac"}, "mkv": {"mkv", "webm"},
    "mka": {"mkv", "webm"}, "webm": {"mkv", "webm"}, "aiff": {"aiff"},
    "aif": {"aiff"}, "aifc": {"aiff"}, "wma": {"wmv"}, "wmv": {"wmv"},
    "asf": {"wmv"}, "amr": {"amr"}, "3ga": {"amr"}, "caf": {"caf"},
    "mpg": {"mpg"}, "mpeg": {"mpg"}, "vob": {"mpg"}, "mts": {"ts"},
    "m2ts": {"ts"}, "flv": {"flv"},
}
FAMILY.update(MEDIA_FAMILY)
MEDIA_EXTS = set(MEDIA_FAMILY) | {"ts"}
AUDIO_ONLY_EXTS = {"mp3", "aac", "wav", "oga", "opus", "spx", "flac", "mka",
                   "aiff", "aif", "aifc", "wma", "amr", "3ga", "caf", "m4a",
                   "m4b", "m4r"}

# Suffixes that may be stripped when they sit inside a name ("essay.doc.pdf").
# Short ones are left alone because they are often part of a real name
# ("types.d.ts", "jquery.min.js").
AMBIGUOUS = {"d", "p", "s", "l", "y", "m", "f", "v", "i", "r", "a", "o", "st",
             "sc", "pp", "cp", "ss", "cl", "el", "ex", "in", "out", "dat",
             "log", "lib", "po", "key", "pages", "numbers"}
KNOWN_TYPES = set(FAMILY) | TEXT_EXTS | BUILT_EXTS | OFFICE_EXTS | IMAGE_EXTS
INNER_OK = KNOWN_TYPES - AMBIGUOUS

SUFFIX_RE = re.compile(r"^[a-z0-9+_-]{1,12}$")


def suffixes_of(base):
    """The trailing suffixes of a name, last first ("a.doc.pdf" -> pdf, doc).
    Stops at anything that doesn't look like a suffix ("Lab 2. final.pdf")."""
    parts = base.split(".")
    out = []
    for p in reversed(parts[1:]):
        if not SUFFIX_RE.match(p.lower()):
            break
        out.append(p)
    if out and len(out) == len(parts) - 1 and parts[0] == "":
        out.pop()                  # ".gitignore" is a name, not a suffix
    return out


# Apple iWork documents (Pages, Numbers, Keynote). Each is really a folder
# (a macOS "package") or a ZIP of one, so it must be kept whole rather than
# unpacked like a student's ZIP.
IWORK_EXTS = {"pages", "numbers", "key"}
IWORK_MARKERS = ("Index/Document.iwa", "Index.zip", "index.xml.gz",
                 "index.xml", "index.apxl.gz", "index.apxl")
IWORK_COMPANIONS = ("preview.jpg", "QuickLook/", "Metadata/",
                    "buildVersionHistory.plist")


def iwork_root(names):
    """If these ZIP entries hold an iWork document, return the folder inside
    the ZIP that is the document ("" when the ZIP is the document itself, as
    with a current single-file .pages), otherwise None."""
    roots = set()
    for n in names:
        for marker in IWORK_MARKERS:
            if n == marker:
                roots.add("")
            elif n.endswith("/" + marker):
                root = n[:-len(marker)]
                if root.rstrip("/").rsplit("/", 1)[-1].lower().rsplit(".", 1)[-1] \
                        in IWORK_EXTS:
                    roots.add(root)
    if "" in roots:
        if any(n.startswith(c) for n in names for c in IWORK_COMPANIONS):
            return ""
        roots.discard("")
    # A folder only counts as the document if it is all the ZIP holds; a
    # student's project ZIP with an Essay.pages folder in it is unpacked
    # normally, and the folder is gathered up by expand_student_zip.
    real = [n for n in names if not n.endswith("/") and "__MACOSX/" not in n
            and os.path.basename(n).lower() not in JUNK_NAMES]
    roots = {r for r in roots if all(n.startswith(r) for n in real)}
    return min(roots, key=len) if roots else None


def iwork_kind(names, root=""):
    """Pages, Numbers or Keynote, from the folder name or, failing that, the
    contents (a best guess: Keynote and Numbers leave recognisable traces)."""
    ext = root.rstrip("/").rsplit("/", 1)[-1].rsplit(".", 1)[-1].lower()
    if ext in IWORK_EXTS:
        return ext
    if any("index.apxl" in n or "/Slide" in n or "MasterSlide" in n for n in names):
        return "key"
    if any("CalculationEngine" in n or "/Tables/" in n for n in names):
        return "numbers"
    return "pages"


def unwrap_iwork(data):
    """A ZIP that merely contains "essay.pages/..." becomes the document itself."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            root = iwork_root(names)
            if not root:
                return data
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
                for info in z.infolist():
                    if info.filename.startswith(root) and not info.is_dir():
                        w.writestr(info.filename[len(root):], z.read(info))
            return out.getvalue()
    except zipfile.BadZipFile:
        return data


def iwork_preview(data):
    """The preview iWork stores inside a document: a full PDF in older
    versions, only a picture of the first page in current ones."""
    wanted = ["quicklook/preview.pdf", "preview.jpg", "quicklook/thumbnail.jpg",
              "preview-web.jpg", "quicklook/thumbnail.png", "preview-micro.jpg"]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            lower = {n.lower(): n for n in z.namelist()}
            for w in wanted:
                if w in lower:
                    return w.rsplit(".", 1)[1], z.read(lower[w])
    except zipfile.BadZipFile:
        pass
    return None, None


def content_type(data):
    """What the bytes say the file is, or None for text and unknown formats."""
    if data[:4] == b"\xca\xfe\xba\xbe" and len(data) >= 8:
        # Java class files and Mach-O universal binaries share this magic.
        return "class" if int.from_bytes(data[4:8], "big") >= 45 else "macho"
    if data[:4] == b"\x7fELF":
        return "elf"
    if data[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                    b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"):
        return "macho"
    if data[:2] == b"MZ" and len(data) >= 64:
        off = int.from_bytes(data[60:64], "little")
        if data[off:off + 4] == b"PE\x00\x00":
            return "exe"
    if data[:8] == b"!<arch>\n":
        return "ar"
    if data[:5] == b"%PDF-" or (data[:2] != b"PK" and b"%PDF-" in data[:1024]
                                and b"%%EOF" in data[-2048:]):
        return "pdf"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole"
    if data[:5] == b"{\\rtf":
        return "rtf"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1",
                                                b"msf1", b"hevc"):
        return "heic"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        return ("m4a" if brand in (b"M4A ", b"M4B ", b"M4P ")
                else "mov" if brand == b"qt  " else "mp4")
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "avi"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm" if b"webm" in data[:64] else "mkv"
    if data[:4] == b"FORM" and data[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if data[:8] == b"\x30\x26\xb2\x75\x8e\x66\xcf\x11":
        return "wmv"
    if data[:5] == b"#!AMR":
        return "amr"
    if data[:4] == b"caff":
        return "caf"
    if data[:3] == b"FLV":
        return "flv"
    if data[:4] == b"\x00\x00\x01\xba":
        return "mpg"
    if len(data) > 376 and data[0] == 0x47 and data[188] == 0x47 and data[376] == 0x47:
        return "ts"
    if data[:3] == b"ID3":
        return "mp3"
    if len(data) > 1 and data[0] == 0xFF and (data[1] & 0xF6) == 0xF0:
        return "aac"
    if len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0 \
            and (data[1] & 0x06) == 0x02:
        return "mp3"
    if data[:2] == b"BM" and len(data) > 14 and \
            int.from_bytes(data[2:6], "little") == len(data):
        return "bmp"
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                if "mimetype" in names:
                    mt = z.read("mimetype").decode("ascii", "ignore")
                    for key, ext in (("opendocument.text", "odt"),
                                     ("opendocument.presentation", "odp"),
                                     ("opendocument.spreadsheet", "ods"),
                                     ("opendocument.graphics", "odg"),
                                     ("epub", "epub")):
                        if key in mt:
                            return ext
                if any(n.startswith("word/") for n in names):
                    return "docx"
                if any(n.startswith("ppt/") for n in names):
                    return "pptx"
                if any(n.startswith("xl/") for n in names):
                    return "xlsx"
                if iwork_root(names) is not None:
                    return "iwork"
                if "META-INF/MANIFEST.MF" in names and \
                        any(n.endswith(".class") for n in names):
                    return "jar"
                return "zip"
        except zipfile.BadZipFile:
            pass
    return None


def in_build_dir(path):
    return any(p.lower() in BUILD_DIRS or p.lower().startswith("cmake-build-")
               for p in re.split(r"[\\/]+", path)[:-1])


def classify(name, data):
    """Work out a file's real type from its name and contents.

    Returns (extension, cleaned name, is source code, is built output).
    The cleaned name has a single suffix for the real type:
    "essay.doc.pdf" holding a PDF becomes "essay.pdf", holding a Word file
    "essay.doc"; "Hello.java.txt" holding Java becomes "Hello.java".
    A file with no suffix is taken to be Word unless its contents say
    otherwise (a PDF, an image, plain text ...).
    """
    base = os.path.basename(name)
    content = content_type(data)
    textual = content is None and decode_text(data) is not None
    sufs = suffixes_of(base)
    low = [s.lower() for s in sufs]

    built = (content in BUILT_CONTENT or (bool(low) and low[0] in BUILT_EXTS)
             or base.lower() == "a.out" or in_build_dir(name))

    if base.lower() in SOURCE_NAMES and textual:
        return re.sub(r"[^a-z0-9]+", "-", base.lower()), base, True, built

    if content == "iwork":         # "essay.pages", "essay.pages.zip", "essay"
        kind = next((s for s in low if s in IWORK_EXTS), None)
        if not kind:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
            kind = iwork_kind(names, iwork_root(names) or "")
        strip = 0
        for s in low:
            if s in KNOWN_TYPES or s == "zip":
                strip += 1
            else:
                break
        parts = base.split(".")
        stem = ".".join(parts[:len(parts) - strip]) if strip else base
        return kind, f"{stem}.{kind}", False, False

    def fits(s):
        if s in FAMILY:
            return content in FAMILY[s]
        if s in TEXT_EXTS:
            return textual
        return content is None

    # The last suffix, then any inner suffixes that name a real file type.
    candidates = [(i, s) for i, s in enumerate(low) if i == 0 or s in INNER_OK]
    fitting = [c for c in candidates if fits(c[1])]
    if textual:              # "Main.java.txt": the source suffix is the real one
        fitting = [c for c in fitting if c[1] in SOURCE_EXTS] or fitting

    if fitting:
        i, ext = fitting[0]
        spelled = sufs[i]                      # keep the student's spelling
    elif content:
        ext = spelled = CONTENT_EXT.get(content, content)
    elif textual and (sufs or data.strip()):
        ext = spelled = "txt"
    elif not sufs:
        ext = spelled = "docx"                 # no suffix at all: assume Word
    else:
        ext, spelled = low[0], sufs[0]         # unknown and uncheckable: keep

    # Strip every trailing suffix that names a file type, then add the real one.
    strip = 0
    for i, s in enumerate(low):
        if s in KNOWN_TYPES and (i == 0 or s in INNER_OK):
            strip = i + 1
        else:
            break
    stem = ".".join(base.split(".")[:len(base.split(".")) - strip]) if strip else base
    clean = f"{stem}.{spelled}"
    source = ext in SOURCE_EXTS and textual
    return ext, clean, source, built


class Item:
    """One submitted file (or receipt) belonging to one student."""

    def __init__(self, user, ts, order, orig, data, receipt=False, path=None):
        self.user = user
        self.ts = ts
        self.order = order          # tuple: position in upload order
        self.orig = orig            # original file name as the student had it
        self.data = data
        self.receipt = receipt
        self.saved_as = None
        self.converted = ""
        self.built = False
        self.source = False
        self.relpath = None
        self.jar = False
        if receipt:
            self.ext = "txt"
            return
        path = path or orig
        self.ext, clean, self.source, self.built = classify(path, data)
        if self.ext in IWORK_EXTS:
            self.data = unwrap_iwork(data)
        self.jar = (self.ext in JAR_EXTS or content_type(data) == "jar")
        folder = os.path.dirname(safe_relpath(path))
        if self.built:                 # report removed files by their real name
            self.relpath = safe_relpath(path)
        else:
            self.relpath = f"{folder}/{clean}" if folder else safe_relpath(clean)
        if clean != os.path.basename(orig):
            self.renamed_from = orig


JAR_EXTS = {"jar", "war", "ear"}


def expand_jar(item):
    """Keep only the source code inside a JAR; everything else is discarded.

    A JAR holding no source is simply removed (it is built output). The
    JAR's own manifest folder (META-INF) and any JARs or ZIPs bundled inside
    it (libraries in a "fat" JAR) are never unpacked.
    """
    kept = []
    try:
        z = zipfile.ZipFile(io.BytesIO(item.data))
    except zipfile.BadZipFile:
        item.jar_note = "(removed: unreadable JAR)"
        return kept
    with z:
        for n, info in enumerate(z.infolist()):
            name = info.filename
            if (info.is_dir() or name.upper().startswith("META-INF/")
                    or name.startswith("__MACOSX/")):
                continue
            child = Item(item.user, item.ts, item.order + (n,),
                         os.path.basename(name), z.read(info), path=name)
            if child.source and not child.built:
                child.from_jar = item.orig
                kept.append(child)
    if kept:
        item.jar_note = f"(JAR unpacked: {len(kept)} source files kept, rest removed)"
    else:
        item.jar_note = "(removed: JAR with no source)"
    return kept


def expand_student_zip(item, depth=0):
    """Replace a student-submitted ZIP with the files inside it."""
    out = []
    try:
        z = zipfile.ZipFile(io.BytesIO(item.data))
    except zipfile.BadZipFile:
        print(f"  warning: {item.user}: {item.orig} is not a readable ZIP; kept as is")
        return [item]
    with z:
        # Pages, Numbers and Keynote documents saved as folders ("Essay.pages/")
        # are gathered back into one document each.
        packages = {}
        for info in z.infolist():
            parts = info.filename.split("/")
            for k, part in enumerate(parts[:-1]):
                if part.lower().rsplit(".", 1)[-1] in IWORK_EXTS and "." in part:
                    packages.setdefault("/".join(parts[:k + 1]), []).append(info)
                    break
        done_packages = set()
        for n, info in enumerate(z.infolist()):
            name = info.filename
            base = os.path.basename(name.rstrip("/"))
            if name.startswith("__MACOSX/") or "/__MACOSX/" in name:
                continue
            pkg = next((p for p in packages if name.startswith(p + "/")), None)
            if pkg:
                if pkg not in done_packages:
                    done_packages.add(pkg)
                    blob = io.BytesIO()
                    with zipfile.ZipFile(blob, "w", zipfile.ZIP_DEFLATED) as w:
                        for m in packages[pkg]:
                            if not m.is_dir():
                                w.writestr(m.filename[len(pkg) + 1:], z.read(m))
                    out.append(Item(item.user, item.ts, item.order + (n,),
                                    os.path.basename(pkg), blob.getvalue(), path=pkg))
                continue
            if (info.is_dir() or base.lower() in JUNK_NAMES
                    or base.startswith("._")):
                continue
            data = z.read(info)
            child = Item(item.user, item.ts, item.order + (n,), base, data,
                         path=name)              # keep src/ folders, packages
            if child.jar:
                out.append(child)
                out.extend(expand_jar(child))
            elif child.ext == "zip" and not child.built and depth < 5:
                out.extend(expand_student_zip(child, depth + 1))
            else:
                out.append(child)
    return out


def read_gradebook(zip_path):
    """Return (assignment title, list of Items) for one gradebook ZIP."""
    items, title = [], None
    receipts_order = {}           # entry name -> position listed in receipt
    with zipfile.ZipFile(zip_path) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        # First pass: receipts give the upload order of each attempt's files.
        for info in infos:
            m = ENTRY_RE.match(info.filename)
            if m and m.group("receipt"):
                text = z.read(info).decode("utf-8", "replace")
                for pos, fn in enumerate(re.findall(r"^\s*Filename:\s*(.+?)\s*$",
                                                    text, re.MULTILINE)):
                    receipts_order[fn] = pos
        for zpos, info in enumerate(infos):
            m = ENTRY_RE.match(info.filename)
            if not m:
                print(f"  warning: unrecognised entry skipped: {info.filename}")
                continue
            title = title or m.group("assignment")
            data = z.read(info)
            if m.group("receipt"):
                items.append(Item(m.group("user"), m.group("ts"), (zpos,),
                                  None, data, receipt=True))
                continue
            order = (receipts_order.get(info.filename, 10_000), zpos)
            item = Item(m.group("user"), m.group("ts"), order, m.group("orig"), data)
            item.entry = info.filename
            if item.jar:
                items.append(item)
                items.extend(expand_jar(item))
            elif item.ext == "zip" and not item.built:
                items.extend(expand_student_zip(item))
            else:
                items.append(item)
    return title or assignment_from_zipname(zip_path), items


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

def _first_font(candidates):
    for path, index in candidates:
        if os.path.exists(path):
            return path, index
    return None


MONO_FONTS = [
    ("/System/Library/Fonts/Menlo.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", None),
    ("/usr/share/fonts/dejavu/DejaVuSansMono.ttf", None),
    ("/System/Library/Fonts/Supplemental/Courier New.ttf", None),
    ("/Library/Fonts/Courier New.ttf", None),
    ("C:/Windows/Fonts/consola.ttf", None),
    ("C:/Windows/Fonts/cour.ttf", None),
]
SANS_FONTS = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf", None),
    ("/Library/Fonts/Arial.ttf", None),
    ("/usr/share/fonts/truetype/msttcorefonts/Arial.ttf", None),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", None),
    ("C:/Windows/Fonts/arial.ttf", None),
]
_fonts = None


def fonts():
    """Register a monospaced and a sans font once; fall back to the PDF core fonts."""
    global _fonts
    if _fonts:
        return _fonts
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    mono, sans = "Courier", "Helvetica"
    found = _first_font(MONO_FONTS)
    if found:
        try:
            kw = {"subfontIndex": found[1]} if found[1] is not None else {}
            pdfmetrics.registerFont(TTFont("CodeMono", found[0], **kw))
            mono = "CodeMono"
        except Exception:
            pass
    found = _first_font(SANS_FONTS)
    if found:
        try:
            pdfmetrics.registerFont(TTFont("HeadSans", found[0]))
            sans = "HeadSans"
        except Exception:
            pass
    _fonts = (mono, sans)
    return _fonts


def decode_text(data):
    if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return None
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def text_to_pdf(text, pdf_path, heading):
    """Render text as a monospaced, line-numbered PDF."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    mono, sans = fonts()
    size, leading = 9, 11.5
    width, height = letter
    margin = 0.75 * inch
    gutter = stringWidth("0000  ", mono, size)
    char_w = stringWidth("M", mono, size)
    cols = max(20, int((width - 2 * margin - gutter) // char_w))
    lines_per_page = int((height - 2 * margin - 30) // leading)

    if mono == "Courier":     # core font: Latin-1 only
        text = text.encode("latin-1", "replace").decode("latin-1")
    rows = []
    for n, line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n")
                             .split("\n"), 1):
        line = line.expandtabs(4)
        chunks = [line[i:i + cols] for i in range(0, len(line), cols)] or [""]
        rows.append((str(n), chunks[0]))
        rows.extend(("\u21aa" if mono != "Courier" else "+", c) for c in chunks[1:])
    while rows and rows[-1][1] == "" and len(rows) > 1:
        rows.pop()

    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.setTitle(heading)
    c.setAuthor("unpack-submissions.py")
    pages = max(1, -(-len(rows) // lines_per_page))
    for p in range(pages):
        c.setFillColorRGB(0, 0x20 / 255, 0x5C / 255)          # SMCM Blue
        c.setFont(sans, 10)
        c.drawString(margin, height - margin, heading)
        c.drawRightString(width - margin, margin - 18, f"Page {p + 1} of {pages}")
        c.setLineWidth(0.5)
        c.line(margin, height - margin - 6, width - margin, height - margin - 6)
        y = height - margin - 24
        for num, chunk in rows[p * lines_per_page:(p + 1) * lines_per_page]:
            c.setFillColorRGB(0x5A / 255, 0x50 / 255, 0x4A / 255)
            c.setFont(mono, size)
            c.drawRightString(margin + gutter - char_w * 2, y, num)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(margin + gutter, y, chunk)
            y -= leading
        c.showPage()
    c.save()


def image_to_jpeg(data, jpg_path):
    from PIL import Image
    try:
        import pillow_heif  # optional: iPhone photos
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    with Image.open(io.BytesIO(data)) as im:
        im.seek(0)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        im.save(jpg_path, "JPEG", quality=92)


# --------------------------------------------------------------------------
# Finding, installing and explaining the helper programs
# --------------------------------------------------------------------------

# ffmpeg downloaded by --install-ffmpeg lives here, next to this script, so
# nothing is installed system-wide and no administrator password is needed.
TOOLS_DIR = Path(__file__).resolve().parent / "Tools" / "FFmpeg" / "bin"
EXE = ".exe" if os.name == "nt" else ""
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
BTBN_PAGE = "https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest"
RIEDL = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/{channel}/{tool}.zip"
RIEDL_PAGE = "https://ffmpeg.martin-riedl.de"
LIBREOFFICE_PAGE = "https://www.libreoffice.org/download/download/"


def platform_info():
    """Return (system, is_arm, distro family, description) for this computer.
    system is Windows, Darwin (macOS) or Linux; the distro family is
    debian (Debian, Ubuntu, Mint ...), fedora, rhel (RHEL, Rocky, Alma,
    CentOS) or other."""
    import platform
    system = platform.system()
    machine = platform.machine().lower()
    distro, desc = "", system
    if system == "Windows":
        arch = (os.environ.get("PROCESSOR_ARCHITEW6432")
                or os.environ.get("PROCESSOR_ARCHITECTURE", ""))
        arm = "ARM" in arch.upper() or machine == "arm64"
        desc = f"Windows ({'ARM' if arm else 'x64'})"
    elif system == "Darwin":
        arm = machine == "arm64"
        if not arm:          # an Intel Python running on Apple Silicon
            try:
                arm = subprocess.run(["sysctl", "-n", "hw.optional.arm64"],
                                     capture_output=True, text=True).stdout.strip() == "1"
            except OSError:
                pass
        desc = f"macOS ({'Apple Silicon' if arm else 'Intel'})"
    else:
        arm = machine in ("aarch64", "arm64")
        info = {}
        try:
            for line in open("/etc/os-release", encoding="utf-8"):
                k, _, v = line.strip().partition("=")
                info[k] = v.strip('"')
        except OSError:
            pass
        ids = (info.get("ID", "") + " " + info.get("ID_LIKE", "")).lower().split()
        if info.get("ID", "").lower() == "fedora":
            distro = "fedora"
        elif any(i in ids for i in ("rhel", "centos", "rocky", "almalinux")):
            distro = "rhel"
        elif any(i in ids for i in ("debian", "ubuntu")):
            distro = "debian"
        else:
            distro = "other"
        desc = info.get("PRETTY_NAME", "Linux")
        if machine not in ("x86_64", "amd64", "aarch64", "arm64"):
            desc += f" ({machine})"
    return system, arm, distro, desc


def find_tool(name):
    local = TOOLS_DIR / (name + EXE)
    if local.exists():
        return str(local)
    path = shutil.which(name)
    if path:
        return path
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin",
              "C:/ffmpeg/bin", "C:/Program Files/ffmpeg/bin"):
        candidate = os.path.join(d, name + EXE)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def check_ffmpeg():
    """True if both ffmpeg and ffprobe can be found and actually run."""
    for tool in ("ffmpeg", "ffprobe"):
        path = find_tool(tool)
        if not path:
            return False
        try:
            if subprocess.run([path, "-version"], capture_output=True,
                              timeout=30).returncode != 0:
                return False
        except (OSError, subprocess.TimeoutExpired):
            return False
    return True


def _ssl_context():
    import ssl
    # A college or company proxy may need its own certificates: honour the
    # usual settings for pointing at them.
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        if os.environ.get(var) and os.path.isfile(os.environ[var]):
            return ssl.create_default_context(cafile=os.environ[var])
    try:
        import certifi   # python.org's Python on macOS has no certificates
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _download(url, dest, label):
    """Download url to dest with a progress line; return the final URL."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "unpack-submissions"})
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=60) as r, \
            open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, shown = 0, -1
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                pct = got * 100 // total
                if pct // 5 != shown:
                    shown = pct // 5
                    print(f"\r  {label}: {pct:3d}% of {total / 1e6:.0f} MB",
                          end="", flush=True)
        print(f"\r  {label}: done ({got / 1e6:.0f} MB)          ")
        return r.geturl()


def _fetch_text(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "unpack-submissions"})
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def install_ffmpeg():
    """Download ffmpeg and ffprobe into TOOLS_DIR. Returns True on success.

    Windows and Linux: the BtbN builds on GitHub (GPL, static, x64 or ARM64).
    macOS: the signed builds from ffmpeg.martin-riedl.de (Apple Silicon or
    Intel). Every download is checked against the published SHA-256 sum.
    """
    import tarfile
    system, arm, distro, desc = platform_info()
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Installing ffmpeg for {desc} into {TOOLS_DIR}")
    tmp = TOOLS_DIR.parent / "download.tmp"
    try:
        if system in ("Windows", "Linux"):
            import platform
            if system == "Linux" and platform.machine().lower() not in (
                    "x86_64", "amd64", "aarch64", "arm64"):
                print("  No ready-made ffmpeg for this processor.")
                return False
            name = (f"ffmpeg-master-latest-{'winarm64' if arm else 'win64'}-gpl.zip"
                    if system == "Windows" else
                    f"ffmpeg-master-latest-{'linuxarm64' if arm else 'linux64'}-gpl.tar.xz")
            sums = _fetch_text(BTBN + "checksums.sha256")
            expected = next((line.split()[0] for line in sums.splitlines()
                             if line.strip().endswith(name)), None)
            if not expected:
                print(f"  {name} is not listed in the published checksums.")
                return False
            _download(BTBN + name, tmp, name)
            if _sha256(tmp) != expected:
                print("  The download is damaged (checksum mismatch); not installed.")
                return False
            wanted = {"ffmpeg" + EXE, "ffprobe" + EXE}
            if system == "Windows":
                with zipfile.ZipFile(tmp) as z:
                    for n in z.namelist():
                        if n.endswith("/bin/" + os.path.basename(n)) and \
                                os.path.basename(n) in wanted:
                            (TOOLS_DIR / os.path.basename(n)).write_bytes(z.read(n))
            else:
                with tarfile.open(tmp, "r:xz") as t:
                    for m in t.getmembers():
                        base = os.path.basename(m.name)
                        if m.isfile() and base in wanted and "/bin/" in m.name:
                            with t.extractfile(m) as src, \
                                    open(TOOLS_DIR / base, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            os.chmod(TOOLS_DIR / base, 0o755)
        elif system == "Darwin":
            for tool in ("ffmpeg", "ffprobe"):
                for channel in ("release", "snapshot"):   # Intel release builds
                    url = RIEDL.format(arch="arm64" if arm else "amd64",  # end 2027
                                       channel=channel, tool=tool)
                    try:
                        final = _download(url, tmp, f"{tool}.zip")
                        break
                    except Exception:
                        if channel == "snapshot":
                            raise
                try:
                    expected = _fetch_text(final + ".sha256").split()[0].lower()
                except Exception:
                    expected = None
                    print("  note: no checksum published; relying on HTTPS and "
                          "Apple's code signature")
                if expected and _sha256(tmp) != expected:
                    print("  The download is damaged (checksum mismatch); not installed.")
                    return False
                with zipfile.ZipFile(tmp) as z:
                    member = next(n for n in z.namelist()
                                  if os.path.basename(n) == tool)
                    (TOOLS_DIR / tool).write_bytes(z.read(member))
                os.chmod(TOOLS_DIR / tool, 0o755)
        else:
            print(f"  Automatic installation is not available for {system}.")
            return False
    except Exception as e:
        print(f"\n  Download failed: {e}")
        return False
    finally:
        if tmp.exists():
            tmp.unlink()
    if check_ffmpeg():
        print("  ffmpeg is installed and working.")
        return True
    print("  ffmpeg was downloaded but will not run on this computer.")
    return False


def ffmpeg_instructions():
    """Step-by-step instructions for installing ffmpeg by hand."""
    system, arm, distro, desc = platform_info()
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    folder = str(TOOLS_DIR)
    lines = [f"How to install ffmpeg on {desc}", ""]
    if system == "Windows":
        zipname = f"ffmpeg-master-latest-{'winarm64' if arm else 'win64'}-gpl.zip"
        lines += [
            f"1. Open {BTBN_PAGE} in your web browser.",
            f'2. Under "Assets", click {zipname} to download it.',
            "3. Open your Downloads folder, right-click the file, choose",
            '   "Extract All..." and click "Extract".',
            '4. Open the extracted folder, then the "bin" folder inside it.',
            "5. Select ffmpeg.exe and ffprobe.exe and copy them (Ctrl+C).",
            "6. Open this folder in File Explorer (paste it into the address bar):",
            f"   {folder}",
            "7. Paste the two files into it (Ctrl+V).",
            "8. Run unpack-submissions.cmd again.",
        ]
        if shutil.which("winget"):
            lines += ["", "Or, to install ffmpeg for every program on this computer,",
                      "open Terminal and type:  winget install -e --id Gyan.FFmpeg",
                      "then close Terminal and open a new one."]
    elif system == "Darwin":
        arch = "arm64 (Apple Silicon)" if arm else "amd64 (Intel)"
        lines += [
            f"1. Open {RIEDL_PAGE} in Safari.",
            f'2. Find the macOS {arch} "Release" row and click ffmpeg.zip,',
            "   then ffprobe.zip, to download both.",
            "3. Open your Downloads folder and double-click each zip file to",
            "   unzip it. You now have two files called ffmpeg and ffprobe.",
            '4. In the Finder choose Go > "Go to Folder..." (Shift-Command-G),',
            "   paste this folder and press Return:",
            f"   {folder}",
            "5. Drag ffmpeg and ffprobe into that folder.",
            "6. Run ./unpack-submissions.sh again. (It clears the download",
            "   quarantine macOS puts on the two files, so they can run.)",
        ]
    elif system == "Linux":
        if distro == "debian":
            lines += ["1. Open a terminal.",
                      "2. Type:  sudo apt update",
                      "   and enter your password when asked.",
                      "3. Type:  sudo apt install ffmpeg",
                      "   and press Y when asked to continue.",
                      "4. Run ./unpack-submissions.sh again."]
        elif distro == "fedora":
            lines += ["Fedora's own ffmpeg (ffmpeg-free) can't make H.264 video, so",
                      "install the full version from RPM Fusion:",
                      "1. Open a terminal.",
                      "2. Type (all on one line):",
                      "   sudo dnf install https://mirrors.rpmfusion.org/free/fedora/"
                      "rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm",
                      "   and enter your password when asked.",
                      "3. Type:  sudo dnf install ffmpeg --allowerasing",
                      "   and press y when asked to continue.",
                      "4. Run ./unpack-submissions.sh again."]
        elif distro == "rhel":
            lines += ["1. Open a terminal.",
                      "2. Turn on the extra package repositories. On Rocky or Alma",
                      "   Linux type these two lines:",
                      "   sudo dnf config-manager --set-enabled crb",
                      "   sudo dnf install epel-release",
                      "   (On Red Hat Enterprise Linux itself, follow",
                      "   https://docs.fedoraproject.org/en-US/epel/ instead.)",
                      "3. Type (all on one line):",
                      "   sudo dnf install https://mirrors.rpmfusion.org/free/el/"
                      "rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm",
                      "4. Type:  sudo dnf install ffmpeg",
                      "5. Run ./unpack-submissions.sh again."]
        tarname = f"ffmpeg-master-latest-{'linuxarm64' if arm else 'linux64'}-gpl.tar.xz"
        lines += ["" if distro != "other" else "",
                  ("Or, without an administrator password:" if distro != "other"
                   else "Without an administrator password:"),
                  f"1. Download {BTBN}{tarname}",
                  "2. In a terminal, go to the folder you saved it in and type:",
                  f"   tar -xJf {tarname}",
                  f"3. Copy the two programs into place:",
                  f"   mkdir -p '{folder}'",
                  f"   cp {tarname[:-7]}/bin/ffmpeg {tarname[:-7]}/bin/ffprobe '{folder}/'",
                  "4. Run ./unpack-submissions.sh again."]
    else:
        lines += [f"Download ffmpeg from https://ffmpeg.org/download.html and put",
                  f"ffmpeg and ffprobe in {folder}"]
    return "\n".join(lines)


LO_DIR = Path(__file__).resolve().parent / "Tools" / "LibreOffice"
LO_STABLE = "https://download.documentfoundation.org/libreoffice/stable/"
LO_APPIMAGE = "https://appimages.libreitalia.org/LibreOffice-latest.basic-x86_64.AppImage"


def libreoffice_instructions():
    """Step-by-step instructions for installing LibreOffice by hand."""
    system, arm, distro, desc = platform_info()
    lines = [f"How to install LibreOffice on {desc}", ""]
    if system == "Windows":
        lines += [
            f"1. Open {LIBREOFFICE_PAGE} in your web browser.",
            f'2. Check that the box says "Windows {"Aarch64" if arm else "x86_64"}"'
            " and click the yellow Download button.",
            "3. Open your Downloads folder and double-click the .msi file.",
            '4. Click Next, choose "Typical", click Next, then Install. Click Yes',
            "   if Windows asks whether to allow changes.",
            "5. Click Finish, then run unpack-submissions.cmd again.",
        ]
        if shutil.which("winget"):
            lines += ["", "Or open Terminal and type:",
                      "   winget install -e --id TheDocumentFoundation.LibreOffice"]
    elif system == "Darwin":
        lines += [
            f"1. Open {LIBREOFFICE_PAGE} in Safari.",
            f'2. Check that the box says "macOS ({"Apple Silicon" if arm else "Intel"})"'
            " and click the yellow Download button.",
            "3. Open your Downloads folder and double-click the .dmg file.",
            "4. In the window that opens, drag the LibreOffice icon onto the",
            "   Applications folder.",
            "5. Open LibreOffice once from Applications (click Open if macOS",
            "   asks), then quit it.",
            "6. Run ./unpack-submissions.sh again.",
        ]
    else:
        if distro == "debian":
            lines += ["1. Open a terminal.",
                      "2. Type:  sudo apt update",
                      "   and enter your password when asked.",
                      "3. Type:  sudo apt install libreoffice",
                      "   and press Y when asked to continue.",
                      "4. Run ./unpack-submissions.sh again."]
        elif distro in ("fedora", "rhel"):
            lines += ["1. Open a terminal.",
                      "2. Type:  sudo dnf install libreoffice",
                      "   enter your password and press y when asked.",
                      "3. Run ./unpack-submissions.sh again."]
        if not arm:
            lines += ["" if distro != "other" else "",
                      ("Or, without an administrator password:" if distro != "other"
                       else "Without an administrator password:"),
                      f"1. Download {LO_APPIMAGE}",
                      "2. Move the downloaded file into this folder:",
                      f"   {LO_DIR}",
                      "3. Run ./unpack-submissions.sh again."]
        elif distro == "other":
            lines += ["Install LibreOffice with your system's package manager."]
    return "\n".join(lines)


def _latest_libreoffice():
    """The newest version in LibreOffice's stable download folder, e.g. 26.8.2."""
    listing = _fetch_text(LO_STABLE)
    versions = set(re.findall(r'href="(\d+(?:\.\d+){2,3})/"', listing))
    if not versions:
        raise RuntimeError("could not find the latest LibreOffice version")
    return max(versions, key=lambda v: tuple(int(x) for x in v.split(".")))


def _checked_download(url, dest, label):
    """Download and compare with the .sha256 file published beside it."""
    _download(url, dest, label)
    try:
        expected = _fetch_text(url + ".sha256").split()[0].lower()
    except Exception:
        print("  note: no checksum published; relying on HTTPS")
        return True
    if _sha256(dest) != expected:
        print("  The download is damaged (checksum mismatch); not installed.")
        return False
    return True


def install_libreoffice():
    """Download LibreOffice into Tools/LibreOffice. Nothing is installed on
    the computer itself: Windows gets the official MSI unpacked (not
    installed), macOS the app copied out of the official disk image, Linux
    the AppImage from libreoffice.org's download page, unpacked."""
    system, arm, distro, desc = platform_info()
    LO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Installing LibreOffice for {desc} into {LO_DIR}")
    tmp = LO_DIR.parent / ("libreoffice.tmp" + (".msi" if system == "Windows" else ""))
    try:
        if system == "Windows":
            v = _latest_libreoffice()
            folder, label = ("aarch64", "aarch64") if arm else ("x86_64", "x86-64")
            url = f"{LO_STABLE}{v}/win/{folder}/LibreOffice_{v}_Win_{label}.msi"
            if not _checked_download(url, tmp, f"LibreOffice {v}"):
                return False
            print("  Unpacking (this takes a minute or two) ...")
            r = subprocess.run(["msiexec", "/a", str(tmp), "/qn",
                                f"TARGETDIR={LO_DIR}"], timeout=1800)
            if r.returncode != 0:
                print(f"  Unpacking failed (msiexec exit code {r.returncode}).")
                return False
        elif system == "Darwin":
            v = _latest_libreoffice()
            folder, label = ("aarch64", "aarch64") if arm else ("x86_64", "x86-64")
            url = f"{LO_STABLE}{v}/mac/{folder}/LibreOffice_{v}_MacOS_{label}.dmg"
            if not _checked_download(url, tmp, f"LibreOffice {v}"):
                return False
            mount = Path(tempfile.mkdtemp(prefix="libreoffice-"))
            subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly",
                            "-mountpoint", str(mount), str(tmp)],
                           input=b"Y\n", capture_output=True, check=True)
            try:
                app = next(mount.glob("*.app"))
                target = LO_DIR / "LibreOffice.app"
                if target.exists():
                    shutil.rmtree(target)
                subprocess.run(["ditto", str(app), str(target)], check=True)
            finally:
                subprocess.run(["hdiutil", "detach", str(mount), "-quiet"])
        elif system == "Linux":
            import platform
            if platform.machine().lower() not in ("x86_64", "amd64"):
                print("  LibreOffice is only published as a portable AppImage for "
                      "x86-64 computers.")
                return False
            _download(LO_APPIMAGE, tmp, "LibreOffice AppImage")
            os.chmod(tmp, 0o755)
            print("  Unpacking ...")
            old = LO_DIR / "squashfs-root"
            if old.exists():
                shutil.rmtree(old)
            r = subprocess.run([str(tmp.resolve()), "--appimage-extract"],
                               cwd=LO_DIR, capture_output=True, timeout=1800)
            if r.returncode != 0:
                print("  Unpacking the AppImage failed.")
                return False
        else:
            print(f"  Automatic installation is not available for {system}.")
            return False
    except Exception as e:
        print(f"\n  Download failed: {e}")
        return False
    finally:
        if tmp.exists():
            tmp.unlink()
    if find_soffice():
        print("  LibreOffice is installed.")
        return True
    print("  LibreOffice was downloaded but could not be found afterwards.")
    return False


# --------------------------------------------------------------------------
# Downloading converters only when a submission needs them
# --------------------------------------------------------------------------

DOWNLOAD_MODE = os.environ.get("UNPACK_INSTALL", "ask").lower()   # ask, yes, no
_ensured = {}


def ask(question):
    if DOWNLOAD_MODE == "yes":
        return True
    if DOWNLOAD_MODE == "no" or not sys.stdin.isatty():
        return False
    try:
        reply = input(f"{question} [Y/n] ")
    except EOFError:
        return False
    return not reply.strip().lower().startswith("n")


def ensure_converter(name, count, what, size, present, install, instructions):
    """Make sure a converter is available, asking to download it the first
    time a submission needs it. Asked at most once per run."""
    if name in _ensured:
        return _ensured[name]
    ok = present()
    if not ok:
        print(f"\n{count} {what} {'needs' if count == 1 else 'need'} {name} to be "
              f"converted, and {name} is not installed.")
        if ask(f"Download {name} now into {Path(__file__).resolve().parent / 'Tools'}"
               f" (about {size}; no administrator password needed)?"):
            ok = install()
            if not ok:
                print(f"\nThe download did not work. You can install {name} yourself:\n")
        else:
            print(f"\nTo install {name} yourself:\n")
        if not ok:
            print("    " + instructions().replace("\n", "\n    ") + "\n")
            print(f"Carrying on without {name}: those files keep only their originals.\n")
    _ensured[name] = ok
    return ok


def ensure_ffmpeg(count):
    return ensure_converter("ffmpeg", count, "audio or video file" + ("s" if count != 1 else ""),
                            "150 MB", check_ffmpeg, install_ffmpeg, ffmpeg_instructions)


def ensure_libreoffice(count):
    return ensure_converter("LibreOffice", count,
                            "Office document" + ("s" if count != 1 else ""),
                            "350 MB", lambda: bool(find_soffice()),
                            install_libreoffice, libreoffice_instructions)


def remove_converters():
    """Delete the converters this script downloaded (the Tools folder).
    Copies installed on the computer in the usual way are not touched."""
    tools = Path(__file__).resolve().parent / "Tools"
    if not tools.exists():
        print("Nothing to remove: no converters were downloaded.")
        return

    def make_writable(func, path, _):
        os.chmod(path, 0o700)
        func(path)
    size = sum(f.stat().st_size for f in tools.rglob("*") if f.is_file())
    shutil.rmtree(tools, onerror=make_writable)
    print(f"Removed {tools} ({size / 1e6:.0f} MB). They will be downloaded "
          "again if a later batch of submissions needs them.")


def find_soffice():
    """LibreOffice downloaded into Tools/LibreOffice first, then any installed copy."""
    if LO_DIR.exists():
        mac = LO_DIR / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
        if mac.exists():
            return str(mac)
        for f in sorted(LO_DIR.rglob("soffice.exe" if os.name == "nt" else "soffice")):
            if f.parent.name == "program" and f.is_file():
                return str(f)
        for f in sorted(LO_DIR.glob("*.AppImage")):      # put there by hand
            return str(f)
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    for path in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
                 "C:/Program Files/LibreOffice/program/soffice.exe",
                 "C:/Program Files (x86)/LibreOffice/program/soffice.exe"):
        if os.path.exists(path):
            return path
    return None


def has_video(path, ext):
    """True if the file holds real video (not just audio with cover art)."""
    ffprobe = find_tool("ffprobe")
    if not ffprobe:
        return ext not in AUDIO_ONLY_EXTS
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v",
                            "-show_entries", "stream=codec_type:stream_disposition=attached_pic",
                            "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return ext not in AUDIO_ONLY_EXTS
    # one line per video stream: "video,0" (real video) or "video,1" (cover art)
    return any(line.split(",")[-1].strip() == "0"
               for line in r.stdout.splitlines() if line.startswith("video"))


_encoders = {}


def video_encoder(ffmpeg):
    """libx264 where available; otherwise another H.264 encoder (Fedora's own
    ffmpeg-free has only OpenH264), and plain MPEG-4 as a last resort."""
    if ffmpeg not in _encoders:
        try:
            out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                                 capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        if " libx264 " in out:
            choice = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]
        elif " libopenh264 " in out:
            choice = ["-c:v", "libopenh264", "-b:v", "1500k"]
        elif " h264_videotoolbox " in out:
            choice = ["-c:v", "h264_videotoolbox", "-b:v", "1500k"]
        else:
            choice = ["-c:v", "mpeg4", "-q:v", "5"]
        _encoders[ffmpeg] = choice
    return _encoders[ffmpeg]


def convert_media(it, src, target):
    """Audio -> MP3 (VBR about 130 kbit/s); video -> MP4 (H.264, long side
    at most 1280 px, AAC audio), written to the name the Namer chose.
    MP3 and MP4 originals are already in a target format and are left alone."""
    ext = it.ext
    if ext == "mp3":
        it.converted = "(already MP3)"
        return
    if ext == "mp4":
        it.converted = "(already MP4)"
        return
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        return                      # ensure_ffmpeg has already explained
    video = it.video
    if video:
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src),
               "-map", "0:v:0", "-map", "0:a:0?",
               "-vf", "scale=w='min(1280,iw)':h='min(1280,ih)'"
                      ":force_original_aspect_ratio=decrease,"
                      "scale=trunc(iw/2)*2:trunc(ih/2)*2",
               *video_encoder(ffmpeg), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "-movflags", "+faststart", str(target)]
    else:
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-vn",
               "-c:a", "libmp3lame", "-q:a", "5", str(target)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        ok = r.returncode == 0 and target.exists() and target.stat().st_size > 0
    except (subprocess.TimeoutExpired, OSError):
        ok = False
    if ok:
        it.converted = target.name
    else:
        target.unlink(missing_ok=True)
        print(f"  warning: could not convert {it.saved_as} to "
              f"{'MP4' if video else 'MP3'}")


def office_to_pdf(jobs):
    """jobs: list of (source path, target pdf path). One LibreOffice run for all."""
    if not jobs:
        return set()
    soffice = find_soffice()
    if not soffice and ensure_libreoffice(len(jobs)):
        soffice = find_soffice()
    if not soffice:
        return None                 # ensure_libreoffice has already explained
    done = set()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        staged = []
        for i, (src, dst) in enumerate(jobs):
            s = tmp / "in" / f"f{i:04d}{src.suffix}"
            s.parent.mkdir(exist_ok=True)
            shutil.copyfile(src, s)
            staged.append((s, dst))
        cmd = [soffice, f"-env:UserInstallation={(tmp / 'profile').resolve().as_uri()}",
               "--headless", "--convert-to", "pdf", "--outdir", str(tmp / "out")]
        cmd += [str(s) for s, _ in staged]
        if soffice.endswith(".AppImage"):
            if not os.access(soffice, os.X_OK):
                os.chmod(soffice, 0o755)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60 + 30 * len(jobs),
                       env=dict(os.environ, APPIMAGE_EXTRACT_AND_RUN="1"))
        for s, dst in staged:
            produced = tmp / "out" / (s.stem + ".pdf")
            if produced.exists():
                shutil.move(str(produced), dst)
                done.add(dst)
    return done


# --------------------------------------------------------------------------
# Receipts
# --------------------------------------------------------------------------

def receipt_extras(text):
    """Return typed submission text and comments from a receipt, if any."""
    def section(name, nxt):
        m = re.search(rf"^{name}:\s*\n(.*?)(?=^{nxt}:|\Z)", text, re.S | re.M)
        return m.group(1).strip() if m else ""
    sub = section("Submission Field", "Comments")
    com = section("Comments", "Files")
    if sub.startswith("There is no student submission text"):
        sub = ""
    if com.startswith("There are no student comments"):
        com = ""
    strip = lambda s: html.unescape(re.sub(r"<br\s*/?>|</p>", "\n",
                                           re.sub(r"<(?!br|/p)[^>]+>", "", s)))
    parts = []
    if sub:
        parts.append("Submission text:\n\n" + strip(sub))
    if com:
        parts.append("Comments:\n\n" + strip(com))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# Main work
# --------------------------------------------------------------------------

def iwork_fallback(it, namer):
    """Use the preview inside an iWork file when LibreOffice can't read it."""
    kind, preview = iwork_preview(it.data)
    if kind == "pdf":
        it.target.write_bytes(preview)
        it.converted = f"{it.target.name} (preview stored in the file)"
        return True
    if kind in ("jpg", "png"):
        jpg = namer.reserve(f"{it.stem}-preview", it.ext, "jpg")
        try:
            image_to_jpeg(preview, jpg)
        except Exception:
            return False
        it.converted = f"{jpg.name} (first page only)"
        return True
    return False


class Namer:
    """Chooses names for converted copies in one assignment folder."""

    def __init__(self, folder):
        self.folder = folder
        self.taken = {f.name.lower() for f in folder.iterdir()}

    def plan(self, requests):
        """requests: (item, output extension). Sets item.target."""
        wanted = defaultdict(list)
        for it, out in requests:
            wanted[(it.stem, out)].append(it)
        for (stem, out), items in wanted.items():
            plain = f"{stem}.{out}"
            if len(items) == 1 and plain.lower() not in self.taken:
                self._take(items[0], plain)
            else:
                for it in items:
                    self._take(it, self._free(f"{stem}-{it.ext}", out))

    def reserve(self, stem, ext, out):
        """A name for a copy decided on later (an iWork preview picture)."""
        plain = f"{stem}.{out}"
        if plain.lower() not in self.taken:
            self.taken.add(plain.lower())
            return self.folder / plain
        name = self._free(f"{stem}-{ext}", out)
        self.taken.add(name.lower())
        return self.folder / name

    def _free(self, base, out):
        name, n = f"{base}.{out}", 2
        while name.lower() in self.taken:
            name, n = f"{base}-{n}.{out}", n + 1
        return name

    def _take(self, it, name):
        self.taken.add(name.lower())
        it.target = self.folder / name


def is_plain_text(data):
    """True if the file is nothing but text (ASCII or Unicode)."""
    sample = data[:1 << 16]
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            data.decode("utf-16")
            return True
        except UnicodeDecodeError:
            return False
    if not data.strip() or b"\x00" in sample:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass
    # Older Windows text (cp1252): allow it if there are almost no control codes.
    controls = sum(1 for b in sample if b < 32 and b not in (9, 10, 12, 13, 26, 27))
    return controls <= len(sample) // 200


def numbered(base, count, i):
    return base if count == 1 else f"{base}-{i:02d}"


def place_source(files, folder):
    """Choose where each source file goes: <username>/<original name>.

    If two attempts by the same student contain a file with the same name,
    each attempt gets its own subfolder (Attempt1, Attempt2, ...) so that
    nothing is overwritten. Names are compared case-insensitively, as the
    Mac and Windows file systems do.
    """
    by_user = defaultdict(list)
    for it in files:
        if it.source:
            by_user[it.user].append(it)
    for user, items in by_user.items():
        attempts = sorted({i.ts for i in items})
        names_per_attempt = defaultdict(set)
        clash = False
        for it in items:
            key = it.relpath.lower()
            if any(key in names_per_attempt[t] for t in attempts if t != it.ts):
                clash = True
            names_per_attempt[it.ts].add(key)
        used = set()
        for it in sorted(items, key=lambda i: (i.ts, i.order)):
            prefix = user
            if clash:
                prefix += f"/Attempt{attempts.index(it.ts) + 1}"
            path = f"{prefix}/{it.relpath}"
            stem, dot, ext = path.rpartition(".")
            if not dot or "/" in ext:
                stem, ext, dot = path, "", ""
            n = 2
            while path.lower() in used:       # same name twice in one attempt
                path = f"{stem} ({n}){dot}{ext}"
                n += 1
            used.add(path.lower())
            it.saved_as = path


def write_assignment(title, items, out_root, force):
    folder = out_root / camel_case(title)
    if folder.exists():
        if not force:
            sys.exit(f"error: {folder} already exists (use --force to replace it)")
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    print(f"{title} -> {folder}")

    built = [i for i in items if i.built]
    files = [i for i in items if not i.receipt and not i.built]
    receipts = [i for i in items if i.receipt]
    for it in built:
        it.saved_as = getattr(it, "jar_note", None) or "(removed: built file)"

    # Group each student's files by type, in submission order.
    groups = defaultdict(list)
    for it in sorted(files, key=lambda i: (i.user, i.ts, i.order)):
        groups[(it.user, it.ext)].append(it)

    place_source(files, folder)

    # 1. Write every renamed original and decide what each one needs.
    office_jobs, media_jobs, image_jobs = [], [], []
    for (user, ext), group in sorted(groups.items()):
        for n, it in enumerate(group):
            stem = numbered(user, len(group), n)
            it.stem = stem
            if it.source:
                dest = folder / it.saved_as          # chosen by place_source
                dest.parent.mkdir(parents=True, exist_ok=True)
            else:
                dest = folder / f"{stem}.{ext}"
                it.saved_as = dest.name
            dest.write_bytes(it.data)
            it.dest = dest
            if it.source:
                it.converted = "(source code, not converted)"
            elif ext in TARGET_EXTS:
                it.converted = "(already PDF/JPEG)"
            elif content_type(it.data) is None and is_plain_text(it.data):
                it.converted = "(plain text, not converted)"
            elif ext in OFFICE_EXTS:
                office_jobs.append(it)
            elif ext in IMAGE_EXTS:
                image_jobs.append(it)
            elif ext in MEDIA_EXTS:
                media_jobs.append(it)
            else:
                print(f"  warning: no converter for {dest.name} "
                      f"(original {it.orig}); original kept")

    # 2. Name the converted copies. A copy takes the student's name alone
    # (jdoe.pdf) unless that would clash with an original or with another
    # copy; then each clashing copy carries its source suffix (jdoe-docx.pdf).
    namer = Namer(folder)
    needs_ffmpeg = [it for it in media_jobs if it.ext not in ("mp3", "mp4")]
    have_ffmpeg = ensure_ffmpeg(len(needs_ffmpeg)) if needs_ffmpeg else True
    plans = [(it, "pdf") for it in office_jobs] + [(it, "jpg") for it in image_jobs]
    for it in media_jobs:
        if it.ext in ("mp3", "mp4"):
            it.converted = f"(already {it.ext.upper()})"
        elif have_ffmpeg:
            it.video = has_video(it.dest, it.ext)
            plans.append((it, "mp4" if it.video else "mp3"))
    namer.plan(plans)

    # 3. Convert.
    for it in image_jobs:
        try:
            image_to_jpeg(it.data, it.target)
            it.converted = it.target.name
        except Exception as e:
            print(f"  warning: could not convert {it.saved_as}: {e}")
    for it in media_jobs:
        if getattr(it, "target", None) is not None:
            convert_media(it, it.dest, it.target)

    done = office_to_pdf([(it.dest, it.target) for it in office_jobs])
    for it in office_jobs:
        if done and it.target in done:
            it.converted = it.target.name
        elif it.ext in IWORK_EXTS and iwork_fallback(it, namer):
            print(f"  note: {it.saved_as}: LibreOffice could not convert it; "
                  f"used the preview stored in the file ({it.converted})")
        elif done is not None:
            print(f"  warning: LibreOffice could not convert {it.saved_as}")

    # Receipts: one per attempt.
    if receipts:
        rdir = folder / "Receipts"
        rdir.mkdir()
        by_user = defaultdict(list)
        for r in sorted(receipts, key=lambda i: (i.user, i.ts)):
            by_user[r.user].append(r)
        for user, rs in by_user.items():
            for n, r in enumerate(rs):
                stem = numbered(user, len(rs), n)
                (rdir / f"{stem}.txt").write_bytes(r.data)
                r.saved_as = f"Receipts/{stem}.txt"
                extra = receipt_extras(r.data.decode("utf-8", "replace"))
                if extra:
                    target = folder / f"{numbered(user + '-text', len(rs), n)}.pdf"
                    text_to_pdf(extra, target, f"{user}: text typed into Blackboard "
                                               f"({r.ts})")
                    r.converted = target.name

    with open(folder / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["username", "attempt", "original_filename", "saved_as",
                    "converted_to"])
        for it in sorted(items, key=lambda i: (i.user, i.receipt, i.ts, i.order)):
            original = it.orig or "(Blackboard receipt)"
            if getattr(it, "from_jar", None):
                original = f"{original} (in JAR {it.from_jar}: {it.relpath})"
            elif it.relpath and "/" in it.relpath:   # came from a student ZIP
                original = f"{original} (in ZIP: {it.relpath})"
            w.writerow([it.user, it.ts, original, it.saved_as or "", it.converted])

    students = len({i.user for i in items})
    print(f"  {students} students, {len(files)} files, {len(receipts)} receipts"
          + (f", {len(built)} built files removed" if built else ""))


def main():
    global DOWNLOAD_MODE
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("zips", nargs="*", type=Path, help="gradebook ZIP files")
    ap.add_argument("-o", "--output", type=Path, default=Path.cwd(),
                    help="where to create the assignment folders (default: here)")
    ap.add_argument("--force", action="store_true",
                    help="replace assignment folders that already exist")
    tools = ap.add_argument_group(
        "converters (ffmpeg and LibreOffice are downloaded into the Tools "
        "folder only when a submission needs them, after asking)")
    tools.add_argument("--download", choices=("ask", "yes", "no"),
                       default=DOWNLOAD_MODE if DOWNLOAD_MODE in ("ask", "yes", "no")
                       else "ask",
                       help="download missing converters: ask first (default), "
                            "always, or never")
    tools.add_argument("--remove-converters", action="store_true",
                       help="delete the downloaded converters when you have "
                            "finished unpacking")
    tools.add_argument("--install-ffmpeg", action="store_true",
                       help="download ffmpeg now")
    tools.add_argument("--install-libreoffice", action="store_true",
                       help="download LibreOffice now")
    tools.add_argument("--instructions", action="store_true",
                       help="show how to install both converters by hand")
    args = ap.parse_args()

    DOWNLOAD_MODE = args.download
    if args.remove_converters:
        remove_converters()
        if not args.zips:
            return
    if args.install_ffmpeg or args.install_libreoffice:
        ok = True
        if args.install_ffmpeg:
            ok = (check_ffmpeg() or install_ffmpeg()) and ok
        if args.install_libreoffice:
            ok = (bool(find_soffice()) or install_libreoffice()) and ok
        sys.exit(0 if ok else 1)
    if args.instructions:
        print(ffmpeg_instructions() + "\n\n" + libreoffice_instructions())
        return
    if not args.zips:
        ap.error("give at least one gradebook ZIP file")

    # Windows doesn't expand wildcards (gradebook_*.zip) for us.
    import glob
    zips = []
    for z in args.zips:
        matches = sorted(glob.glob(str(z))) if any(c in str(z) for c in "*?[") else []
        zips.extend(Path(m) for m in matches) if matches else zips.append(z)
    for z in zips:
        if not z.is_file():
            ap.error(f"no such file: {z}")
    args.zips = zips

    by_assignment = {}
    for zp in args.zips:
        title, items = read_gradebook(zp)
        seen = by_assignment.setdefault(title, ({}, []))
        for it in items:
            key = (it.user, it.ts, it.orig, it.order, it.receipt)
            if key not in seen[0]:        # same gradebook downloaded twice
                seen[0][key] = True
                seen[1].append(it)

    args.output.mkdir(parents=True, exist_ok=True)
    for title, (_, items) in by_assignment.items():
        write_assignment(title, items, args.output, args.force)


if __name__ == "__main__":
    main()
