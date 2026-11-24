# MC-174 implementation plan: an optional agent-built panel on a cron run

## Goal
`submit_cron_report` takes an optional `panel` (stat tiles and bar or line charts, a validated static A2UI surface), stored in its own column `cron_runs.panel`, given back to the next run's prompt, and drawn above Summary, Findings and Checked on the run's page.

## Architecture
- **Backend.** `backend/app/a2ui/catalog.json` gains `Chart`. `backend/app/a2ui/service.py` adds `PANEL_COMPONENTS`, `PanelError`, `clean_panel` (the card checks, shared with `clean_card`, then chart-data checks, then the catalog), `unwrap` and `panel_guide`. `CronRun.panel` (JSONB, null) is written by `app/crons/report.py:apply_report` before any task or comment; `app/crons/turns.py:cron_prompt` gives the newest earlier panel back; `CronRunOut.panel` carries it to the UI (null inside `last_run`). MCP: `submit_cron_report(..., panel?)` and `get_panel_guide()`.
- **Frontend.** `--chart-3`/`--chart-4` join the theme; `ChartFrame` moves to `components/ui/`; `components/a2ui/Chart.tsx` (Recharts, lazily loaded by `Surface.tsx`, which stays the only `@a2ui/*` importer) draws a chart with a table view; `components/crons/CronReport.tsx` draws the panel above Summary with a fallback line.

## Conventions every step follows
- Backend tests run from `backend/`: `megoocolab-runner services run test -- uv run pytest <paths> -q`. Never two pytest runs at once. Before each backend commit also run `megoocolab-runner services run test -- uv run pytest tests/workflow tests/mcp -q -n auto` and `uvx ruff check --select E9,F app tests`.
- Frontend checks from `frontend/`: `npx vitest run <paths>`, `npx tsc --noEmit`, `npx eslint <changed files>`. No Prettier.
- One commit per step, Conventional Commits ending `(MC-174)`, body with why and what, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nothing from `.megoocolab/` is committed.
- Known baseline failure (not a regression): `tests/dashboard/test_speed.py::test_dashboard_answers_under_300ms_with_10k_tasks`.

## The `points` mode (settled in step 1)
Step 1 records with `record_decision` one of two modes; every later step uses that mode only:
- **Mode B (binding, the design's first choice):** `"points": {"@path": "/trend"}`. Catalog: `points` refers to the a2ui-core `common_types.json` def that types a value which may be a data binding to any JSON value (the one `DynamicString`/`DynamicNumber` are built from); frontend `ChartApi.schema.points` uses the matching `core.CommonSchemas` entry, and the renderer hands the adapter the resolved list.
- **Mode P (path string, the design's fallback):** `"points": "/trend"`. Catalog: `"points": {"type": "string", "pattern": "^/", "description": "An absolute data-model path to the list of points, e.g. '/trend'."}`; frontend schema `z.string()`, and the adapter reads the list from the surface's data model (`surface.dataModel.get(path)`, passed to adapters through `FormContext` as `read(path)`).

Examples below are written in mode B; in mode P replace `{"@path": "/x"}` in `points` by `"/x"`.

## File map
| File | Change |
| --- | --- |
| `frontend/src/app/globals.css` | `--chart-3`, `--chart-4` in light and dark |
| `frontend/src/lib/useThemeColors.ts` | reads `chart-3`, `chart-4` |
| `frontend/src/lib/__tests__/themeTokens.test.ts` | + four chart colours in both themes |
| `backend/app/a2ui/catalog.json` | + `Chart`, in `$defs.anyComponent.oneOf` |
| `backend/tests/a2ui/test_catalog.py` | `COMPONENTS` + `Chart`; library accepts/rejects a chart |
| `frontend/src/components/a2ui/catalog.tsx` | `COMPONENT_PROPS.Chart` |
| `frontend/src/components/a2ui/__tests__/catalog.test.ts` | + `Chart` present |
| `backend/app/a2ui/service.py` | `PANEL_COMPONENTS`, `MAX_PANEL_BYTES`, `MAX_CHARTS`, `PanelError`, `_checked_display` (shared), `_chart_problems`, `clean_panel`, `unwrap`, `panel_guide` |
| `backend/app/a2ui/panel_guide.md`, `panel_example.json` | new |
| `backend/tests/a2ui/fixtures/panels.json` | new: valid and invalid panels |
| `backend/tests/a2ui/test_panels.py` | new |
| `backend/tests/a2ui/test_cards.py` | + forms and cards refuse a `Chart` |
| `backend/app/crons/models.py` | `CronRun.panel` |
| `backend/migrations/versions/<rev>_cron_run_panel.py` | new: `cron_runs.panel` JSONB null |
| `backend/app/crons/schemas.py`, `service.py` | `CronRunOut.panel`; `run_out(..., with_panel=)`; `last_run` without panel |
| `frontend/src/lib/api-types.ts` | regenerated |
| `backend/app/crons/report.py` | `apply_report(..., panel)` |
| `backend/app/mcp_server/cron_tools.py` | `panel` argument, `get_panel_guide` |
| `backend/tests/crons/test_panel.py` | new: storage, refusal, tools, prompt, API, migration column |
| `backend/tests/mcp/test_mcp.py` | tool list + `get_panel_guide` |
| `backend/app/crons/turns.py` | "The last panel" section |
| `backend/app/workflow/methodology_texts/defaults/cron.md` | tools list + "A panel" |
| `backend/app/workflow/methodology_history.py` | new hash for `cron` |
| `backend/tests/workflow/test_methodology.py` | + cron text teaches panels |
| `frontend/src/components/sprint/ChartFrame.tsx` → `frontend/src/components/ui/ChartFrame.tsx` | moved; Velocity/Burndown import it |
| `frontend/src/components/ui/__tests__/ChartFrame.test.tsx` | new |
| `frontend/src/components/a2ui/Chart.tsx` | new: the Recharts chart |
| `frontend/src/components/a2ui/__tests__/Chart.test.tsx` | new |
| `frontend/src/components/a2ui/Surface.tsx` | `ChartApi`, lazy `Chart` |
| `frontend/src/components/a2ui/__tests__/Surface.test.tsx` | + panels |
| `frontend/src/components/crons/CronReport.tsx` | Panel section |
| `frontend/src/components/crons/__tests__/crons.test.tsx` | + panel cases |
| `frontend/e2e/crons.spec.ts` | the report carries a panel |

## Reference code

### R1. Catalog entry `Chart` (mode B shown; `<BINDING_REF>` is the def recorded in step 1)
```json
"Chart": {
  "type": "object",
  "description": "A bar or line chart of numbers from the data model, one point per label on the x axis, 1 to 4 series. Panels only. Series take the theme's chart colours in the order listed; you never pick a colour. A snapshot: it never updates.",
  "properties": {
    "component": {"const": "Chart"},
    "kind": {"enum": ["bar", "line"], "type": "string", "description": "bar for counts per label, line for a trend across runs."},
    "title": {"type": "string", "minLength": 1, "maxLength": 120, "description": "What the chart shows, e.g. 'Failing tests by suite, last 14 runs': its heading and accessible name."},
    "points": {"$ref": "<BINDING_REF>", "description": "A binding to a list of 1 to 50 objects in data, e.g. {\"@path\": \"/trend\"}."},
    "x": {"type": "string", "minLength": 1, "maxLength": 40, "description": "The key of each point that holds its label (a day, a suite name)."},
    "series": {
      "type": "array", "minItems": 1, "maxItems": 4,
      "items": {"type": "object", "additionalProperties": false, "required": ["key", "label"],
                "properties": {"key": {"type": "string", "minLength": 1, "maxLength": 40, "description": "The key of the number in each point."},
                               "label": {"type": "string", "minLength": 1, "maxLength": 40, "description": "The series' name in the legend and table."}}},
      "description": "1 to 4 series."
    },
    "unit": {"type": "string", "maxLength": 8, "description": "A short unit shown after values, e.g. 's', 'ms' or '%'."},
    "weight": {"$ref": "#/$defs/Weight"}
  },
  "required": ["component", "kind", "title", "points", "x", "series"]
}
```
Add `{"$ref": "#/components/Chart"}` at the end of `$defs.anyComponent.oneOf`.

### R2. `service.py` additions (signatures and behaviour)
```python
PANEL_COMPONENTS = CARD_COMPONENTS | {"Chart"}
MAX_PANEL_BYTES = 16 * 1024
MAX_CHARTS = 4


class PanelError(FormError):
    """A panel refused: the same 422 as FormError (the code, then up to MAX_PROBLEMS "path: message" lines)."""


def _checked_display(value: Any, name: str, error: type[FormError], allowed: frozenset[str],
                     max_bytes: int) -> tuple[list, dict | None]:
    """The checks every read-only surface (a card, a panel) gets, as clean_card made them: its shape, NUL stripped,
    its size, its component count, no inputs, only `allowed` components, tabs, task keys, data arrays. Codes are
    invalid_<name>, <name>_with_inputs and too_large; shape problems have the path `name`. Returns (components, data)."""
```
`clean_card` becomes `components, data = _checked_display(card, "card", CardError, CARD_COMPONENTS, MAX_CARD_BYTES)`, then `wrap(..., prefix="card")` and `_library` as today. Its behaviour and messages stay byte-for-byte the same (every existing test in `test_cards.py` passes unchanged).

```python
def _points(component: dict) -> str | None:
    """The data-model path a chart's points are bound to (mode B: points["@path"]; mode P: points itself)."""

def _resolve(data: dict, path: str) -> Any:
    """The value at an absolute JSON pointer in data (~1 is "/", ~0 is "~"), or None when it isn't there."""

def _chart_problems(components: list, data: dict) -> list[dict]:
    """Each chart's data checked against the panel's own data, as {path, message} problems."""

def clean_panel(panel: Any) -> dict:
    """The agent's {components, data?} as a validated, stored panel surface. Raises PanelError."""
    components, data = _checked_display(panel, "panel", PanelError, PANEL_COMPONENTS, MAX_PANEL_BYTES)
    charts = [c for c in components if c["component"] == "Chart"]
    if len(charts) > MAX_CHARTS:
        raise PanelError("too_large", [{"path": "components", "message": f"over {MAX_CHARTS} charts"}])
    if problems := _chart_problems(charts, data or {}):
        raise PanelError("invalid_panel", problems)
    message = wrap(components, data, prefix="panel")
    if problems := _library(message):
        raise PanelError("invalid_panel", problems)
    return message

def unwrap(message: dict) -> dict:
    """The {components, data} an agent writes, from a stored createSurface message."""
    surface = message["createSurface"]
    return {"components": surface["components"], "data": surface.get("dataModel") or {}}

def panel_guide() -> dict:
    """What get_panel_guide gives an agent: instructions, the panel part of the catalog and an example panel."""
    return {"instructions_md": _panel_instructions(), "catalog": _catalog_for(PANEL_COMPONENTS),
            "example": _panel_example()}
```
`_chart_problems` rules, per chart `c` (id `i = c.get("id")`), skipping a rule when the shape it reads is wrong (the catalog check after it names that):
1. `points` path missing or not starting with `/` → `components.{i}.points`: `must be an absolute path such as /trend`.
2. `_resolve(data, path)` not a list of 1 to 50 objects → `components.{i}.points`: `{path} is not a list of 1 to 50 objects in data`. (Over 50 is already `too_large` from the data-array check.) Skip rules 3 to 5 for this chart.
3. A point without a `str` or number (`int`/`float`, not `bool`) under `x` → `components.{i}.x`: `point {n} of {path} has no text or number under "{x}"` (first such point only).
4. Series keys repeat, or one equals `x` → `components.{i}.series`: `series keys must differ from each other and from x`.
5. For series `s` at index `k`: a point whose value under `s.key` is present, not None and not a number → `components.{i}.series.{k}.key`: `point {n} of {path} has {value!r} under "{key}", not a number`; no point with a number → `components.{i}.series.{k}.key`: `no point of {path} has a number under "{key}"`.

### R3. `backend/app/a2ui/panel_example.json`
```json
{
  "components": [
    {"id": "root", "component": "Column", "children": ["tiles", "charts"]},
    {"id": "tiles", "component": "Row", "children": ["failing", "passed", "duration", "flaky"]},
    {"id": "failing", "component": "StatTile", "label": "Failing", "value": "3", "caption": "1 fewer than last run", "tone": "bad"},
    {"id": "passed", "component": "StatTile", "label": "Passed", "value": "412", "tone": "good"},
    {"id": "duration", "component": "StatTile", "label": "Suite time", "value": "4m 12s"},
    {"id": "flaky", "component": "StatTile", "label": "Flaky", "value": "2", "tone": "warning"},
    {"id": "charts", "component": "Row", "children": ["trend", "slowest"]},
    {"id": "trend", "component": "Chart", "kind": "line", "title": "Failing tests by suite, last 3 runs",
     "points": {"@path": "/trend"}, "x": "day",
     "series": [{"key": "api", "label": "API"}, {"key": "web", "label": "Web"}]},
    {"id": "slowest", "component": "Chart", "kind": "bar", "title": "Slowest suites", "points": {"@path": "/slowest"},
     "x": "suite", "series": [{"key": "seconds", "label": "Time"}], "unit": "s"}
  ],
  "data": {
    "trend": [{"day": "Nov 22", "api": 4, "web": 1}, {"day": "Nov 23", "api": 3, "web": 1}, {"day": "Nov 24", "api": 2, "web": 1}],
    "slowest": [{"suite": "api", "seconds": 131}, {"suite": "web", "seconds": 74}, {"suite": "runner", "seconds": 38}]
  }
}
```

### R4. `backend/tests/a2ui/fixtures/panels.json`
Shape `{"valid": [{"name", "panel"}], "invalid": [{"name", "code", "path_contains"?, "panel"}]}`. Every chart has the ids shown.
- valid: `example` (R3, same content), `line-four-series` (one line chart `c`, keys `a b c d`, 3 points), `bar-one-series-unit` (one bar chart `c`, `unit: "ms"`), `gaps` (line chart `c` where one point has `null` and one lacks the key, others numbers), `card-only` (Tabs, List template with TaskLink, StatTile, no chart).
- invalid:
  - `input` → `panel_with_inputs` (a TextField)
  - `button` → `invalid_panel`, `components.send.component`
  - `five-series` → `invalid_panel`, `series`
  - `five-charts` → `too_large`, `components` (five one-series bar charts)
  - `bad-kind` (`"kind": "pie"`) → `invalid_panel`, `kind`
  - `points-relative` (`trend` without `/`) → `invalid_panel`, `components.c.points`
  - `points-missing` (`/nowhere`) → `invalid_panel`, `components.c.points`
  - `points-empty` (`[]`) → `invalid_panel`, `components.c.points`
  - `points-not-objects` (`[1, 2]`) → `invalid_panel`, `components.c.points`
  - `fifty-one-points` → `too_large`, `data.trend`
  - `x-missing` (a point without `day`) → `invalid_panel`, `components.c.x`
  - `value-not-number` (`"api": "3"`) → `invalid_panel`, `components.c.series.0.key`
  - `series-no-number` (every `web` null) → `invalid_panel`, `components.c.series.1.key`
  - `duplicate-key` → `invalid_panel`, `components.c.series`
  - `key-is-x` → `invalid_panel`, `components.c.series`
  - `seven-tabs` → `too_large`, `components.root.tabs`
  - `bad-task-key` → `invalid_panel`, `components.link.task`
  - `extra-key` (top-level `surfaceId`) → `invalid_panel`, `panel`

### R5. `cron.md` changes
Tools list, replace the `submit_cron_report` bullet with:
```markdown
- `submit_cron_report(summary, findings, checked, nothing_new, document_md?, panel?)`: your report. Call it **once**,
  at the end. Each finding is `{title, detail, new_task?, existing_task_key?}`. `panel` is optional: see "A panel".
- `get_panel_guide()`: what a panel may contain. Call it before you send your first panel.
```
New part after "## Each run":
```markdown
## A panel

A panel is tiles and charts drawn above your report on the run's page: `{components, data}` (see
`get_panel_guide()`).

- Send one only when the job watches numbers that read better as tiles or a chart than as a sentence: counts,
  sizes, durations, rates, a trend across runs. Otherwise leave it out.
- Summary, findings and checked must be complete without it. Notifications, triggers and opened tasks carry only
  those.
- Every number in it comes from a command of this run, or from the last panel for earlier points.
- For a trend, start from the last panel in your prompt: keep its layout, update the tiles, add this run's point to
  each series, and drop the oldest point past 50.
- A refused panel refuses the whole call and nothing is stored: fix it and call again. If it is refused twice, send
  the report without it.
```
Also in "## Untrusted content" change "The last run's report, task texts" to "The last run's report and panel, task texts".

### R6. `cron_prompt` addition (after the "The last run's report" part)
```python
    last_panel = await db.scalar(
        select(CronRun).where(CronRun.cron_id == cron.id, CronRun.scheduled_at < run.scheduled_at,
                              CronRun.panel.is_not(None))
        .order_by(CronRun.scheduled_at.desc()).limit(1)
    )
    if last_panel is not None:
        parts.append(f"## The last panel\n\nFrom the run of {last_panel.scheduled_at:%Y-%m-%d %H:%M} UTC. For a trend, "
                     "keep its layout, update its tiles and add this run's point to each series.\n\n"
                     + wrap_untrusted("last panel", json.dumps(a2ui.unwrap(last_panel.panel))))
```
(`json` imported at module top; `from app.a2ui import service as a2ui`.) `CronRun.panel` is only ever assigned a message, never `None`, so a run without a panel keeps SQL NULL.

## Steps

### 1. Settle the four open points; add the chart-3 and chart-4 colours
See the step detail.

### 2. Catalog: the Chart component, in panels only
### 3. clean_panel: validate a panel, sharing the card checks
### 4. The panel guide
### 5. cron_runs.panel: the column, the migration and the API
### 6. submit_cron_report takes a panel; get_panel_guide
### 7. The next run's prompt carries the last panel
### 8. The cron methodology text says when a panel is worth sending
### 9. Move ChartFrame to components/ui
### 10. The Chart component
### 11. Surface draws a Chart, loaded on first use
### 12. CronReport draws the panel above Summary
### 13. Browser test: a cron run with a panel

(Each step's full detail is in the `steps` list submitted with this plan, identical in content.)

## Final verification
From `backend/`:
- `megoocolab-runner services run test -- uv run pytest tests/a2ui tests/crons tests/triggers tests/workflow tests/mcp -q -n auto`
- `megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"`
- `uvx ruff check --select E9,F app tests`

From `frontend/`:
- `npm test`, `npx tsc --noEmit`, `npx eslint src/components/a2ui src/components/crons src/components/ui src/components/sprint src/lib`
- `npm run build` (Recharts and the chart load lazily; the build passes)
- `megoocolab-runner services run e2e -- npx playwright test e2e/crons.spec.ts e2e/cards.spec.ts e2e/forms.spec.ts --reporter=line`

Every design requirement maps to a step: catalog `Chart` (2), panel validation and limits (3), guide (4), column/API/`last_run` null (5), tool + refusal stores nothing (6), last panel in prompt (7), methodology (8), colours (1), `ChartFrame` move (9), Chart look and table (10), lazy loading and fallback (11), page layout (12), browser test (13). Triggers, notifications and task opening are unchanged and covered by the existing tests in `tests/crons` and `tests/triggers`.
