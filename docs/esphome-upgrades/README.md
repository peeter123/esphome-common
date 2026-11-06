# ESPHome release reviews

One file per ESPHome minor release (`2026.10.md` covers 2026.10.0 and its
patch releases). Each file records the release review that `AGENTS.md`
requires before raising a project's pin, so the changelog is read once and
every project is checked against the same list.

## Writing a review

1. Read the release blog post's upgrade guide (linked from the changelog
   page), then the full changelog at `https://esphome.io/changelog/X.Y.0/`.
   The changelog page is about 250,000 characters; read it in parts until the
   end, including any patch-release sections.
2. Add each later patch release (`X.Y.1`, `X.Y.2`, ...) to the same file as it
   ships, and update `Reviewed up to`.
3. Keep the review project-neutral: list what changed and which components or
   C++ APIs it affects. Per-project findings belong in that project's commit.

## File layout

```markdown
# ESPHome X.Y

Reviewed up to: X.Y.Z (YYYY-MM-DD)
Sources: changelog URL, blog post URL

## Breaking changes (YAML)
- component: what changed; what to check or change.

## Behaviour changes
- component: changed defaults or runtime behaviour without a config error.

## C++ API changes (lambdas and external components)
- class or function: what changed.

## Patch releases
### X.Y.1 (date)
- Fixes relevant to consumers.

## Gaps
- Anything the sources did not state, so a project check knows what is
  unverified.
```
