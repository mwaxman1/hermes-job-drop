# Resume builder

Deterministic: the profile supplies every word of content; the job description only decides
**which** verified bullets appear and in what order, and may trim the summary.

## The invariant

- `profile.yaml` is the only source of resume claims.
- A JD may **select and order** bullets within a role. It may never rewrite a bullet, merge
  two, add a metric, or add a skill the profile does not list.
- Every role with `core: true` appears on every resume. If a tailoring step would drop one,
  the build **fails loudly**, naming the role. Silent omission is the exact failure this
  design exists to prevent.
- Non-core roles may be dropped for space, oldest first.
- Each kept role keeps at least two bullets (or all, if it has fewer).

The `resume` slot's job is narrow: given the JD and the list of verified bullets (by id),
return which bullet ids to keep per role, in order, and optionally a summary that is a trimmed
version of the profile summary. Validate that every returned id exists and every returned
summary sentence appears in (or is a shortening of) the profile summary.

## Template token contract

`~/.hermes/jobdrop/templates/resume.html` (shipped default in the repo's `templates/`).

| Token | Kind | Content |
|---|---|---|
| `FULL_NAME` | text | first + last (preferred first name if set) |
| `HEADLINE` | text | `headline`, or the most recent title |
| `CONTACT_LINE` | text | email · phone · City, ST · links — only the parts present, joined by ` · ` |
| `SUMMARY` | text | the (trimmed) summary |
| `EXPERIENCE` | html | one `.role` block per kept role |
| `SKILLS` | html | one `<p class="skill-line"><strong>Group:</strong> a, b</p>` per group |
| `EDUCATION` | html | one `.role`-shaped block per entry |
| `CERTIFICATIONS` | html | one `<p class="cert">Name — Issuer, Year</p>` per entry |

Tokens are written with double braces in the template (e.g. the token `SUMMARY`). Text
tokens are HTML-escaped. A `<section data-optional>` whose token renders empty is removed so
no heading appears with nothing under it. A token in the user's template that the builder
does not know is reported as a **warning** and left visible, so a typo is noticed rather than
silently dropping a section. A user may replace the template wholesale.

Role block shape:

```html
<div class="role">
  <div class="role-head"><span class="role-title">Title</span><span class="role-dates">2021-04 – Present</span></div>
  <div class="role-sub"><span class="role-employer">Employer</span> · Location</div>
  <ul><li>Verified bullet</li></ul>
</div>
```

## Rendering to PDF — Chrome

The user's Chrome is already required for driving forms, so it renders the PDF too (no extra
system libraries). Render-only, so an isolated throwaway profile is correct **here**:

```bash
UD="$(mktemp -d)"
timeout 60 google-chrome --headless=new --disable-gpu --no-sandbox --no-first-run \
  --no-default-browser-check --no-pdf-header-footer --user-data-dir="$UD" \
  --virtual-time-budget=5000 --print-to-pdf="$OUT/resume.pdf" "$OUT/resume.html"
rm -rf "$UD"
```

- `--no-pdf-header-footer` is required: without it Chrome stamps the date and the local file
  path on every page — a path that can contain the user's home directory name.
- `timeout 60` guards against a hung Chrome. Headless Chrome sometimes writes the PDF and
  then does not exit; a timeout with a complete PDF on disk is fine — check the file.
- Chrome binary names: `google-chrome`, `google-chrome-stable`, `chromium`, `chromium-browser`;
  on macOS `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`.
- Fallback when Chrome is unavailable: WeasyPrint (`weasyprint in.html out.pdf`) if installed.
  Chrome is the default and documented path.

## The visual gate

A resume is a visual artifact. Before the first real application with a new or edited
template, render it with the user's real profile, rasterize page 1 (and page 2 if present) to
PNG (e.g. `pdftoppm -r 110 -png resume.pdf page`), and **look at the image**. Fail on:

- overlapping text, or a title colliding with its dates;
- a clipped or cut-off right edge, or text running off the page;
- a section heading with no content under it;
- a page break that separates a role title from its bullets;
- unreadable contrast, or a summary overflowing its box;
- a near-empty last page (tighten spacing or drop a non-core role).

If the environment cannot rasterize, open the rendered HTML in Chrome, screenshot it, and
inspect the screenshot instead. "It looks clean" without having looked at an image is a fail.
