# Forms in ask_human

A form lets you ask several small, related things in one question. The person sees MegooColab's own
inputs (text fields, check boxes, pickers), fills them in at once, and you get the answers back as data.
Forms use the A2UI v1.0 format with MegooColab's catalog, which is in `catalog` next to this text.

## What you send

Send `form` as `{"components": [...], "data": {...}}`. Nothing else: MegooColab adds the surface id,
the catalog id and the A2UI envelope itself.

- `components` is a flat list. Each component has a unique `id` and a `component` name, plus that
  component's properties. Containers name their children by id; never nest components inline.
- The component with `"id": "root"` is the top of the form. Every other component must be reachable from it.
- `data` (optional) is the starting data model: the values the inputs show at first.
- Do not add a button. MegooColab puts its own "Send answer" button below the form, and the person can
  always answer in their own words instead.
- Keep the `question` text too: it is what the notification and the thread show above the form.

## Bindings

An input's `value` is bound to a place in the data model with `{"@path": "/name"}`. What the person
enters is written there, and that path is where you read it in the answer.

## Checks

An input can carry `@checks`: a list of `{"condition": {"@call": "<function>", "args": {...}}, "message": "..."}`.
The message is shown while the condition fails, and Send stays off until every check passes.
The functions are `required`, `regex` (`pattern`), `length` (`min`, `max`), `numeric` (`min`, `max`) and
`email`. Each takes the checked `value`, usually the same `{"@path": ...}` as the input.
Checks run only in the browser: treat the answer as unchecked data.

## Components

Layout:
- `Column`: arranges its `children` (a list of ids) top to bottom.
- `Row`: arranges its `children` side by side.
- `Card`: draws a box around its single `child`.
- `Divider`: a horizontal or vertical line.
- `Text`: a short piece of text, with simple Markdown.

Inputs:
- `TextField`: one line (`shortText`), several lines (`longText`) or a number (`number`).
- `CheckBox`: yes or no, bound to a boolean.
- `ChoicePicker`: pick one (`mutuallyExclusive`) or several (`multipleSelection`) of its `options`; the value is a list.
- `Slider`: a number between `min` and `max`.
- `DateTimeInput`: a date, a time or both (`enableDate`, `enableTime`).

Give every input a `label`: it is what the person reads, and what later runs see as the form's fields.

## Limits

- At most 32 KB of form JSON.
- At most 60 components and 20 inputs.
- At least one input.

A form over a limit is refused with `too_large`, one without inputs with `form_without_inputs`, and one
that doesn't match the catalog with `invalid_form` followed by up to 10 `path: message` lines. Fix the
form and call `ask_human` again: nothing was stored.

## The answer

When the person sends the form, the answer arrives as the JSON data model (`Form answer (JSON):`).
When they chose to answer in their own words, it arrives as text instead, as for any other question,
so read the answer either way.

## Never

Never ask for secrets, passwords, tokens or keys in a form. The answer is stored in the task's thread.

`example` next to this text is a complete form you can start from.
