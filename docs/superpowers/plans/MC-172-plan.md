# MC-172 implementation plan: A2UI foundation and form questions

## Goal
An agent can call `ask_human` with a form (A2UI v1.0 components drawn with MegooColab's own inputs). A person fills it in or answers in their own words. The agent gets the answer back as JSON data.

## Architecture
- **Backend.** `backend/app/a2ui/` holds MegooColab's catalog (`catalog.json`), the agent guide (`guide.md`, `example.json`) and `service.py`. `service.py` wraps what the agent sends into a `createSurface` message, validates it with `a2ui-core` plus our own limits, and lists field labels. `workflow/questions.py` stores the form on the question and the answer data. `workflow/context.py` gives both to the agent. `mcp_server/workflow_tools.py` adds `form` to `ask_human` and adds the new tool `get_form_guide`.
- **Frontend.** `src/components/a2ui/FormSurface.tsx` is the only file that imports `@a2ui/*`, and it loads them lazily. `src/components/a2ui/catalog.tsx` holds plain React components built from `components/ui`. `workflow/QuestionCard.tsx` draws a form question in place of the choice list, with MegooColab's own "Send answer" button and "Answer in your own words instead".
- **Spike first.** Steps 1 and 2 settle the open library points in code and record them with `record_decision`. If the frontend points fail, step 2 writes our own small renderer behind the same `FormSurface` interface. Nothing else changes.

## Conventions for every step
- Work on the current branch `megoo/MC-172-a2ui-integration`. One commit per step, using the subject given in the step. The body says why and what in plain sentences and ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- TDD: write the test, run it and watch it fail, implement, then run it again.
- Backend: `cd backend; megoocolab-runner services run test -- uv run pytest <files> -q`. Run the whole suite once before each commit with `megoocolab-runner services run test -- uv run pytest -q -n auto`. Never start two pytest runs at the same time. Lint with `uvx ruff check --select E9,F app tests`.
- Frontend: `cd frontend; npx tsc --noEmit; npx eslint <changed files>; npm test`. Don't run Prettier.
- `frontend/src/lib/api-types.ts` is regenerated (`cd frontend; npm run gen:api`) **only in step 10**. That is the step whose code sends the new `data` field.
- Dependencies are pinned exactly: `a2ui-core==0.7.0` (and `a2ui-agent-sdk==0.12.0` only if step 1 shows it is needed), and `@a2ui/react` 0.15.0, `@a2ui/web_core` 0.15.0 and `zod` (the version their peer range asks for, written without `^`).
- Error codes are the REST `detail` strings. Over MCP, `tool_session` turns an `HTTPException` detail into the tool error text.

## File map
| File | Status | Responsibility |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | modify | `a2ui-core==0.7.0` |
| `backend/app/a2ui/__init__.py` | create | package |
| `backend/app/a2ui/catalog.json` | create | catalog `urn:megoocolab:a2ui:catalog:v1`, protocol 1.0 |
| `backend/app/a2ui/guide.md` | create | instructions for agents |
| `backend/app/a2ui/example.json` | create | the example form `{components, data}` |
| `backend/app/a2ui/service.py` | create | `wrap`, `validate`, `field_labels`, `guide`, `clean_answer_data`, `FormError`, the limits |
| `backend/app/core/text.py` | modify | `strip_nul_deep` |
| `backend/app/workflow/models.py` | modify | `WorkflowQuestion.form`, `.answer_data` |
| `backend/migrations/versions/<rev>_question_forms.py` | create | two JSONB null columns |
| `backend/app/workflow/questions.py` | modify | `ask(form=)`, `answer(data=)`, `deliver` payload |
| `backend/app/workflow/router.py` | modify | `AnswerIn.data` |
| `backend/app/workflow/context.py` | modify | resume text, `_question_text` |
| `backend/app/tasks/activity.py` | modify | question item `form`, `answer_data` |
| `backend/app/mcp_server/workflow_tools.py` | modify | `ask_human(form=)`, `get_form_guide` |
| `backend/app/workflow/methodology_texts/defaults/*.md` (10 files), `methodology_history.py` | modify | the form rule and new hashes |
| `backend/tests/a2ui/__init__.py`, `test_catalog.py`, `test_service.py`, `fixtures/forms.json` | create | validation tests, shared fixtures |
| `backend/tests/workflow/test_question_forms.py`, `test_question_forms_migration.py` | create | ask, answer, agent text, activity, migration |
| `backend/tests/mcp/test_workflow_tools.py`, `backend/tests/mcp/test_mcp.py` | modify | tool tests, tool list |
| `frontend/package.json`, `package-lock.json` | modify | A2UI packages |
| `frontend/src/components/a2ui/FormSurface.tsx` | create | lazy renderer; the only `@a2ui/*` importer |
| `frontend/src/components/a2ui/catalog.tsx` | create | our React component per catalog entry, `CATALOG_ID`, `COMPONENT_PROPS` |
| `frontend/src/components/a2ui/__tests__/FormSurface.test.tsx`, `catalog.test.ts` | create | rendering, validity, read-only, parity |
| `frontend/src/lib/types.ts` | modify | `FormMessage`, `FormValues`, `ActivityQuestion.form/answer_data` |
| `frontend/src/components/workflow/QuestionCard.tsx` and its test | modify | form mode |
| `frontend/src/lib/api-types.ts` | regenerate | `AnswerIn.data` |
| `frontend/e2e/forms.spec.ts` | create | browser test |

## Shared contracts

### Stored message (what `service.wrap` returns and `workflow_questions.form` holds)
```json
{"version": "1.0",
 "createSurface": {"surfaceId": "form-<12 hex>", "catalogId": "urn:megoocolab:a2ui:catalog:v1",
                   "components": [ ... ], "dataModel": { ... }}}
```
`dataModel` is `data`, or `{}` when it is absent. `surfaceId` is `"form-" + uuid4().hex[:12]`, so two cards on one page never share an id.

### `backend/app/a2ui/service.py`
```python
CATALOG_ID = "urn:megoocolab:a2ui:catalog:v1"
INPUTS = frozenset({"TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"})
MAX_FORM_BYTES = 32 * 1024        # json.dumps(form, separators=(",", ":"), ensure_ascii=False).encode()
MAX_COMPONENTS = 60
MAX_INPUTS = 20
MAX_PROBLEMS = 10
MAX_ANSWER_DATA_BYTES = 16 * 1024

class FormError(HTTPException):
    """422 whose detail is the code, then up to MAX_PROBLEMS "path: message" lines."""
    def __init__(self, code: str, problems: Sequence[dict] = ()):
        self.code = code
        self.problems = [{"path": str(p["path"]), "message": str(p["message"])} for p in problems][:MAX_PROBLEMS]
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT,
                         "\n".join([code, *(f"{p['path']}: {p['message']}" for p in self.problems)]))

def wrap(components: list, data: dict | None) -> dict: ...
def clean_form(form: Any) -> dict:          # agent's {components, data?} -> validated stored message
def validate(message: dict) -> None: ...    # library + our limits; raises FormError
def field_labels(message: dict | None) -> list[str]: ...
def guide() -> dict: ...                    # {"instructions_md", "catalog", "example"}
def clean_answer_data(data: dict) -> dict:  # strip_nul_deep, then 16 KB -> HTTPException 422 "too_large"
```
`clean_form` does the checks in this order:
1. `form` is a dict whose keys are only `components` (a list of dicts) and `data` (a dict, optional). Anything else is `FormError("invalid_form", [{"path": "form", "message": ...}])`.
2. `strip_nul_deep`.
3. Size over `MAX_FORM_BYTES` is `too_large`.
4. More than `MAX_COMPONENTS` components, or more than `MAX_INPUTS` with `component` in `INPUTS`, is `too_large`. Zero inputs is `form_without_inputs`.
5. `wrap`, then `validate`. A library error is `invalid_form` with the library's paths and messages.

`field_labels` returns, in component order, the `label` of each input when it is a non-blank string, and the component `id` otherwise.

### The example form (`backend/app/a2ui/example.json`; also the first valid fixture)
```json
{
  "components": [
    {"id": "root", "component": "Column", "children": ["intro", "name", "due", "kind", "notify"]},
    {"id": "intro", "component": "Text", "text": "A few details about the release."},
    {"id": "name", "component": "TextField", "label": "Release name", "value": {"@path": "/name"},
     "variant": "shortText",
     "checks": [{"condition": {"@call": "required", "args": {"value": {"@path": "/name"}}},
                 "message": "A name is needed"}]},
    {"id": "due", "component": "DateTimeInput", "label": "Due date", "value": {"@path": "/due"},
     "enableDate": true, "enableTime": false},
    {"id": "kind", "component": "ChoicePicker", "label": "Kind", "variant": "mutuallyExclusive",
     "options": [{"label": "Patch", "value": "patch"}, {"label": "Minor", "value": "minor"}],
     "value": {"@path": "/kind"}},
    {"id": "notify", "component": "CheckBox", "label": "Tell the team", "value": {"@path": "/notify"}}
  ],
  "data": {"name": "", "due": "", "kind": ["patch"], "notify": true}
}
```
If the pinned library names a property differently (step 1 finds this out), the example and fixtures follow the library. That is recorded with `record_decision`. It is not a design change.

### `backend/tests/a2ui/fixtures/forms.json`
```json
{"valid":   [{"name": "example", "form": {...}}, {"name": "every-input", "form": {...}}, ...],
 "invalid": [{"name": "unknown-component", "form": {...}, "code": "invalid_form", "path_contains": "components"},
             {"name": "dangling-id", ...}, {"name": "missing-root", ...}, {"name": "obscured-variant", ...},
             {"name": "button", ...}, {"name": "image", ...}, {"name": "no-inputs", "code": "form_without_inputs"},
             {"name": "extra-key", "code": "invalid_form"}]}
```
The `every-input` form uses each of the 10 catalog components at least once: the TextField variants `shortText`, `longText` and `number`, ChoicePicker with one and with many, a Slider, and a DateTimeInput with date and time. It also uses each check function (`required`, `regex`, `length`, `numeric`, `email`). The limit cases (32 KB, 61 components, 21 inputs) are built in test code from the `example` form, because the file would otherwise hold kilobytes of filler. Frontend tests read this file with `readFileSync(join(process.cwd(), "..", "backend", "tests", "a2ui", "fixtures", "forms.json"))`.

### Answers
- `AnswerIn` gets `data: dict[str, Any] | None = None`.
- `questions.answer(db, user, task, question_id, choice, text, images=(), data=None)`. The rules, after the question row is loaded:
  - `choice`, `text` and `data` all empty: `empty_answer` (checked before loading, as today, with `data is None` added).
  - `data` on a question without `form`: `no_form`.
  - `choice` on a form question: `unknown_choice`.
  - `data` together with `text` or images: `invalid_answer`.
  - `data` over 16 KB once serialised: `too_large`.
  - The stored `answer_data` is `strip_nul_deep(data)`.
- The `deliver` payload is `{"choice_label", "text", "data": q.answer_data}`.
- `resume_text("answer", p)` adds the part `"Form answer (JSON):\n" + json.dumps(p["data"], ensure_ascii=False, indent=2)` when `p.get("data") is not None`. It stays inside the `answer` untrusted block.
- `_question_text` adds `"Form fields: " + ", ".join(field_labels(form))` after the body, and `"Form answer (JSON): " + json.dumps(answer_data, ensure_ascii=False, sort_keys=True)` once answered with data.

### Frontend types (`src/lib/types.ts`)
```ts
export type FormValues = Record<string, unknown>;
export type FormMessage = {
  version: "1.0";
  createSurface: { surfaceId: string; catalogId: string; components: Record<string, unknown>[]; dataModel?: FormValues };
};
// ActivityQuestion gains:
  form: FormMessage | null;
  answer_data: FormValues | null;
```

### `FormSurface`
```tsx
export function FormSurface(props: {
  message: FormMessage;
  readOnly?: boolean;                                   // default false
  onChange?: (data: FormValues, valid: boolean) => void; // once after first draw, then on every change
}): JSX.Element
```
- It loads `@a2ui/react` and `@a2ui/web_core` on first use, cached in a module-level promise, as `MermaidDiagram` does.
- `data` is the surface's whole data model.
- `valid` is false while any check fails.
- If the load fails or the renderer throws (an error boundary), it shows `<p role="alert">This form couldn't be shown. You can still answer in your own words.</p>` and never calls `onChange(…, true)`.

### `catalog.tsx`
- `export const CATALOG_ID = "urn:megoocolab:a2ui:catalog:v1"`.
- `export const COMPONENT_PROPS: Record<string, readonly string[]>`: component name to its property names, equal to `catalog.json` (the parity test).
- One plain React component per catalog entry. It never imports `@a2ui/*`. Inputs take `FieldProps<V> = { id: string; label?: string; value: V; onChange: (v: V) => void; readOnly: boolean; error?: string }` plus their own options. `FormSurface` adapts them to the renderer inside its lazy import.
- `Text` renders through `<Markdown compact>`.
- Inputs are built from `Input`, `Textarea` and `Select` in `components/ui`, and the theme's classes (`border-line`, `bg-surface-2`, `focus:border-cyan`, `text-pink` for the message).
- A check message shows once the field was changed or blurred. Read-only inputs get the `disabled` attribute and show no message.

### Methodology rule (added to each of the 10 default texts that list `ask_human`)
Tool line: `` `ask_human(key, question, choices?, mockup_html?, mockup_title?, mockup_choices?, form?)` ``. In `freestyle.md`: `` `ask_human(key, question, choices?, form?)` ``. New tool line:
> - `get_form_guide()`: the components a form may use, with an example. Call it before you send your first `form`.

New paragraph, placed right after the tool list:
> **Forms.** When you need several small inputs on one topic and none of them depends on another's answer, ask them in one `ask_human` call with a `form` (`{components, data?}`; see `get_form_guide`). The person fills them in at once and you get the answers back as JSON. Otherwise ask one question. A form replaces `choices` and `mockup_choices`: never send both. The person may still answer in their own words instead, so read the answer either way.

In `brainstorm.md`, step 3 reads "Each `ask_human` call carries exactly one question, or one form." The hard rule reads "One question per `ask_human` call. Never batch several questions into one, except as a form (see **Forms**)."

## Steps

### 1. Spike (backend): a2ui-core validates against MegooColab's catalog
See the step detail.

### 2. Spike (frontend): the A2UI React renderer draws our own components in the App Router
See the step detail.

### 3. Backend form service: wrap, validate with our limits, field labels, the agent guide

### 4. Questions store a form and its answer data (migration)

### 5. ask_human takes a form, and get_form_guide gives agents the catalog

### 6. A person answers a form question with data, and the agent gets it as JSON

### 7. The thread item and later prompts show the form and its answer

### 8. Methodology texts teach agents when to use a form

### 9. Frontend catalog: every component, read-only mode, failure state, parity with the backend

### 10. QuestionCard draws a form question, sends its data, and shows it answered

### 11. Browser test: an agent asks a form question, a person fills it in and sends it

(The full detail of each step is in the `steps` array. The titles above match it one to one.)

## Final verification
```bash
cd backend
megoocolab-runner services run test -- uv run pytest -q -n auto
megoocolab-runner services run migrate -- bash -c "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"
uvx ruff check --select E9,F app tests
cd ../frontend
npx tsc --noEmit
npx eslint src/components/a2ui src/components/workflow/QuestionCard.tsx src/lib/types.ts e2e/forms.spec.ts
npm test
npm run build
megoocolab-runner services run e2e -- npx playwright test --reporter=line
```
Requirements map:
- catalog: step 1
- validation and limits: step 3
- the migration and model: step 4
- `ask_human` form, `get_form_guide` and `form_with_choices`: step 5
- answer data and the 422s: step 6
- resume text, `_question_text` and the activity item: steps 6 and 7
- methodology texts: step 8
- `FormSurface`, the catalog and parity: steps 2 and 9
- QuestionCard states: step 10
- the browser test: step 11
- notifications and Telegram: unchanged by design, so no step
