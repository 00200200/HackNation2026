---
name: web-design-guidelines
description: Review web UI files against Vercel's Web Interface Guidelines (accessibility, focus, forms, animation, typography, copy). Use before committing changes under frontend/, or when asked to audit the UI, UX or accessibility of the web channel.
argument-hint: <file-or-pattern>
---

# Web Interface Guidelines review

1. Read [references/command.md](references/command.md). It holds every rule and the output format.
2. Read the files to review: the argument, or `frontend/public/index.html`, `styles.css` and `app.js` by default.
3. Check them against the rules, with the project overrides below, and report in the `file:line` format the
   guidelines define. No preamble.

## Project overrides (repo rules win)

- Stack: static HTML/CSS/JS behind nginx with a strict CSP (no inline styles or scripts, no external fonts or
  CDNs). Skip rules that only apply to React or Next.js (hydration, `<Link>`, `nuqs`, virtualization libraries) and
  any fix that needs inline code or a third-party host.
- Copy is Polish: sentence case, not Title Case; Polish quotes „…”; the service speaks as "my". User-facing text also
  goes through `/humanizer`.
- Honesty rules from `CLAUDE.md` still apply: never label a sample, fixture or estimate as a live result.

## Source

Rules: `references/command.md`, a verbatim copy of
https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/command.md
(SHA-256 `d246b026f4f29b5823a9cc857f9edf3d2507002e055e32040cadeaf3b38e0234`), MIT, Copyright (c) 2025 Vercel Labs;
license in `.claude/third-party/vercel-web-interface-guidelines.LICENSE`. Read the local copy; do not fetch rules from
the network. To update: download a newer commit, review the diff, update the URL and hash here.
