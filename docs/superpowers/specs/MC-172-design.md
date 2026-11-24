# MC-172 — A2UI integration: foundation and form questions

## Goal

An agent can ask several related things in one question as a form, drawn with MegooColab's own inputs, and gets the answer back as data. Today each of those things is its own question, and each costs a stop, a wait for a person and a session resume.

This task also builds the A2UI foundation (catalog, validation, renderer) that two follow-up tasks reuse for rich replies and cron reports.

## Evaluation: is A2UI worth having?

Yes, in a narrow way. The findings behind that:

- **What fits.** A2UI describes UI as data, and the app draws it with components from a fixed catalog. That lets agent-made UI appear inside the page, in our theme, with no iframe and no agent code running.
- **What doesn't apply.** MegooColab doesn't call the model: agents are Claude Code and Codex, reached through MCP tools. A2UI's agent SDK, its streaming and its A2A and AG-UI transports go unused. We use the v1.0 JSON format as an MCP tool argument, the Python validator, and the React renderer.
- **It doesn't replace HTML mockups.** A mockup shows any screen of the product being designed. A catalog draws only its own components.
- **Benefit by area.** Form questions: high. Cron reports: medium. Rich replies: low, because Markdown already covers most of it.
- **Costs.** The packages are 0.x and change often (four `@a2ui/react` minors in five weeks). The frontend packages bring Lit, zod, Preact signals, markdown-it and DOMPurify.

## Decisions

| Decision | Chosen | Why, and what was rejected |
| --- | --- | --- |
| Areas | All three: form questions, rich replies, cron reports | The owner's answer. |
| Split | This task: foundation and form questions. Follow-ups: rich replies, cron reports | The owner's choice. One design for all three was rejected: a foundation problem would be found late. |
| Packages | Official A2UI packages on both sides, with our own catalog | The owner's choice. Rejected: our own renderer with the official validator (kept as the fallback), and no A2UI packages at all. |
| Send button | MegooColab's own button, outside the surface | The owner approved. An agent can't label or trigger a send. The catalog has no Button in this phase. |
| Own words | "Answer in your own words instead" is always offered | The owner approved. A form can miss the point. |
| Form or choices | A question has choices or a form, never both. An HTML mockup may still come with a form | The owner approved. A form has its own choice picker. |
| Catalog in the agent's context | A new tool `get_form_guide` returns it on demand | Putting it in the `ask_human` description would cost every session thousands of tokens. |
| What the agent writes | Only `components` and `data`. MegooColab adds the surface envelope and the catalog id | Fewer things for the agent to get wrong. What we store is still a standard A2UI v1.0 `createSurface` message. |
| Notifications | Unchanged | They already say only "the agent has a question for you" with a link. The question text stays required. |

## Architecture

### Step 1 is a spike

Four points could not be settled by reading, so the build starts by settling them in code. The result is recorded with `record_decision`.

1. A lazily loaded client component draws a stored surface in the Next.js App Router, and `next build` passes.
2. A catalog made only of our components works, with no built-in Lit components and without `injectBasicCatalogStyles()`.
3. `@checks` reaches our input components as validity and a message.
4. The surface's whole data model can be read when the person sends.

On the backend the spike confirms that a payload validates against our catalog file with structured errors, and whether `a2ui-core` is enough or `a2ui-agent-sdk` is needed for it.

**If the frontend points fail:** we write our own small renderer inside the same module, with the same interface (the hybrid option). Nothing else in this design changes.

### Backend: `backend/app/a2ui/` (new)

- `catalog.json`: MegooColab's catalog, `protocolVersion` "1.0", id `urn:megoocolab:a2ui:catalog:v1`. Component names and properties follow A2UI's basic catalog, cut down to what we allow.
- `service.py`:
  - `wrap(components, data)` builds the `createSurface` message.
  - `validate(message)` runs the A2UI validator against the catalog, then our own limits. It raises with a list of `{path, message}`.
  - `guide()` returns the catalog, its instructions and one example.

**Catalog, version 1:**

| Kind | Components |
| --- | --- |
| Layout | `Column`, `Row`, `Card`, `Divider`, `Text` |
| Inputs | `TextField` (`shortText`, `longText`, `number`), `CheckBox`, `ChoicePicker`, `Slider`, `DateTimeInput` |
| Check functions | `required`, `regex`, `length`, `numeric`, `email` |

Left out on purpose: `Button`, `Image`, `Icon`, `Video`, `AudioPlayer`, `Modal`, `Tabs`, `List`, `openUrl`, the formatting functions, and `TextField`'s `obscured` variant (secrets don't belong in an answer).

### Backend: questions

- `workflow/models.py`: `WorkflowQuestion` gets `form` (the stored message) and `answer_data`.
- `workflow/questions.py`:
  - `ask()` takes an optional form, wraps and validates it, and stores it.
  - `answer()` takes optional `data`.
  - `deliver()` passes the data to the agent.
- `workflow/context.py`:
  - `resume_text("answer", …)` prints `Form answer (JSON):` and the data, inside the untrusted block.
  - `_question_text` adds the form's field labels and the form answer, so later runs and connect-only agents see them.
- `tasks/activity.py`: the question item carries `form` and `answer_data`.
- `mcp_server/workflow_tools.py`: `ask_human` gets `form`, and `get_form_guide` is new.
- Methodology defaults that describe `ask_human` (brainstorm, freestyle and the others that list it) get the new argument and one rule: use a form for several small inputs on one topic where none depends on another's answer; otherwise ask one question.

### Frontend: `frontend/src/components/a2ui/` (new)

- `FormSurface.tsx`: the only file that imports the A2UI packages. It loads them on first use, as `MermaidDiagram` loads Mermaid. Interface: `<FormSurface message readOnly onChange={(data, valid) => …} />`.
- `catalog.tsx`: one React component per catalog entry, built from `components/ui` and the theme's colours.
  - `Text` goes through our `Markdown` component, so raw HTML is never drawn and remote images stay links.
  - Inputs honour `readOnly` and show their check message.
- `workflow/QuestionCard.tsx`, when the question has a form:
  - It draws `FormSurface` in place of the choice list, with "Answer in your own words instead" and "Send answer" below it.
  - Send stays off while a check fails.
  - Once answered, the form is drawn read-only with the sent values, or the text when the person used their own words.

The mockup (v2) shows all four states.

## Data and interfaces

- **Migration:** `workflow_questions.form` JSONB null, `workflow_questions.answer_data` JSONB null.
- **MCP `ask_human(key, question, choices?, mockup_html?, mockup_title?, mockup_choices?, form?)`:** `form` is `{components: [...], data?: {...}}`.
- **MCP `get_form_guide()`:** returns `{instructions_md, catalog, example}`.
- **`POST /api/tasks/{key}/questions/{id}/answer`:** the body gets `data: object | null`.
  - On a form question: `data` or `text` (with images).
  - On any other question: `choice` or `text`, as today.
- **Activity item `question`:** adds `form` and `answer_data`. `api-types.ts` is regenerated.
- **Resume payload for `answer`:** adds `data`.
- **Dependencies, pinned exactly:** `@a2ui/react` 0.15.0, `@a2ui/web_core` 0.15.0 and `zod` (their peer) in the frontend. `a2ui-core` 0.7.0 in the backend, plus `a2ui-agent-sdk` 0.12.0 only if the spike shows the validator needs it.

## Error handling and edge cases

- **Invalid form:** the tool refuses with `invalid_form` and up to 10 `path: message` lines, so the agent can correct it and call again. Nothing is stored.
- **Form with `choices` or `mockup_choices`:** `form_with_choices`.
- **Limits:** at most 32 KB of form JSON, 60 components and 20 inputs, and at least one input (`form_without_inputs`). Over a limit: `too_large`.
- **Answers:**
  - `data` on a question without a form: 422 `no_form`.
  - `choice` on a form question: 422 `unknown_choice`.
  - `data` must be a JSON object of at most 16 KB.
  - Checks run in the browser only. The data comes from a person who may answer, and the agent receives it as untrusted data either way.
- **The renderer fails to load or throws:** the card says the form couldn't be shown, and the person can still answer in their own words.
- **Withdrawn question:** dimmed as today, with the form read-only.
- **A person who can't answer, or a read-only view:** the form is read-only.
- **A text answer on a form question:** `answer_data` stays null and the agent gets the text, as today.

## Testing

- **Backend (pytest):**
  - Validation: a shared fixture file of valid and invalid forms, covering an unknown component, a dangling id, a missing root, a left-out variant, and each limit.
  - Asking: `ask` with a form, and `form_with_choices`.
  - Answering: with data, with text, and each 422.
  - Agent text: the resume text, `_question_text`, and the activity item.
  - Tools: `get_form_guide` returns every catalog component.
  - Migration: down and up again.
- **Frontend (Vitest):**
  - `FormSurface` draws every fixture form, reports data and validity, and honours `readOnly`.
  - `QuestionCard`: Send is off while a check fails; sending data; switching to own words and back; the answered state; the renderer-failed state.
  - Parity: the frontend catalog has the same component and property names as `backend/app/a2ui/catalog.json`.
- **Browser (Playwright):** an agent asks a form question, a person fills it and sends it, and the thread shows it read-only.

## Out of scope

- Rich replies and cron reports: the two follow-up tasks below.
- Replacing HTML mockups.
- Streaming or updating a surface after it was sent, several surfaces in one question, and A2UI's remote function calls.
- Answering a form from Telegram.
- Images with a form answer (they stay with the own-words answer).
- Checking the form's rules again on the server.