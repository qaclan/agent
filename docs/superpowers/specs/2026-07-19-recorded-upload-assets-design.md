# Recorded file-upload test assets

## Problem

Playwright codegen records `set_input_files(<name>)` (or `setInputFiles`)
when a script interacts with a file input. The recorded value is only ever
the **basename** of the picked file (e.g. `report.pdf`) — never a real
filesystem path. This is a hard browser-security limitation, not a
Playwright quirk: the injected in-page recorder can only read
`input.files[i].name` (confirmed in `pollingRecorderSource.js`,
`playwright-core`); JS in a page is never given the real absolute path of a
file picked via native OS dialog. So there is no way, at record time, for
qaclan to know where on disk the referenced file actually lives.

(An earlier version of this spec assumed the recorded value was a
machine-local absolute path and designed an auto-copy step around
`os.path.isabs(path)`. That assumption was wrong — real recordings never
produce an absolute path, so that step could never fire. This revision
replaces it with an explicit attach step.)

Separately (already fixed, unrelated to this spec): codegen also records a
redundant `.click()` immediately before `set_input_files()` on the same
locator, which opens a real unhandled native OS file-picker dialog when
replayed headed. That fix lives in `_strip_upload_click()` in
`javascript_strategy.py` / `python_strategy.py` — unaffected by this
revision.

## Goal

After recording (or when editing an existing script), the user can attach
the actual file(s) a `set_input_files`/`setInputFiles` call needs, via a
"Files" tab in the existing review wizard and script editor. The script is
rewritten to reference the attached file through a portable token that
resolves correctly at run time, on any machine.

Out of scope for this spec: any migration/fix-up of scripts recorded before
this feature existed (they keep whatever bare filename they currently have
until the user re-attaches via the new Files tab themselves — no automatic
migration).

## Storage layout

`~/.qaclan/uploads/<script_id>/<basename>` — one folder per script.
Unchanged from the original design.

- No cross-script content deduplication. If two scripts happen to reference
  the identical file, it is stored twice. Test fixtures are KB–low-MB scale;
  the disk cost of duplication is negligible next to the complexity of
  refcounting shared files across script deletion.
- Deleting a script deletes its upload folder (`shutil.rmtree`, best-effort;
  already implemented).
- Attaching a same-name file overwrites the existing copy in that script's
  own folder — safe, since the folder is scoped to that script only.

## Size cap

Configurable, default 20 MB per file. Backed by `~/.qaclan/config.json` via
`get_upload_size_cap_mb()` / `set_upload_size_cap_mb()` in `cli/config.py`
(already implemented, unchanged). Enforced server-side on the new upload
endpoint: a file over the cap is rejected with a 4xx and a clear message,
not silently truncated or partially saved.

## Reference mechanism: reserved template token

Unchanged: `{{__qaclan_upload_dir__}}`, resolved in `web/routes/runs.py`
immediately before the rendered script is written, independent of the
normal `{{KEY}}` substitution path. See existing implementation — no
changes needed there.

What changes is **who writes the token into the script source, and when**:
previously "automatically, at record time, by copying from an absolute
path" (impossible, see Problem); now "explicitly, when the user attaches a
file via the Files tab, by a client-side string replace of the exact
recorded call."

## UI: Files tab

Added as a 4th tab in the existing post-record review wizard
(`openReviewWizard()` / `state.phases` in `web/static/app.js`, alongside
the current Bind/Waits/Typed tabs) and reused inside the existing script
editor (`editScriptModal()`), since both already share the "load script
source → let user edit → commit" flow.

Behavior:

1. Scan the current script source (from the wizard's live-edited text, same
   source the other 3 tabs read/write) for
   `set_input_files(...)`/`setInputFiles(...)` calls whose argument is a
   plain quoted string or array of strings that is **not** already the
   `{{__qaclan_upload_dir__}}/...` token form.
2. For each detected reference, show: the referenced filename, and whether
   a file with that basename already exists in
   `~/.qaclan/uploads/<script_id>/` (attached) or not (missing — needs
   attaching).
3. A file-picker control per missing reference uploads a file, which:
   - POSTs it (multipart) to the new upload endpoint,
   - on success, rewrites that occurrence in the in-memory script source
     from `set_input_files("<name>")` to
     `set_input_files("{{__qaclan_upload_dir__}}/<name>")` (basename of the
     uploaded file, which may differ from the originally recorded name —
     use the uploaded file's actual name).
4. A free-standing "add file" control (not tied to any detected call) lets
   the user attach additional files up front — covers scripts with many
   upload steps (10-12+), where attaching happens before all the
   corresponding calls exist, or files used by later manual edits.
5. Already-attached files can be removed (deletes from
   `~/.qaclan/uploads/<script_id>/`; does not rewrite the script source —
   removing a file the source still references is the user's call, same as
   any other broken reference they'd need to fix manually).
6. Commit behavior matches the other 3 tabs: the rewritten source becomes
   part of what `_wizardCommit()` saves (`PUT /scripts/<id>` for
   post-record source, or the live editor for the `editor` source).

## New backend endpoints (`web/routes/scripts.py`)

- `GET /api/scripts/<script_id>/uploads` — list `{name, size}` for every
  file in that script's upload folder (empty list if folder doesn't exist).
- `POST /api/scripts/<script_id>/uploads` — multipart file upload. Enforces
  `get_upload_size_cap_mb()`; creates the folder if needed; overwrites on
  same-name conflict. Returns the saved `{name, size}`.
- `DELETE /api/scripts/<script_id>/uploads/<filename>` — removes one file
  from the folder. No-op (200) if already absent.

## Components touched

1. **`cli/script_strategies/python_strategy.py` /
   `javascript_strategy.py`** — remove `_extract_upload_files()` and its
   call in `post_process_recording` (dead code, can never fire — see
   Problem). Keep `_strip_upload_click()` / `_UPLOAD_CLICK_RE` as-is
   (unrelated, still correct). `post_process_recording`'s `upload_dir`
   parameter becomes unused and is removed along with the call-site plumbing
   in `record.py` that computed it — the Files tab creates/writes the
   upload folder itself, on demand, via the new endpoints.
2. **`web/routes/scripts.py`** — add the 3 endpoints above.
3. **`web/static/app.js`** — new "Files" wizard tab (`_wizardMountAttach`-
   style function, added to `state.phases`), reused in `editScriptModal()`.
4. **`web/routes/runs.py`** — unchanged, already resolves the token.
5. **`cli/config.py`**, **`qaclan.py`** — unchanged, cap getter/setter and
   CLI command already implemented.

## Data flow

```
recording finishes → raw script has bare filename, e.g. "report.pdf"
  → review wizard opens, Files tab detects the bare reference
  → user uploads the real file via Files tab
      → POST /api/scripts/<id>/uploads saves it to
        ~/.qaclan/uploads/<script_id>/report.pdf
      → wizard rewrites source: "report.pdf" → "{{__qaclan_upload_dir__}}/report.pdf"
  → user commits wizard → saved script (DB + file) contains the token
  → execute_run: token resolved to the real absolute upload-dir path
  → subprocess runs against a file that actually exists
```

Same flow, minus the "recording finishes" step, when attaching/replacing
files later via the script editor's Files tab.

## Error handling

- Upload over the size cap: endpoint returns 4xx with a clear message;
  frontend surfaces it inline in the Files tab, upload not saved.
- Upload folder missing at run time (e.g. manually deleted between attach
  and run): `set_input_files` throws its normal Playwright error, already
  flows through `error_classifier.py` — no new handling needed.
- Script deletion: existing `shutil.rmtree(upload_dir, ignore_errors=True)`
  in the delete route, unchanged.
- Deleting an attached file via the Files tab while the source still
  references it: allowed; becomes a normal missing-file run-time error, no
  special guard — matches the "user's responsibility" precedent already
  used elsewhere in this design (e.g. cap-exceeded case).

## Testing

No automated test suite exists in this repo (per `CLAUDE.md`). Verification
is manual, via `app.test_client()` E2E scripts in the scratchpad plus real
Flask requests:

1. `GET`/`POST`/`DELETE` the 3 new endpoints against a throwaway script row
   — confirm list/upload/delete all behave, including the cap-exceeded
   rejection.
2. Drive a recording, open the Files tab, confirm a bare `setInputFiles()`
   reference is detected as "missing."
3. Attach a file through the tab; confirm the in-memory source is rewritten
   to the token form and, after commit, the saved script contains it.
4. Run a suite containing such a script; confirm the upload step succeeds
   headed (no native OS dialog, correct file resolved) — this is the same
   E2E harness already used for the original Task 6 (`e2e_task6.py`).
5. Open an existing (already-saved) script in the editor, confirm the Files
   tab shows the same list/attach/remove behavior against that script's
   folder.

## Explicitly not doing

- No auto-capture at record time (proven impossible — see Problem).
- No fix-up of scripts recorded before this feature (they keep their
  current bare filename until the user attaches via the Files tab
  themselves).
- No cross-script content deduplication / refcounting.
- No rewriting of a script's source when a file is removed via the Files
  tab (see Error handling) — no auto-detection/repair loop.
