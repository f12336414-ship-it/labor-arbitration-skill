# Parser boundary contract v1.0

## Scope

The parser reads one immutable object from a validated local case workspace and emits a content-bound extraction record. It never edits the workspace, follows a link, executes a macro or formula, opens an external relationship, fetches a URL, or treats document text as instructions.

The boundary is a separate Python process started with isolated mode and site-package loading disabled. Input and output use bounded JSON, execution has a wall-clock timeout, source and output byte ceilings are enforced, and POSIX workers additionally apply CPU, address-space, file-size, and open-file limits. This reduces accidental parser impact but is **not an operating-system security sandbox**. Windows Job Objects, containers, seccomp/AppContainer, antivirus scanning, and independently sandboxed third-party PDF/OCR engines remain P6-03 work.

## Supported adapters

| Adapter | Result | Anchors | Mandatory refusal |
| --- | --- | --- | --- |
| UTF-8 text/Markdown | exact decoded lines | `TEXT_LINE` | invalid UTF-8, NUL bytes, limit breach |
| CSV | cells in row order | `CSV_CELL` | malformed/oversized rows or cells |
| DOCX | paragraph text from `word/document.xml` | `DOCX_PARAGRAPH` | macros, external relationships, unsafe ZIP/XML |
| XLSX | sheet/cell text; formula source is never evaluated | `XLSX_CELL` | macros, external relationships, unsafe ZIP/XML |
| EML | selected headers and `text/plain` lines | `EMAIL_HEADER`, `EMAIL_TEXT_LINE` | excessive parts or decoded bytes |
| ZIP | entry-name inspection only; no extraction or recursion | `ARCHIVE_ENTRY` | traversal, links, encryption, duplicates, bomb limits |

PDF and image bytes are positively identified and refused with a stable unsupported-adapter code. They are not silently treated as text. PDF parsing and OCR require independently reviewed engines and stronger P6-03 isolation.

## Anchor semantics

Every anchor binds the workspace ID, raw ID, object SHA-256, adapter identity, coordinate, exact extracted text SHA-256, and record snapshot. Coordinates are structural candidates only. A valid extraction record does not prove that an anchor exists in a visually rendered page, that OCR is correct, that a spreadsheet cached value is current, or that text supports a legal fact.

## Active content and archive policy

- ZIP paths must be portable relative paths; absolute, drive-qualified, `..`, NUL, link-like, encrypted, duplicate, excessive-count, excessive-size, and extreme-compression entries are refused.
- XML containing `DOCTYPE` or `ENTITY` is refused before parsing.
- OOXML macro parts, macro-enabled content types, external relationships, external links, embedded packages, and OLE objects are refused.
- Spreadsheet formula source may be extracted as inert text with a warning; it is never evaluated and cached results are not trusted as recalculated values.
- Email HTML is not rendered and attachments are not recursively parsed in this adapter.

## Output state

Schema or integrity success grants only `LOCAL_EXTRACTION_CANDIDATE_INTEGRITY`. `legal_review_required` and `human_anchor_confirmation_required` remain true, and `submission_ready` remains false.
