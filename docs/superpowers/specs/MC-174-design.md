# MC-174: A2UI cron reports, an optional agent-built panel on a cron run

This design goes with mockup **v1** ("Cron panel v1: a run with a panel, without one, a panel that can't be drawn, and the agent's side").

## Goal

A cron that watches numbers can show them. `submit_cron_report` takes an optional `panel` (stat tiles and bar or line charts), and the run's page draws it above Summary, Findings and Checked. A run without a panel reads exactly as it does today.

## Decisions

| Decision | Chosen | Why, and what was rejected |
| --- | --- | --- |
| How a trend gets its history | **The last panel goes back to the agent** (your answer). The next run's prompt carries the newest earlier panel of the cron as `{components, data}`. | The agent keeps the layout, updates the tiles and adds one point to each series. Rejected: only the data (the layout would drift from run to run), nothing (no trend across runs), and MegooColab keeping named numbers itself (a different, bigger feature). |
| Series in one chart | **Up to four** (your answer). | Needs two new chart colours in the theme, checked in both themes. Rejected: one or two series with today's two colours. |
| Chart in thread cards | **Only in a cron panel** (your answer). | Cards keep exactly the components they have today. |
| Storage | **Its own column, `cron_runs.panel`** (your answer, approach A). | The report stays exactly the fixed fields, so triggers, notifications and `crons/report.py` never see the panel. Rejected: inside the report JSON (every reader would carry up to 16 KB more), and a separate tool call (two calls to keep in order, a panel without a report). |
| A panel that is refused | The whole `submit_cron_report` call is refused with the list of problems, and nothing is stored. | The panel is checked before any task is opened or comment written, so the agent can fix it, or leave it out, and call again. It matches how forms and cards are refused. |
| Which earlier panel is given back | The newest earlier run of the cron **that has a panel**, with that run's time. | A run that failed, was skipped, or sent no panel doesn't lose the series; it only leaves a gap. |
| What a panel may contain | The card's components plus `Chart`: `Column`, `Row`, `Card`, `Divider`, `Text`, `Tabs`, `List`, `StatTile`, `TaskLink`, `Chart`. | One read-only set, checked by the same code as a card. No inputs, buttons, images or media. |
| Colours | The agent never picks one. Series take `chart-1` to `chart-4` in the order they are listed. | A colour then always means "the nth series", and both themes stay readable. |
| Guide | A new tool `get_panel_guide`. | As with forms and cards, the catalog stays out of every session's tool descriptions. |
| Layout | Panel above Summary; charts side by side when there is room; each chart has a table view (approved with the mockup). | Rejected: Summary above the panel. |

## Architecture

### Step 1 settles four points in code

The A2UI packages aren't installed in the design checkout, so these could not be confirmed by reading. The first build step confirms them and records the result with `record_decision`.

1. `a2ui-core` 0.7.0 validates a catalog component whose property is a data binding to a list (`"points": {"@path": "/trend"}`) and one that holds a literal list of objects (`series`).
2. The React renderer (`@a2ui/react` 0.15.0) hands that binding to our component as the list of objects it points at.
3. A lazily loaded Recharts chart draws inside a surface, and `next build` passes.
4. The two new colours pass the dataviz palette validator (`validate_palette.js`, adjacent pairs) in both themes, against `#ffffff` and `#17191f`, in the order cyan, pink, violet, amber. Candidates: `--chart-3` `#6d28d9` light and `#a06bf0` dark; `--chart-4` `#b7791f` light and `#c98500` dark. The validator may move a shade, or replace amber with another hue if it can't pass next to violet. The count of four stays.

**If point 1 or 2 fails:** `points` becomes a plain path string (`"points": "/trend"`, the way a `List` template names its array), and the chart reads that array from the surface's data model itself. Nothing else in this design changes.

### Backend

- **`backend/app/a2ui/catalog.json`** gets one entry, `Chart`, also listed in `$defs.anyComponent.oneOf`:
  - `kind`: `bar` or `line`.
  - `title`: what the chart shows; its heading and accessible name.
  - `points`: a binding to a list of objects in `data`.
  - `x`: the key of each point that holds its label (a day, a suite name).
  - `series`: 1 to 4 of `{key, label}`; `key` names the number in each point.
  - `unit` (optional): a short unit shown after values, such as `s`, `ms` or `%`.
- **`backend/app/a2ui/service.py`**:
  - `PANEL_COMPONENTS` = `CARD_COMPONENTS` plus `Chart`. Forms and cards keep their sets, so both still refuse a `Chart`.
  - `clean_panel(panel)` takes `{components, data?}`, runs the checks a card gets (size, component count, no inputs, allowed set, tabs, task keys, array length), then the chart checks below, wraps it with a surface id `panel-<12 hex>` and validates it against the catalog. It raises `PanelError`, shaped like `CardError`. The card checks are shared with `clean_card`, not copied.
  - Chart checks, against the panel's own `data`: `points` is an absolute path to a list of 1 to 50 objects; every point has a text or number under `x`; under each series key every point has a number or nothing, and at least one point has a number; series keys differ from each other and from `x`; at most 4 charts in a panel.
  - `unwrap(message)` returns the `{components, data}` an agent writes, from a stored message.
  - `panel_guide()` returns its instructions, the catalog cut down to `PANEL_COMPONENTS`, and an example. New files `panel_guide.md` and `panel_example.json`.
- **`backend/app/crons/models.py`**: `CronRun.panel`, the stored `createSurface` message or null.
- **`backend/app/crons/report.py`**: `apply_report` takes `panel`. After the checks it makes today (the run is running, no report yet) and before any task or comment, it calls `clean_panel`. It stores the message in `cron_run.panel`. `cron_run.report` is built exactly as today.
- **`backend/app/mcp_server/cron_tools.py`**: `submit_cron_report` gets `panel: dict | None = None`, and `get_panel_guide()` is new.
- **`backend/app/crons/turns.py`**: `cron_prompt` adds a section "The last panel" after the last report: the time of the run it comes from and `unwrap(panel)` as JSON inside an untrusted block (`last panel`). It is left out when no earlier run has a panel.
- **`backend/app/crons/schemas.py` and `service.py`**: `CronRunOut.panel`. The runs list and the single run return it. A cron's `last_run` (the crons list and the cron itself) leaves it null, so the list doesn't carry panels nobody draws there.
- **Unchanged:** triggers (`triggers/events.py`), notifications (`tell_outcome`) and task opening read `report` only.
- **`methodology_texts/defaults/cron.md`**:
  - The tools list names `panel?` and `get_panel_guide()` (call it before the first panel).
  - A new part, "A panel", says when one is worth sending:
    - Send one only when the job watches numbers that read better as tiles or a chart than as a sentence: counts, sizes, durations, rates, a trend across runs.
    - Summary, findings and checked must be complete without it. Notifications, triggers and opened tasks carry only those.
    - Every number in it comes from a command of this run, or from the last panel for earlier points.
    - For a trend, start from the last panel in the prompt: keep its layout, update the tiles, add this run's point, and drop the oldest past 50.
    - If the panel is refused twice, send the report without it.

### Frontend

- **`app/globals.css`**: `--chart-3` and `--chart-4` in both themes. **`lib/useThemeColors.ts`** reads them.
- **`components/sprint/ChartFrame.tsx` moves to `components/ui/ChartFrame.tsx`**, since a third chart now uses it. It keeps its title, legend and "Show table" switch. The Velocity and Burndown charts import the new path.
- **`components/a2ui/Chart.tsx`** (new): the Recharts chart inside `ChartFrame`, in the style of the Velocity and Burndown charts.
  - Lines are 2 px with a dot on the last point; bars have a rounded top and are at most 24 px wide. No animation.
  - A bar chart's axis starts at zero. A line chart's axis fits its data.
  - A legend when there are two or more series; with one, the title names it.
  - A tooltip on hover, and the table view with the same numbers.
  - A value that isn't a number is left out (a gap in a line). With no list to draw, it shows "No data to draw." in the frame.
  - It is loaded on first use, so pages that only draw forms or cards don't load Recharts.
- **`components/a2ui/catalog.tsx`**: the `Chart` entry and its `COMPONENT_PROPS` names. **`Surface.tsx`** (still the only `@a2ui/*` importer) gets the chart's component API and draws it.
- **`components/crons/CronReport.tsx`**: when the run has a report and a panel, a `Panel` section above Summary draws `<Surface message={run.panel} readOnly fallback=… />`, with a line under it. The fallback is "This run's panel couldn't be drawn. The report below is complete without it."
- **`lib/api-types.ts`** is regenerated for `CronRunOut.panel`.

## Data and interfaces

- **Migration:** `cron_runs.panel` JSONB null.
- **MCP `submit_cron_report(summary, findings, checked?, nothing_new?, document_md?, panel?)`:** `panel` is `{components: [...], data?: {...}}`. The return value is unchanged.
- **MCP `get_panel_guide()`:** returns `{instructions_md, catalog, example}`.
- **`CronRunOut.panel`:** the stored message or null; always null inside a cron's `last_run`.
- **A chart in a panel:**

```json
{"id": "trend", "component": "Chart", "kind": "line", "title": "Failing tests by suite, last 14 runs",
 "points": {"@path": "/trend"}, "x": "day",
 "series": [{"key": "api", "label": "API"}, {"key": "web", "label": "Web"}]}
```

  with `"data": {"trend": [{"day": "Nov 23", "api": 3, "web": 1}, {"day": "Nov 24", "api": 2, "web": 1}]}`.
- **Limits:** 16 KB of panel JSON, 60 components, 4 charts, 4 series in a chart, 50 points in a chart (the limit on any array of `data`), 6 tabs in one `Tabs`.

## Error handling and edge cases

- **Doesn't match the catalog, or a chart's data is wrong:** `invalid_panel` with up to 10 `path: message` lines, for example `components.trend.series.2.key: no point of /trend has a number under "runer"`.
- **An input component:** `panel_with_inputs`. **Over a size limit:** `too_large`.
- **Any refusal stores nothing:** no report, no task, no comment. The run can still report. A run that never does ends as `no_report`, as today.
- **`already_submitted` and `run_not_running`** are answered before the panel is looked at, as today.
- **A `Chart` in a form or a card:** `invalid_form` or `invalid_card`.
- **The renderer or Recharts fails to load, or drawing throws:** the fallback line takes the panel's place, and Summary, Findings and Checked are complete below it.
- **While the renderer loads** the panel's place is empty and the fixed sections are already shown.
- **A run without a panel, and every run stored before this change:** drawn as today.
- **A failed or skipped run** has no report and so no panel. The next run still gets the newest earlier panel.
- **The last panel in the prompt** is data inside an untrusted block; it never carries instructions.
- **A panel doesn't change** what a run counts as: findings, "nothing new", notifications and triggers depend on the report only.
- **Deleting a cron** deletes its runs and their panels.

## Testing

- **Backend (pytest):**
  - Validation: a fixture file `panels.json` of valid and invalid panels, covering a line and a bar chart, each chart check, five series, five charts, an input, and each limit. Forms and cards refuse a `Chart`.
  - `apply_report`: a panel is stored and the report is unchanged; a refused panel stores nothing and opens no task; the same call without the panel then succeeds.
  - Tools: `submit_cron_report` with and without a panel; `get_panel_guide` lists exactly the panel components; the card and form guides are unchanged.
  - Prompt: the last panel section, taken from the newest earlier run that has one, and left out when none has.
  - API: `panel` on the runs list and on a single run; null in `last_run`.
  - Migration: down and up again.
- **Frontend (Vitest):**
  - `Surface` draws every valid panel fixture; a chart's table view lists its points; the fallback shows when drawing fails.
  - `catalog` parity with `catalog.json` for `Chart`.
  - `CronReport`: with a panel it comes before Summary; without one the output is as before.
  - The Velocity and Burndown charts still pass under the moved `ChartFrame`.
- **Browser (Playwright):** an agent reports a cron run with a panel; the run's page shows the tiles and both charts, and a chart switches to its table.

## Out of scope

- Charts in thread cards and in forms.
- Other chart kinds (pie, area, stacked bars), a second axis, and colours chosen by the agent.
- MegooColab keeping a history of named numbers, and comparing panels across runs.
- Panels in notifications, triggers, opened tasks, the Knowledge Base document of a `kb` cron, and exports.
- Editing or updating a panel after the report, and more than one panel in a run.
- A panel preview in the crons list or on the Dashboard.