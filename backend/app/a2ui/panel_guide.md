# Panels in submit_cron_report

A panel shows a cron run's numbers as tiles and charts, drawn above the run's Summary on its page. It is
read-only and a snapshot: it never updates. Panels use the A2UI v1.0 format with MegooColab's catalog, which is in
`catalog` next to this text.

## When

Only when the job watches numbers that read better as tiles or a chart than as a sentence: counts, sizes,
durations, rates, a trend across runs. Summary, findings and checked must be complete without it.

## What you send

`submit_cron_report(..., panel)`, where `panel` is `{"components": [...], "data": {...}}`. MegooColab adds the
surface id, the catalog id and the envelope.

- `components` is a flat list. Each has a unique `id` and a `component` name; containers name children by id.
- The component with `"id": "root"` is the top. Every other component must be reachable from it.
- `data` (optional) is the data model that bound values read from (`{"@path": "/name"}`).

## Components

Layout:
- `Column`, `Row`: arrange their `children` top to bottom, or side by side.
- `Card`: a box around its single `child`.
- `Divider`: a line.
- `Text`: a short text with simple Markdown; Markdown links work.

Display:
- `Tabs`: up to 6 `tabs`, each `{title, child}`. The first is open.
- `List`: rows with a line between them. `children` is a list of ids, or a template
  `{"componentId": "<id>", "path": "/<array>"}` drawn once per item of that array, with paths inside the
  template relative to the item (`{"@path": "key"}`).
- `StatTile`: a `value` with its `label`, an optional `caption`, and a `tone`: `neutral`, `good`, `warning` or `bad`.
- `TaskLink`: a link to a task by its key (`task`, such as `MC-181`), followed by `label`. The label is your words,
  not the task's current title.
- `Chart`: a bar or line chart of numbers from `data`.
  - `kind`: `bar` for counts per label (the axis starts at zero), or `line` for a trend (the axis fits the data).
  - `title`: what the chart shows, such as "Failing tests by suite, last 14 runs".
  - `points`: a binding to a list of objects in `data`, one per label on the x axis: `{"@path": "/trend"}`.
  - `x`: the key of each point that holds its label (a day, a suite name), text or a number.
  - `series`: 1 to 4 `{key, label}`. `key` names the number in each point; `label` names the series in the
    legend and the table.
  - `unit` (optional): a short unit shown after values, such as `s`, `ms` or `%`.

  Series take the theme's chart colours in the order they are listed; never name a colour. A value that isn't a
  number is left out (a gap in a line), but every series needs at least one point with a number.

There are no inputs, buttons, images or media in a panel.

## Layout

Put the tiles in a `Row` first, then the charts in a `Row`: they sit side by side when there is room.

## A trend across runs

Your prompt carries the last panel of this cron, when there is one. Copy it, keep its layout, update the tiles,
append this run's point to each chart's list, and drop the oldest point once a list is past 50.

## Limits

- At most 16 KB of panel JSON and 60 components.
- At most 4 charts, 4 series in one chart, and 50 points in a chart (50 items in any array of `data`).
- At most 6 tabs in one `Tabs`.

Refusals: `invalid_panel` followed by up to 10 `path: message` lines (it doesn't match the catalog, a chart's data
is wrong, or a `TaskLink` whose literal `task` is not a task key), `panel_with_inputs`, `too_large`. The whole
report is refused and nothing was stored: fix the panel, or leave it out, and call `submit_cron_report` again.

`example` next to this text is a complete panel you can start from.
