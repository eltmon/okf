# OKF-11: Publish a bundle as a public static site with visibility and redaction

Issue: https://github.com/eltmon/okf/issues/11 · Planned 2026-11-15 against `main` at `92a21fe`.

This PRD is the implementation brief. It names every file, function signature, output path, finding code and test. An executor must not re-research or redesign; where a choice exists, this document makes it.

---

## 1. Glossary

- **Bundle.** A directory tree of UTF-8 Markdown files in Open Knowledge Format (OKF). `references/spec.md` is the vendored spec.
- **Concept.** A `.md` file in the bundle other than the reserved `index.md` and `log.md`. It has YAML frontmatter between `---` lines and a Markdown body.
- **Concept ID.** The concept's bundle-relative path without `.md`, in POSIX form, for example `rules/no-spoilers`. `okf_common.concept_id_for_path` computes it.
- **Index file.** A reserved `index.md` in any bundle directory. `scripts/reindex.py` keeps a generated listing between `<!-- OKF:INDEX:BEGIN -->` and `<!-- OKF:INDEX:END -->` markers; prose outside the markers is hand-written.
- **Visibility.** Whether a concept may appear on the published site: `public` or `private`.
- **Public concept.** A concept whose resolved visibility is `public` (§4.2). Every other concept is private.
- **Published directory.** A bundle directory (root included, written `""`) that contains at least one public concept in itself or in any subdirectory.
- **Schema file.** `schema.md` at the bundle root. OKF v0.2 plans it as a `type: Policy` concept (`.pan/drafts/okf-v0.2-redesign.md` §4.2). For this issue it only carries the bundle visibility default.
- **Redaction profile.** The YAML file `okf-publish.yaml` at the bundle root (or `--profile <path>`). It lists regex rules that rewrite published text.
- **Rule.** One redaction entry: an `id`, a Python `re` pattern and a replacement string.
- **Built-in rules.** The rules in `DEFAULT_RULES` in `scripts/publish_redact.py` (§4.5). They apply even with no profile file.
- **Published text.** Every string the site shows: concept title, description, type, status, tags, source entries, body; and the Markdown of published index pages.
- **Trust tier.** A label derived from OKF v0.2 `verified` frontmatter: `human-reviewed`, `machine-confirmed` or `unverified` (§4.4).
- **Site root.** The `--out` directory. Every site path in this PRD is relative to it.
- **Page-relative href.** An href computed from the linking page's own location, for example `../schema.html` from `rules/no-spoilers.html`. The site never uses `/`-rooted hrefs, so it works under a subpath (GitHub Pages project sites) and on any static host.
- **Output marker.** The file `.okf-publish` that `publish.py` writes at the site root. Its presence proves `publish.py` created the directory and may delete its contents.
- **Finding.** One error line printed by `publish.py`, shaped `ERROR <CODE> <location>: <message>` (§4.8).
- **Check mode.** `publish.py --check`: scan without writing; exit 2 if any rule would fire in published text.
- **`PYRUN`.** Shorthand used only in this PRD for `uv run --no-project --python 3.12 --with pyyaml --with pytest`. On the dev machine `python3` is 3.14 without PyYAML, so plain `python3` fails (verified 2026-11-15). Verify commands in the xBRIEF spell the full form.

## 2. Problem and context

A bundle can be viewed only locally today (`/okf open`, which delegates to `pan knowledge open`). Some projects want a public, read-only site. The motivating case is a live-stream project whose viewers propose the rules the AI follows; viewers want to see each rule, who suggested it, and what replaced it.

Publishing the raw bundle is unsafe. Concepts can hold operator-only notes, machine paths, internal incident detail and names of private people. So the site needs per-concept visibility, a deterministic redaction pass, and a gate (`--check`) that fails CI when a rule would fire in a public concept.

**Current code state (verified 2026-11-15, `main` = `92a21fe`):**

- Scripts are separate CLIs under `scripts/` sharing `scripts/okf_common.py`. There is no `okf.py` CLI, no `tests/` directory and no pytest. The gate is `scripts/selftest.sh` (bash greps plus inline Python), run by `.github/workflows/ci.yml`.
- OKF-1 (one CLI and pytest), OKF-4 (`schema.md`), OKF-6 (trust fields) and OKF-8 (viewer) are all still open. The issue says publishing "fits after #6". This plan does not wait (decision D1).
- `okf_common.iter_concept_paths` (`scripts/okf_common.py`, line 174, `def iter_concept_paths(bundle_root: Path) -> Iterable[Path]:`) walks every `*.md`, including `.github/` and `.git/`. Publishing needs its own walker (§4.1).
- `okf_common.resolve_concept_link` (line 126) returns `None` for `index.md` and for directory links, so publishing needs its own link classifier (§4.3).
- `okf_common.LINK_PATTERN` (line 17) and `markdown_links` (line 109) skip fenced code. Publishing reuses `markdown_links` for backlinks.
- The house extension-key convention is an `x_` prefix (`x_embed: exclude`, `scripts/embed.py` line 187). The issue names `x_visibility`, so this plan uses `x_visibility` and `x_visibility_default`.

## 3. Requirements

### Functional

- **FR-1.** `python3 scripts/publish.py --bundle <B> --out <DIR>` writes one HTML page per public concept at `<concept-id>.html`, an `index.html` for every published directory (root always), `search.html`, `search-index.json`, `assets/style.css`, `assets/search.js` and the output marker `.okf-publish`. It writes nothing else.
- **FR-2.** Visibility resolves per concept from frontmatter `x_visibility`, falling back to the bundle default `x_visibility_default` in root `schema.md` frontmatter. A missing `schema.md` or a missing key means the default is `private`. Any value other than the exact strings `public` or `private` is finding `P_VISIBILITY_INVALID`, and the run exits 2 without writing.
- **FR-3.** A private concept appears nowhere on the site. It has no page. Its index listing line is dropped. It has no search record and appears in no backlink list. A body or source link to it renders as plain text (the link text stays; the issue requires this).
- **FR-4.** Links in published Markdown resolve this way: a link to a public concept becomes a page-relative href to its page, keeping any `#fragment`. A link to a published directory or its `index.md` becomes a page-relative href to that directory's `index.html`. `http:`, `https:` and `mailto:` links stay as written. A `#fragment`-only link stays. Every other target renders as plain text: private concepts, missing concepts, unpublished directories, non-Markdown files and any other scheme. A private target and a missing target render identically.
- **FR-5.** Each concept page shows the concept ID, title, type, status, trust tier, tags, description, rendered body, a "Sources" list and a "Linked from" list (backlinks from public concepts only).
- **FR-6.** The trust tier is `human-reviewed` when any `verified` entry has a `by` string that starts with `human:`. Otherwise it is `machine-confirmed` when there is at least one `verified` entry. Otherwise it is `unverified`. A bare mapping counts as a one-element list. Status is frontmatter `status` or `stable` when absent.
- **FR-7.** Search is client-side. `search-index.json` holds one record per public concept. `search.html` loads `assets/search.js`, which fetches the JSON and lists matches. No server code, no CDN and no third-party script.
- **FR-8.** The redaction profile `okf-publish.yaml` (schema in §4.5) adds regex rules and literal `private_strings`, and can disable built-in rules by id. Built-in rules apply with no profile file. Every rule applies to all published text before rendering, including fenced code.
- **FR-9.** `publish.py --check` scans the published text of public concepts and of published index pages. Each rule that matches gives one `P_REDACTION` finding with the rule id and the location (file and line for bodies and index pages, field name for frontmatter). It never prints the matched text. It exits 2 on any finding and 0 otherwise. It writes no files.
- **FR-10.** A rule that matches a public concept ID or a published directory path gives finding `P_ID_REDACTION` in both modes, and the run exits 2 without writing, because URLs cannot be redacted.
- **FR-11.** `--out` safety. The run refuses (finding `P_OUT_UNSAFE`, exit 2) when `--out` resolves to the bundle root or an ancestor of it, is an existing non-directory, or is a non-empty directory without the output marker. When the marker is present, the run deletes every entry in `--out` and rebuilds, so a page from a concept that has turned private never survives.
- **FR-12.** Bundle walking skips any path with a component that starts with `.` (for example `.git`, `.github`, `.okf`, `.okf-index`) or equals `node_modules`, and skips `--out` when it lies inside the bundle. A concept whose frontmatter does not parse gives finding `P_FRONTMATTER_PARSE`, and the run exits 2 without writing. `log.md` is never published. Non-Markdown files are never copied.
- **FR-13.** Documentation: SKILL.md and README command-table rows and a SKILL.md section for `/okf publish`; a README "Publishing a bundle" section covering visibility, the redaction profile and a sample Cloudflare Pages setup; `references/publish.md`; a `docs/USAGE.md` section.
- **FR-14.** A pytest harness under `tests/` runs in CI next to `scripts/selftest.sh`.

### Non-functional

- **NFR-1.** Standard library plus PyYAML only. Python 3.10+ syntax (no `tomllib`, no `typing.Self`, no `ExceptionGroup`). Every new module starts with `#!/usr/bin/env python3`, a one-line docstring and `from __future__ import annotations`.
- **NFR-2.** Deterministic output: two runs on the same bundle produce byte-identical files. No timestamps, sorted iteration everywhere, `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))`.
- **NFR-3.** No existing script changes except the `scripts/selftest.sh` command loop (§6, WI-9). `okf_common.py`, `validate.py`, `reindex.py` and the template copies under `templates/repo/.okf/scripts/` stay byte-identical. No Overdeck imports (selftest greps for them).
- **NFR-4.** HTML safety. All text from the bundle is HTML-escaped. Raw HTML in Markdown renders as escaped text. No `on*=` attributes, no `style=` attributes, no `javascript:` or `data:` hrefs. The only `<script>` on the whole site is `<script src="assets/search.js"></script>` on `search.html`. `search.js` writes results with `textContent` and `setAttribute("href", …)`, never `innerHTML`.
- **NFR-5.** Findings never echo matched secret text, because CI logs of public repos are public.

## 4. Design (decisions made)

### 4.1 Module layout

All new code is flat in `scripts/`, matching the existing `from okf_common import …` style. Files:

| File | Role |
| --- | --- |
| `scripts/publish_markdown.py` | Stdlib Markdown-subset → escaped HTML renderer. |
| `scripts/publish_redact.py` | Built-in rules, profile loading, `redact`, `scan`. |
| `scripts/publish_model.py` | Bundle walk, visibility, trust tier, sources, link classification, backlinks. |
| `scripts/publish_render.py` | Page shell, concept pages, index pages, index filtering, `assets/style.css`. |
| `scripts/publish_search.py` | `search-index.json`, `search.html`, `assets/search.js`. |
| `scripts/publish.py` | CLI: argparse, profile, `--out` safety, redaction application, `--check`, exit codes. |
| `scripts/publish_assets/style.css` | Site stylesheet, copied verbatim to `assets/style.css`. |
| `scripts/publish_assets/search.js` | Search script, copied verbatim to `assets/search.js`. |
| `templates/okf-publish.yaml` | Starter profile users copy to their bundle root. |

Modules locate assets with `Path(__file__).resolve().parent / "publish_assets"`.

### 4.2 Visibility (`publish_model.py`)

```python
VISIBILITY_KEY = "x_visibility"
DEFAULT_KEY = "x_visibility_default"
SCHEMA_FILE = "schema.md"
VISIBILITY_VALUES = ("public", "private")
```

1. Bundle default: if `<bundle>/schema.md` does not exist → `private`, reason `"no schema.md at bundle root"`. If it parses and lacks `x_visibility_default` → `private`, reason `"schema.md has no x_visibility_default"`. If the value is `public` or `private` → that value, reason `"schema.md x_visibility_default: <value>"`. Any other value → finding `P_VISIBILITY_INVALID schema.md: x_visibility_default must be public or private`, default `private`.
2. Per concept: `x_visibility` absent → bundle default. `public`/`private` → that value. Anything else (including `Public`, `true`, `yes`) → finding `P_VISIBILITY_INVALID <path>: x_visibility must be public or private`, concept treated as private.
3. `schema.md` is an ordinary concept for publishing: its own `x_visibility` or the default decides whether it gets a page.

Fail closed: no input ever resolves to public by accident. When zero concepts are public, `publish.py` prints the default reason (§4.8).

### 4.3 Link classification (`publish_model.py`)

```python
@dataclass(frozen=True)
class LinkTarget:
    kind: str          # "concept" | "directory" | "external" | "fragment" | "other"
    value: str         # concept ID, directory path ("" = root), or the raw href
    fragment: str      # text after "#", without the "#"; "" when none

def classify_link(source_dir: str, target: str) -> LinkTarget: ...
```

`source_dir` is the bundle-relative POSIX directory of the page holding the link (`""` for the root). Rules, in order:

1. Split `target` on the first `#` into `path` and `fragment`.
2. `path == ""` → `fragment` kind, value `"#" + fragment`.
3. `path` lowercased starts with `http://`, `https://` or `mailto:` → `external`, value = `target` unchanged.
4. `path` contains `:` → `other` (any other scheme, including `javascript:`, `data:`, `tel:`, `repo:`).
5. Resolve the path: a leading `/` makes it bundle-root relative; otherwise join it to `source_dir`. Normalise `.` and `..`. A `..` that would climb above the root → `other`.
6. Normalised path ends with `/`, or is empty after normalising → `directory`, value = path without trailing `/`.
7. Last segment is `index.md` → `directory`, value = its parent (`""` for root).
8. Last segment is `log.md` → `other`.
9. Ends with `.md` → `concept`, value = path without `.md`.
10. Anything else → `other`.

Whether a `concept` or `directory` target is *published* is decided by the caller (`model.is_public(id)`, `dir in model.public_dirs`).

### 4.4 Model types (`publish_model.py`)

```python
@dataclass(frozen=True)
class Source:
    title: str        # "" when absent
    resource: str     # required; entries without it are skipped
    author: str       # "" when absent

@dataclass(frozen=True)
class PublishConcept:
    concept_id: str
    path: str                 # bundle-relative POSIX path, e.g. "rules/no-spoilers.md"
    directory: str            # "" for root
    title: str                # frontmatter title, else last ID segment
    description: str
    type: str
    tags: tuple[str, ...]
    status: str               # default "stable"
    trust_tier: str
    sources: tuple[Source, ...]
    body: str
    body_start_line: int      # 1-based file line of the first body line
    visibility: str           # "public" | "private"
    links: tuple[str, ...]    # raw link targets from markdown_links(body), in order

@dataclass(frozen=True)
class Finding:
    code: str
    location: str             # "rules/a.md", "rules/a.md:14", "index.md:5"
    message: str
    def line(self) -> str:
        return f"ERROR {self.code} {self.location}: {self.message}"

@dataclass
class PublishModel:
    bundle_root: Path
    default_visibility: str
    default_reason: str
    concepts: dict[str, PublishConcept]   # every parsed concept, keyed by ID
    index_files: dict[str, str]           # directory -> index.md text with any frontmatter removed
    def public_ids(self) -> list[str]: ...          # sorted
    def is_public(self, concept_id: str) -> bool: ...
    def public_dirs(self) -> set[str]: ...          # "" always included
    def backlinks(self, concept_id: str) -> list[str]: ...  # sorted public IDs that link to it

def walk_markdown(bundle_root: Path, exclude: Path | None = None) -> list[Path]: ...
def trust_tier(frontmatter: dict) -> str: ...
def build_model(bundle_root: Path, exclude: Path | None = None) -> tuple[PublishModel, list[Finding]]: ...
```

Normalisation rules:

- `tags`: a list → `str()` of each item; a scalar → one-element tuple; absent → `()`.
- `sources`: a list; each item is either a mapping (use `resource`, `title`, `author`, all `str()`; skip an item without `resource`) or a string (becomes `Source("", s, "")`). A non-list value is ignored.
- `verified` for `trust_tier`: `None`/absent → `[]`; a mapping → `[mapping]`; a list → mapping items only.
- `body_start_line`: index (1-based) of the closing `---` line plus 1; plus 1 more when the following line is empty (because `okf_common.split_frontmatter` drops one leading blank line).
- `backlinks(x)`: IDs `s` with `is_public(s)`, `s != x`, and any `classify_link(s.directory, link)` with kind `concept` and value `x`. Sorted, unique.
- `public_dirs()`: for every public concept, its directory and every ancestor, plus `""`.
- `index_files`: for each `index.md` the walker finds, keyed by its directory. Strip frontmatter when the text starts with `---\n` (the root may carry `okf_version`).
- A concept that fails `okf_common.parse_concept` gives `P_FRONTMATTER_PARSE <path>: <error>` and is left out of `concepts`.
- `walk_markdown` returns sorted `*.md` paths. It skips any path whose bundle-relative parts include a component starting with `.` or equal to `node_modules`, and skips paths under `exclude` when `exclude` is inside the bundle. It does not skip `log.md`; `build_model` ignores `log.md` itself.

### 4.5 Redaction (`publish_redact.py`)

Profile schema (`okf-publish.yaml`):

```yaml
okf_publish_version: "0.1"      # required, must be the string "0.1"
disable_default_rules: []        # optional; ids from DEFAULT_RULES
rules:                           # optional; applied after built-in rules
  - id: stream-box-host          # required, unique, matches ^[a-z0-9][a-z0-9-]*$
    pattern: '\bstream-box\.lan\b'   # required, Python re syntax; inline flags such as (?i) allowed
    replace: '[internal-host]'   # optional, default "[redacted]"
private_strings:                 # optional; literal strings, matched case-insensitively
  - Alice Example
```

Built-in rules (exact patterns, in this order):

```python
DEFAULT_RULES: tuple[tuple[str, str, str], ...] = (
    ("home-path-unix", r"/(?:home|Users)/[^/\s'\"`)\]>]+", "~"),
    ("home-path-windows", r"[A-Za-z]:\\Users\\[^\\\s'\"`)\]>]+", "~"),
    ("ipv4", r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b", "[ip]"),
    ("github-token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "[token]"),
    ("openai-style-key", r"\bsk-[A-Za-z0-9_-]{20,}", "[token]"),
    ("aws-access-key", r"\bAKIA[0-9A-Z]{16}\b", "[token]"),
    ("slack-token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}", "[token]"),
    ("private-key-block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "[private-key]"),
)
```

`private_strings` entry *n* (1-based) becomes rule `private-string-<n>` with pattern `re.escape(s)`, flag `re.IGNORECASE`, replacement `[redacted]`. Order of application: enabled built-in rules, then `rules`, then `private_strings`.

```python
@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern[str]
    replace: str
    origin: str   # "default" | "profile" | "private_strings"

@dataclass(frozen=True)
class Profile:
    rules: tuple[Rule, ...]
    path: Path | None          # None when built-in rules only

def default_profile() -> Profile: ...
def load_profile(bundle_root: Path, profile_path: Path | None = None) -> tuple[Profile | None, list[str]]: ...
def redact(text: str, profile: Profile) -> tuple[str, dict[str, int]]: ...
def scan(text: str, profile: Profile) -> list[tuple[str, int]]: ...
```

- `load_profile`: with `profile_path` given, that file must exist. Without it, use `<bundle>/okf-publish.yaml` when it exists, else `default_profile()`. Return `(None, errors)` on any error: unreadable YAML, top level not a mapping, unknown top-level key, `okf_publish_version` not `"0.1"`, unknown id in `disable_default_rules`, rule without `id` or `pattern`, invalid id, duplicate id (including a clash with a built-in id), a pattern that fails `re.compile` (message names the rule id and the `re.error`), an empty private string, or a non-string value. Each error string is one sentence naming the field.
- `redact`: apply each rule with `pattern.sub(replace, text)` in order. Return the new text and `{rule_id: substitutions}` for rules that fired. `replace` is passed as a literal (escape backslashes with `replace.replace("\\", "\\\\")` before `sub`, so `\1` is not a group reference).
- `scan`: for each rule, each match in the *original* text gives `(rule.id, line)` where `line = text.count("\n", 0, match.start()) + 1`. Return sorted unique pairs.
- `templates/okf-publish.yaml` contains `okf_publish_version: "0.1"`, `disable_default_rules: []`, commented examples of one rule and one private string, and a comment listing every built-in rule id. A test asserts the commented id list equals `[r[0] for r in DEFAULT_RULES]`.

False positives: `ipv4` also matches `127.0.0.1` and four-part version numbers. A bundle that hits this either rewrites the text or adds `ipv4` to `disable_default_rules`. This is documented, and there is no per-match allow list (non-goal).

### 4.6 Rendering (`publish_markdown.py`, `publish_render.py`)

```python
LinkResolver = Callable[[str], Optional[str]]
def render_markdown(text: str, resolve_link: LinkResolver) -> str: ...
```

`resolve_link(raw_target)` returns an href or `None`; `None` renders only the link text. The renderer re-checks every href it emits: an href whose part before the first `/`, `?` or `#` contains `:` must start with `http:`, `https:` or `mailto:` (case-insensitive), otherwise the link renders as text.

Supported Markdown (everything else is escaped text inside a paragraph):

| Construct | Output |
| --- | --- |
| ATX heading `#`–`######` | `<hN id="slug">…</hN>`; slug = lowercase, runs of non-`[a-z0-9]` → `-`, trimmed; repeats get `-2`, `-3` |
| Paragraph (consecutive non-blank lines) | `<p>…</p>`, lines joined with `\n` |
| Fenced code ```` ``` ```` or `~~~` with optional info word | `<pre><code class="language-<word>">escaped</code></pre>`; class only when the word matches `^[A-Za-z0-9_+-]+$` |
| Blockquote `> ` | `<blockquote>` + recursive render |
| Unordered list `-`, `*`, `+` and ordered `1.` | `<ul>`/`<ol>` with `<li>`; an item line indented by 2+ more spaces than its parent starts a nested list |
| Thematic break `---`, `***`, `___` alone | `<hr>` |
| GFM pipe table (header row, `\|---\|` separator row, body rows) | `<table><thead>…</thead><tbody>…</tbody></table>` |
| Footnote definition `[^label]: text` (line start) | collected; emitted at the end as `<section class="footnotes"><ol><li id="fn-<slug>">…</li></ol></section>` |
| Inline code `` `x` `` | `<code>escaped</code>` (no further inline parsing inside) |
| Link `[text](target)` and `[text](target "title")` | `<a href="…">text</a>` or plain text per resolver |
| Image `![alt](src)` | escaped alt text only (no `<img>`; assets are never copied) |
| Autolink `<https://…>` / `<mailto:…>` | `<a href>` (same scheme check) |
| Footnote reference `[^label]` with a definition | `<sup class="fnref"><a href="#fn-<slug>" id="fnref-<slug>">N</a></sup>`; N = order of first reference; an undefined reference stays as escaped literal text |
| `**x**` / `__x__`, `*x*` / `_x_` | `<strong>`, `<em>` |

Escaping uses `html.escape(s, quote=True)` on every text run and attribute value. Raw HTML such as `<script>alert(1)</script>` in a body renders as `&lt;script&gt;alert(1)&lt;/script&gt;`.

`publish_render.py`:

```python
def concept_page_path(concept_id: str) -> str: ...      # "rules/no-spoilers.html"
def dir_index_path(directory: str) -> str: ...          # "index.html" or "rules/index.html"
def relative_href(from_page: str, to_page: str) -> str: ...   # page-relative, URL-quoted segments
def make_resolver(model: PublishModel, source_dir: str, page_path: str) -> LinkResolver: ...
def filter_index_markdown(text: str, directory: str, model: PublishModel) -> str: ...
def page_shell(*, title: str, site_title: str, page_path: str, body_html: str, scripts: tuple[str, ...] = ()) -> str: ...
def site_title(index_texts: dict[str, str]) -> str: ...
def render_site(model: PublishModel, index_texts: dict[str, str], out_dir: Path) -> list[str]: ...
```

- `relative_href("rules/no-spoilers.html", "schema.html") == "../schema.html"`; `relative_href("index.html", "rules/a.html") == "rules/a.html"`; same directory → bare file name. Segments are quoted with `urllib.parse.quote(seg, safe="")`.
- `make_resolver` applies FR-4 using `classify_link`: public `concept` → `relative_href(page_path, concept_page_path(id))` plus `#fragment` when present; published `directory` → `relative_href(page_path, dir_index_path(dir))`; `external` and `fragment` → value; all else → `None`.
- `filter_index_markdown`: for each line that starts (after optional indentation) with `* ` or `- ` and contains a Markdown link, classify the **first** link. Drop the line when that link is a `concept` that is not public, or a `directory` not in `public_dirs()`. Keep every other line unchanged. Process every line, including any inside fenced code, because index listings are never fenced.
- `site_title`: the text of the first line starting with `# ` in `index_texts[""]`, stripped; otherwise `"Knowledge"`.
- `page_shell` emits exactly this structure (`rel` = `"../" * page_path.count("/")`):

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {site_title}</title>
<link rel="stylesheet" href="{rel}assets/style.css">
</head>
<body>
<header class="site"><a class="home" href="{rel}index.html">{site_title}</a>
<form class="search" action="{rel}search.html" method="get" role="search"><input type="search" name="q" placeholder="Search" aria-label="Search"></form>
</header>
<main>
{body_html}
</main>
<footer class="site">Published from an Open Knowledge Format bundle.</footer>
{one <script src="{rel}{path}"></script> line per scripts entry}
</body>
</html>
```

- Concept page body (`title`, `site_title` and all text escaped):

```html
<article class="concept">
<p class="concept-id"><code>{concept_id}</code></p>
<h1>{title}</h1>
<p class="badges"><span class="badge type">{type}</span> <span class="badge status status-{status_class}">{status}</span> <span class="badge trust trust-{trust_tier}">{trust_tier}</span></p>
<p class="description">{description}</p>                       <!-- only when non-empty -->
<ul class="tags"><li>{tag}</li>…</ul>                            <!-- only when tags -->
<div class="body">{render_markdown(body, resolver)}</div>
<section class="sources"><h2>Sources</h2><ul>…</ul></section>    <!-- only when sources -->
<section class="backlinks"><h2>Linked from</h2><ul>…</ul></section>  <!-- only when backlinks -->
</article>
```

  `status_class` = status lowercased when it matches `^[a-z0-9-]+$`, else `other`. A source `<li>` shows the title (or the resource when the title is empty), then ` — {author}` when present. The source resource is linked only when `make_resolver` returns an href for it; a `repo:path@sha` resource therefore renders as text. A backlink `<li>` is `<a href="{relative}">{title}</a>`.
- `render_site` writes, for each public concept, `concept_page_path(id)`. For each published directory, it writes `dir_index_path(dir)`: when `dir` is in `index_texts`, it renders that text with `make_resolver(model, dir, page)`; otherwise it renders a generated listing `# {last dir segment}` followed by `* [title](file.md) - description` lines for public concepts directly in `dir` and `* [child/](child/)` lines for published child directories. It copies `publish_assets/style.css` to `assets/style.css`. It returns the sorted list of written paths. Page titles: the concept title; for index pages, the first `# ` heading of the index text, else the directory name, else the site title for the root.

### 4.7 Search (`publish_search.py`, `publish_assets/search.js`)

```python
def search_text(body: str) -> str: ...
def search_records(model: PublishModel) -> list[dict[str, str]]: ...
def write_search(model: PublishModel, out_dir: Path, site_title: str) -> None: ...
```

- `search_text`: remove fenced-code fence lines (keep their content), replace `![alt](x)` with `alt` and `[text](x)` with `text`, drop footnote markers `[^x]`, collapse whitespace runs to one space, strip. Link targets never reach the index.
- One record per public concept, sorted by `id`: `{"id", "title", "description", "type", "url": concept_page_path(id), "text": search_text(body)}`.
- `write_search` writes `search-index.json` (NFR-2 dump settings), `search.html` (via `page_shell(scripts=("assets/search.js",))`, body `<h1>Search</h1><p id="okf-status"></p><ol id="okf-results"></ol>`), and copies `publish_assets/search.js` to `assets/search.js`.
- `search.js` behaviour: read `q` from `location.search`; put it in the header input; if empty, set status "Type a search term."; else `fetch("search-index.json")`, split `q` lowercase on whitespace into terms, keep records where every term occurs in `title + " " + description + " " + text` lowercased, score 3 per term in title, 2 in description, 1 in text, sort by score descending then `id`, show at most 50 as `<li><a href=url>title</a> <span>description</span></li>` built with `document.createElement`, `textContent` and `setAttribute`. Status text: `"N result(s)"` or `"No results."`. On fetch failure, status: `"Search needs the site to be served over HTTP."`. No `innerHTML`, no `eval`, no external URLs.

### 4.8 CLI (`publish.py`)

```
python3 scripts/publish.py [--bundle B] (--out DIR | --check) [--profile FILE]
```

`--out` and `--check` are a required mutually exclusive argparse group. Flow:

1. `bundle = Path(args.bundle).resolve()`. Missing directory → `ERROR P_BUNDLE_MISSING <path>: bundle directory not found`, exit 2.
2. `load_profile`; errors → one `ERROR P_PROFILE_INVALID <profile path>: <error>` line each, exit 2.
3. `out = Path(args.out).resolve()` when given. `build_model(bundle, exclude=out)`.
4. ID check: for each public ID and each published directory path (non-empty), `scan(value, profile)` hits → `P_ID_REDACTION <path>: rule <id> matches the concept ID; rename the concept or make it private` (directories: `... matches the directory path ...`).
5. Index texts: `filtered = {d: filter_index_markdown(t, d, model) for d, t in model.index_files.items() if d in model.public_dirs()}`.
6. `--check`: for each public concept, scan `title`, `description`, `type`, `status`, each tag, each source's `title`/`resource`/`author` (location `<path>`, message `rule <id> matches published text (field <name>)`), and `body` (location `<path>:<body_start_line + line - 1>`, message `rule <id> matches published text (field body)`). For each filtered index text: location `<dir>/index.md:<line>` (root `index.md:<line>`), field `index`. Line numbers in index texts are relative to the stripped text; when the root index had frontmatter, add the stripped line count so numbers match the file.
7. Print every finding sorted by `(location-path, line, code, message)`. Any finding → exit 2.
8. `--check` with no findings: print `ok - publish check passed: <N> public concept(s), no redaction rule matches`, exit 0.
9. `--out`: prepare the directory (FR-11): refuse cases → `P_OUT_UNSAFE <out>: <reason>`, exit 2. Otherwise create it, delete all entries if the marker is present, write `.okf-publish` with the text `Generated by OKF publish.py. Every run deletes and rebuilds this directory.\n`.
10. Build redacted copies: every published string field of every public concept via `dataclasses.replace`, and every `filtered` index text, through `redact`; sum the counts.
11. `render_site(redacted_model, redacted_index_texts, out)`, then `write_search(redacted_model, out, site_title(redacted_index_texts))`.
12. Print `ok - published <N> public concept(s) to <out> (<P> private excluded, <R> redaction(s) applied)`. When N is 0, also print `note - no public concepts: default visibility is private (<default_reason>); set x_visibility: public on concepts or x_visibility_default: public in schema.md`. Exit 0.

Finding codes (all `ERROR`, all exit 2): `P_BUNDLE_MISSING`, `P_PROFILE_INVALID`, `P_FRONTMATTER_PARSE`, `P_VISIBILITY_INVALID`, `P_ID_REDACTION`, `P_REDACTION` (check mode only), `P_OUT_UNSAFE`. When any finding exists in `--out` mode, nothing is written and the existing `--out` contents stay untouched.

Redaction runs over the model's text, including link targets in bodies. If a rule rewrites a link target, that link may become plain text. This is safe (it only removes links) and documented.

## 5. Repo rules restated for the executor

- Stdlib + PyYAML only; Python 3.10+ (NFR-1). Do not add dependencies or a `pyproject.toml`.
- Do not import or call Overdeck or `pan` from any script (selftest greps `scripts/`, `.py`, `.js`, `.sh` for it).
- Do not edit `okf_common.py`, `validate.py`, `reindex.py`, `diff_lint.py`, `embed.py`, `build_index.py`, `search.py` or `templates/repo/.okf/scripts/*` (NFR-3; OKF-1 will restructure them).
- Run tests with `uv run --no-project --python 3.12 --with pyyaml --with pytest python -m pytest …`. Plain `python3` on the dev machine is 3.14 without PyYAML.
- Stage files by explicit path. The workspace holds untracked `.claude/` and `.overdeck/` trees, and `.overdeck/config.yaml` there contains live credentials. Never `git add -A`, `git add .` or `git commit -a`.
- The SKILL.md and README command tables must list identical `/okf …` strings in the same order (selftest drift check), so WI-9 changes both tables and the selftest loop in one commit.
- Tests that copy the fixture use pytest's `tmp_path` and `shutil.copytree`; never mutate `tests/fixtures/` in a test. No test sleeps or waits on real time.
- Prose in docs: short, plain sentences; active voice.

## 6. Work items

Each item lands as its own commit with an `Item: <id>` trailer.

### WI-1 `pytest-harness` — pytest in CI (FR-14)

Files: `tests/conftest.py`, `tests/test_harness.py`, `.github/workflows/ci.yml`.

1. `tests/conftest.py`: insert `str(Path(__file__).resolve().parents[1] / "scripts")` at the front of `sys.path`, and define fixtures `scripts_dir` (that path) and `fixture_bundle` (returns `Path(__file__).parent / "fixtures" / "publish_bundle"`).
2. `tests/test_harness.py`: `test_okf_common_importable` imports `okf_common` and asserts `okf_common.concept_id_for_path(Path("a/b.md")) == "a/b"`.
3. `.github/workflows/ci.yml` before:

```yaml
      - run: python -m pip install pyyaml
      - run: bash scripts/selftest.sh
```

after:

```yaml
      - run: python -m pip install pyyaml pytest
      - run: bash scripts/selftest.sh
      - run: python -m pytest -q tests
```

Test: `uv run --no-project --python 3.12 --with pyyaml --with pytest python -m pytest -q tests/test_harness.py` passes.

### WI-2 `markdown-renderer` — escaped Markdown subset (FR-4, NFR-4)

Files: `scripts/publish_markdown.py`, `tests/test_publish_markdown.py`. Implements §4.6 `render_markdown`. Tests (all in `tests/test_publish_markdown.py`):

- `test_raw_html_is_escaped`: `<script>alert(1)</script>` and `<img src=x onerror=alert(1)>` render escaped; output contains no `<script` and no `<img`.
- `test_disallowed_schemes_render_as_text`: a resolver that returns `javascript:alert(1)` and `data:text/html,x` yields plain text; `https://example.com` yields `<a href="https://example.com">`.
- `test_resolver_none_renders_link_text`: `[Secret](/ops/x.md)` with a resolver returning `None` renders `Secret` and no `<a`.
- `test_blocks`: headings with slug ids (duplicate gets `-2`), paragraphs, nested unordered list, ordered list, blockquote, `<hr>`, fenced code with `language-python` and escaped content, a pipe table with `<thead>`.
- `test_footnotes`: `Claim.[^s1]` plus `[^s1]: Source text` renders a `fnref` superscript linking `#fn-s1` and a footnotes section; an undefined `[^zz]` stays literal.
- `test_inline`: code span content is not formatted; `**b**`, `*i*`, image renders alt text only.

### WI-3 `redaction-rules` — profile, built-in rules, redact and scan (FR-8, FR-9, NFR-5)

Files: `scripts/publish_redact.py`, `templates/okf-publish.yaml`, `tests/test_publish_redact.py`. Implements §4.5. Tests:

- `test_default_rules_redact_samples`: `/home/alice/x` → `~/x`; `C:\Users\bob\x` → `~\x`; `10.0.0.12` → `[ip]`; a `ghp_` + 36 alphanumerics token → `[token]`; `-----BEGIN RSA PRIVATE KEY-----` → `[private-key]`; counts dict names each rule.
- `test_private_strings_case_insensitive`: profile with `private_strings: [Alice Example]` redacts `alice example` and reports rule id `private-string-1`.
- `test_disable_default_rule`: `disable_default_rules: [ipv4]` leaves `127.0.0.1` unchanged.
- `test_profile_errors`: each invalid profile in §4.5 returns `(None, errors)` with a message naming the field; an invalid regex message names the rule id.
- `test_scan_reports_lines_not_text`: `scan("a\n/home/alice\n", p)` returns `[("home-path-unix", 2)]`.
- `test_replace_is_literal`: a rule with `replace: '\1'` inserts a literal `\1`.
- `test_template_lists_default_ids`: the commented id list in `templates/okf-publish.yaml` equals the `DEFAULT_RULES` ids, and the template loads with no errors via `load_profile(tmp, template_path)`.

### WI-4 `publish-model` — walk, visibility, trust, links, backlinks, fixture bundle (FR-2, FR-3, FR-6, FR-12)

Files: `scripts/publish_model.py`, `tests/test_publish_model.py`, `tests/fixtures/publish_bundle/**`. Implements §4.2–§4.4.

Fixture bundle `tests/fixtures/publish_bundle/` (exact contents up to wording; the named strings are exact):

| Path | Frontmatter essentials | Body essentials |
| --- | --- | --- |
| `index.md` | none | `# Stream Rules Knowledge`; prose `See [the incident](/ops/incident-42.md).`; marker listing with lines `* [ops/](ops/) - Subdirectory`, `* [rules/](rules/) - Subdirectory`, `* [Schema](schema.md) - Bundle conventions.` |
| `schema.md` | `type: Policy`, `title: Schema`, `description: Bundle conventions.`, `x_visibility: public`, `x_visibility_default: public` | short prose |
| `rules/index.md` | none | `# Rules`; marker listing for `mod-notes.md`, `no-spoilers.md`, `old-spoiler-rule.md` with their titles and descriptions |
| `rules/no-spoilers.md` | `type: Rule`, `title: No spoilers`, `description: Do not reveal plot points.`, `tags: [chat, rules]`, `status: stable`, `sources: [{id: s1, resource: "https://example.com/vod/1", title: Chat proposal, author: viewer-anna}]`, `verified: [{by: "human:host", at: "2026-11-01T00:00:00Z"}]` | `Proposed in chat.[^s1]`; links `[old rule](old-spoiler-rule.md)`, `[incident](/ops/incident-42.md)`, `[future rule](/rules/not-written-yet.md)`, `[VOD](https://example.com/vod/1)`, `[rules home](index.md)`; `[^s1]: Chat proposal from viewer-anna.` |
| `rules/old-spoiler-rule.md` | `type: Rule`, `title: Old spoiler rule`, `description: Replaced rule.`, `status: deprecated`, `verified: {by: "process:ci", at: "2026-10-01T00:00:00Z"}` | `Replaced by [No spoilers](no-spoilers.md).` |
| `rules/mod-notes.md` | `type: Note`, `title: ZZ-PRIVATE-MOD-NOTES`, `description: ZZ-PRIVATE-MOD-DESC`, `x_visibility: private` | mentions `/home/alice/mod.txt` |
| `ops/index.md` | none | marker listing for `incident-42.md` |
| `ops/incident-42.md` | `type: Incident`, `title: ZZ-PRIVATE-INCIDENT`, `description: ZZ-PRIVATE-INCIDENT-DESC`, `x_visibility: private` | `/home/alice/stream/obs.json`, `10.0.0.12`, `Alice Example` |
| `log.md` | none | `# Directory Update Log`, `## 2026-11-01`, `* **Update**: Added [incident](/ops/incident-42.md)` |
| `okf-publish.yaml` | `okf_publish_version: "0.1"`, one rule `stream-box-host` (`\bstream-box\.lan\b` → `[internal-host]`), `private_strings: [Alice Example]` | — |
| `.github/notes.md` | no frontmatter at all | `plain text` (proves dot-dirs are skipped) |

Public content must contain no rule match, so `--check` passes on the unmodified fixture.

Tests (`tests/test_publish_model.py`):

- `test_fixture_public_and_private`: `public_ids() == ["rules/no-spoilers", "rules/old-spoiler-rule", "schema"]`; `ops/incident-42` and `rules/mod-notes` are present and private; findings empty; `.github/notes.md` produced no finding.
- `test_default_private_without_schema`: on a `tmp_path` copy with `schema.md` deleted, `public_ids() == []` and `default_reason == "no schema.md at bundle root"`.
- `test_default_private_without_key`: copy with `x_visibility_default` removed → `public_ids() == ["schema"]`.
- `test_invalid_visibility`: `x_visibility: Public` → one `P_VISIBILITY_INVALID` finding; the concept is private.
- `test_parse_error_finding`: a `notes/bad.md` without frontmatter → one `P_FRONTMATTER_PARSE` finding naming `notes/bad.md`.
- `test_trust_tier`: list with `human:` → `human-reviewed`; bare mapping with `process:ci` → `machine-confirmed`; absent → `unverified`.
- `test_classify_link`: one assertion per rule 1–10 of §4.3, including `../../x.md` from `rules` → `other`, `javascript:x` → `other`, `/rules/` → `directory "rules"`, `index.md` from `rules` → `directory "rules"`.
- `test_backlinks_public_only`: `backlinks("rules/no-spoilers") == ["rules/old-spoiler-rule"]`; a temporary private concept linking to it does not appear.
- `test_public_dirs`: `public_dirs() == {"", "rules"}`.
- `test_body_start_line`: `rules/no-spoilers` `body_start_line` equals the file line of its first body line.

### WI-5 `site-pages` — concept and index pages with page-relative links (FR-1, FR-3, FR-4, FR-5)

Files: `scripts/publish_render.py`, `scripts/publish_assets/style.css`, `tests/test_publish_render.py`. Implements §4.6 `publish_render.py` (not search). `style.css`: system font stack, max-width 48rem main column, badge styles per `status-*`/`trust-*`, and a `@media (prefers-color-scheme: dark)` block. No external fonts or `@import`.

Tests (render the fixture model to `tmp_path` with unredacted texts):

- `test_relative_href`: the three examples in §4.6 plus a deeper case.
- `test_filter_index_drops_private_lines`: the filtered root index has no `ops/` line; the filtered `rules/index.md` has no `ZZ-PRIVATE-MOD-NOTES`; the hand-written prose line keeps `the incident` as text.
- `test_concept_page_contents`: `rules/no-spoilers.html` contains the concept ID, `human-reviewed`, `stable`, the `Chat proposal — viewer-anna` source, a "Linked from" entry for `Old spoiler rule` with `href="old-spoiler-rule.html"`, `href="../index.html"` in the header, and the words `incident` and `future rule` with no `<a` around them.
- `test_written_pages`: the returned list equals `["assets/style.css", "index.html", "rules/index.html", "rules/no-spoilers.html", "rules/old-spoiler-rule.html", "schema.html"]`.
- `test_generated_listing_without_index_md`: deleting `rules/index.md` from a copy still writes `rules/index.html` listing both public rules and not `ZZ-PRIVATE-MOD-NOTES`.

### WI-6 `search-index` — JSON index, search page and script (FR-7, NFR-4)

Files: `scripts/publish_search.py`, `scripts/publish_assets/search.js`, `tests/test_publish_search.py`. Implements §4.7.

Tests:

- `test_records_public_only`: record ids equal `public_ids()`; no record text contains `ZZ-PRIVATE`; the `rules/no-spoilers` text contains `incident` but not `/ops/incident-42.md`.
- `test_search_html_shell`: `search.html` contains exactly one `<script` tag, `src="assets/search.js"`, and the `okf-results` list.
- `test_search_js_is_safe`: `search.js` does not contain `innerHTML`, `eval(`, `http://` or `https://`, and does contain `textContent` and `fetch("search-index.json")`.
- `test_json_is_deterministic`: two `write_search` runs give byte-identical `search-index.json`.

Browser UAT (test role): serve the published fixture with `python3 -m http.server --directory <out> <port>` in an isolated Playwright browser; open `search.html?q=spoilers`; the results list shows `No spoilers` and `Old spoiler rule`, and no `ZZ-PRIVATE` text appears anywhere on the page.

### WI-7 `publish-command` — `publish.py --out` (FR-1, FR-10, FR-11, NFR-2)

Files: `scripts/publish.py`, `tests/test_publish_cli.py`. Implements §4.8 steps 1–5 and 9–12. Tests run the CLI with `subprocess.run([sys.executable, str(scripts_dir / "publish.py"), ...])` against `tmp_path` copies:

- `test_publish_fixture_pages`: exit 0; the set of `*.html` under `--out` equals `{"index.html", "rules/index.html", "rules/no-spoilers.html", "rules/old-spoiler-rule.html", "schema.html", "search.html"}`; `ops/incident-42.html`, `rules/mod-notes.html`, `ops/index.html` and any `log.html` do not exist.
- `test_no_unresolved_links`: parse every `.html` with `html.parser.HTMLParser`; for each `href`/`src` not starting with `http:`, `https:`, `mailto:` or `#`, strip `?…`/`#…`, `urllib.parse.unquote`, resolve against the page's directory, and assert the file exists inside `--out`.
- `test_no_private_or_secret_bytes`: no file under `--out` contains `ZZ-PRIVATE`, `/home/alice`, `10.0.0.12` or `Alice Example` (case-insensitive); running `scan` with the fixture profile over every output file returns no match.
- `test_redaction_applied`: add `Mirror lives at /home/bob/vod` and `stream-box.lan` to the body of `rules/old-spoiler-rule.md` in a copy; publish exits 0, prints a non-zero redaction count, and the page contains `~/vod` and `[internal-host]`.
- `test_deterministic`: two publishes to two directories produce identical file lists and identical bytes.
- `test_out_safety`: `--out` equal to the bundle → exit 2 with `P_OUT_UNSAFE`; a non-empty directory without `.okf-publish` → exit 2 and its files untouched; a second publish into a marked directory after making `rules/old-spoiler-rule.md` private removes `rules/old-spoiler-rule.html`.
- `test_id_redaction_blocks`: a public concept at `hosts/stream-box.lan.md` (ID `hosts/stream-box.lan`, matched by the fixture rule `stream-box-host`) → exit 2 with `P_ID_REDACTION`, and `--out` is not created.
- `test_errors_write_nothing`: an invalid `x_visibility` → exit 2, `P_VISIBILITY_INVALID` printed, `--out` not created.
- `test_zero_public_note`: with `schema.md` deleted → exit 0 and stdout contains `note - no public concepts` and `no schema.md at bundle root`.

### WI-8 `publish-check-mode` — `publish.py --check` gate (FR-9, NFR-5)

Files: `scripts/publish.py`, `tests/test_publish_cli.py`. Implements §4.8 steps 6–8. Tests:

- `test_check_passes_on_fixture`: exit 0, stdout starts with `ok - publish check passed: 3 public concept(s)`; no files written anywhere (the bundle copy's file list is unchanged).
- `test_check_fails_on_home_path_then_passes`: **Given** a copy where `rules/no-spoilers.md` body line `Setup notes: /home/alice/obs.json` is added, **when** `publish.py --check` runs, **then** it exits 2 and prints `ERROR P_REDACTION rules/no-spoilers.md:<n>: rule home-path-unix matches published text (field body)` where `<n>` is that line's file line number, and stdout does not contain `/home/alice`. **Given** the author replaces the line with `Setup notes: ~/obs.json`, **when** `--check` runs again, **then** it exits 0.
- `test_check_ignores_private`: the unmodified fixture's private concepts hold home paths, an IP and a private string, yet check exits 0.
- `test_check_frontmatter_field`: `description: Runs on 10.0.0.12` on a public concept → exit 2 with `rule ipv4 matches published text (field description)`.
- `test_check_index_text`: hand-written prose `Hosted on stream-box.lan` in root `index.md` → exit 2 with location `index.md:<line>`.
- `test_check_and_out_exclusive`: passing both flags exits 2 with an argparse error.

### WI-9 `skill-command-row` — command tables and selftest loop (FR-13)

Files: `SKILL.md`, `README.md`, `scripts/selftest.sh`. One commit (drift check).

1. SKILL.md command table: after the `/okf embed` row (line 38), add
   ``| `/okf publish --out <dir> [--check]` | Build a public static site from public concepts, with redaction. | `references/publish.md` |``
2. README command table: after the `/okf embed` row (line 85), add
   ``| `/okf publish --out <dir> [--check]` | Build a public static site from public concepts, with redaction. |``
3. SKILL.md: append a section after `## \`/okf embed …\``:

```markdown
## `/okf publish --out <dir> [--check]`

Build a public static site from the bundle.

- Run `python3 <okf-skill-dir>/scripts/publish.py --bundle <bundle> --check` first; it exits 2 when a redaction rule matches text in a public concept and names the rule and line, never the matched text.
- Then run `python3 <okf-skill-dir>/scripts/publish.py --bundle <bundle> --out <dir>`.
- Only concepts with `x_visibility: public`, or covered by `x_visibility_default: public` in root `schema.md`, are published. The default is private.
- Links to private or missing concepts render as plain text. `log.md` and non-Markdown files are never published.
- Redaction rules come from built-in defaults plus `okf-publish.yaml`; see `references/publish.md`.
- Never mark a concept public or edit a redaction profile without the user's request. Deploying the site is outside this skill.
```

4. `scripts/selftest.sh` line 27 before: `for command in init author convert sync study retro extract validate lint embed; do` — after: `for command in init author convert sync study retro extract validate lint embed publish; do`.

Test: `uv run --no-project --python 3.12 --with pyyaml --with pytest bash scripts/selftest.sh` exits 0 and prints `ok - SKILL.md documents /okf publish` and the README drift check line.

### WI-10 `publishing-docs` — README section, reference page, usage guide (FR-13)

Files: `README.md`, `references/publish.md`, `docs/USAGE.md`.

1. README: add `## Publishing a bundle` after `## The Three Loops` (before `## Reading Rules`). Content, in order:
   - What it builds (pages, indexes, search, plain static files; any static host works; deploying is outside the skill).
   - **Visibility**: `x_visibility: public | private`, `x_visibility_default` in `schema.md`, private by default, private links render as plain text and the link text stays (so the link text should not itself be secret).
   - **Redaction profile**: the `okf-publish.yaml` example from §4.5, the built-in rule ids, `disable_default_rules`, `private_strings`, `--check` as the CI gate.
   - **Sample Cloudflare Pages setup**: this workflow, verbatim apart from wording in comments:

```yaml
name: Publish knowledge site
on:
  push:
    branches: [main]
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      deployments: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/checkout@v4
        with:
          repository: eltmon/okf
          ref: vX.Y.Z            # a release that includes scripts/publish.py
          path: .okf-skill        # dot-directory: the publisher skips it
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python3 -m pip install PyYAML
      - run: python3 .okf-skill/scripts/publish.py --bundle . --check
      - run: python3 .okf-skill/scripts/publish.py --bundle . --out _site
      - uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy _site --project-name=<your-pages-project>
```

   - One sentence for GitHub Pages: upload `_site` with `actions/upload-pages-artifact` and deploy with `actions/deploy-pages`; page-relative links work under a project subpath.
   - One sentence: search fetches `search-index.json`, so preview with `python3 -m http.server --directory _site` rather than opening files directly.
2. `references/publish.md`: command synopsis; visibility rules (§4.2); link rules (FR-4); trust tier rule (FR-6); profile schema and built-in rules table (§4.5) including the `ipv4` false-positive note; output layout (FR-1); finding codes and exit codes (§4.8); the `--out` safety and rebuild rule (FR-11); "What is never published" list (`log.md`, private concepts, non-Markdown files, dot-directories, frontmatter keys other than those in FR-5).
3. `docs/USAGE.md`: add `## \`/okf publish --out <dir> [--check]\`` after the `/okf embed` section (before `## Model Ladder`) with two example commands and four bullets matching the SKILL.md section.

Checks: the grep commands in AC-10. No docs test file is added.

## 7. Acceptance criteria (map 1:1 to work items)

- **AC-1 (WI-1).** `python -m pytest -q tests` runs in CI after the selftest step, and `tests/test_harness.py` passes locally with the `uv run` form.
- **AC-2 (WI-2).** `tests/test_publish_markdown.py` passes; raw `<script>` and `onerror=` input never produces a `<script` or `<img` tag; `javascript:` hrefs render as text.
- **AC-3 (WI-3).** `tests/test_publish_redact.py` passes; built-in rules apply without a profile; `scan` returns rule ids and line numbers only.
- **AC-4 (WI-4).** `tests/test_publish_model.py` passes; the fixture's public set is exactly `rules/no-spoilers`, `rules/old-spoiler-rule`, `schema`; a bundle without `schema.md` has no public concepts.
- **AC-5 (WI-5).** `tests/test_publish_render.py` passes; private listing lines are dropped and private/missing links render as text.
- **AC-6 (WI-6).** `tests/test_publish_search.py` passes; `search.js` has no `innerHTML`; browser UAT finds `No spoilers` for `q=spoilers` on a served site.
- **AC-7 (WI-7).** `test_publish_fixture_pages`, `test_no_unresolved_links`, `test_no_private_or_secret_bytes`, `test_out_safety` and `test_deterministic` pass (issue acceptance bullet 1).
- **AC-8 (WI-8).** `test_check_fails_on_home_path_then_passes` passes: exit 2 with the rule id and file line and no echoed path, then exit 0 after the edit (issue acceptance bullet 2).
- **AC-9 (WI-9).** `bash scripts/selftest.sh` (via `uv run`) exits 0 with `ok - SKILL.md documents /okf publish`.
- **AC-10 (WI-10).** `grep -n '^## Publishing a bundle' README.md` matches; the section contains `x_visibility`, `okf-publish.yaml`, `cloudflare/wrangler-action@v3` and `publish.py --bundle . --check`; `references/publish.md` lists all seven `P_*` codes (issue acceptance bullet 3).

## 8. Non-goals

- Deploying the site, or any host-specific config file beyond the README sample (the issue puts deploying outside the skill).
- Publishing `log.md`, non-Markdown assets (images, PDFs), embeddings or the `.okf-index/` cache.
- Rendering `generated`/`verified` actor identities (only the derived trust tier is shown).
- A per-match allow list for redaction rules; bundles disable a whole built-in rule instead.
- Redacting or rewriting concept IDs or directory names (a match is a hard error instead).
- Excluding drafts or deprecated concepts automatically; visibility alone decides inclusion, and status is shown as a badge.
- Full CommonMark: HTML blocks, setext headings, reference-style links, indented code blocks and hard line breaks are not supported.
- Changing `okf_common.py` or other existing scripts, adding an `okf.py` CLI, or vendoring the publish scripts into `templates/repo/.okf/scripts/` (OKF-1/OKF-4 own those).
- Adding `x_visibility` checks to `validate.py`.
- Search ranking beyond term matching, stemming or fuzzy search.
- A site theme or configuration option (site title comes from the root `index.md` heading).

## 9. Planning Q&A

This session ran in `pan plan --auto` mode, so no questions went to the operator. Each would-be question and the default chosen:

1. **Wait for OKF-1/OKF-4/OKF-6, or build now?** Options: block on the v0.2 restructure; build on today's v0.1 scripts. Chosen: build now, as new `scripts/publish*.py` files that touch no existing script, and read v0.2 `verified`/`status`/`sources` keys tolerantly. Why: "fits after #6" is sequencing advice, and isolated new files keep OKF-1's later move cheap.
2. **Key name for the bundle default in `schema.md`?** Options: `x_visibility_default`; reuse `x_visibility` (ambiguous, because `schema.md` is itself a concept). Chosen: `x_visibility_default`.
3. **Default when no default is configured?** Options: public; private. Chosen: private. Why: publishing must be opt-in, and the CLI explains why zero concepts were published.
4. **Markdown rendering?** Options: client-side CDN `marked`; a stdlib renderer. Chosen: a stdlib renderer with full escaping. Why: no third-party script on a public site, deterministic output, and testable XSS boundary.
5. **Do built-in rules apply with no profile?** Chosen: yes; a bundle disables one by id. Why: fail toward redaction.
6. **What does "passes after redaction" mean?** Chosen: after the author removes the matching text from the source concept; `--check` scans source text and never passes because `publish` would redact.
7. **Test framework?** The repo has no pytest. Chosen: add `tests/` with pytest in CI (the v0.2 plan's direction for OKF-1), keeping `selftest.sh`.
8. **Search index loading?** Options: `fetch` of `search-index.json`; a `.js` file that sets a global. Chosen: `fetch` of JSON, as the issue says "prebuilt JSON index"; `file://` previews are documented as unsupported.
