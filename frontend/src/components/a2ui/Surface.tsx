"use client";

import type { ReactCatalogComponent } from "@a2ui/react";
import {
  Component,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";

import type { FormValues, SurfaceMessage } from "@/lib/types";

import {
  CATALOG_ID,
  Card,
  CheckBox,
  ChoicePicker,
  Column,
  DateTimeInput,
  Divider,
  List,
  Row,
  Slider,
  StatTile,
  Tabs,
  TaskLink,
  Text,
  TextField,
} from "./catalog";

const FAILED = "This form couldn't be shown. You can still answer in your own words.";

/** The input components of the catalog: each reports whether its checks pass. */
const INPUTS = new Set(["TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"]);

/** What the adapters read from the surface they are drawn in. */
type Form = { surfaceId: string; readOnly: boolean; report: (id: string, path: string, valid: boolean | null) => void };
const FormContext = createContext<Form>({ surfaceId: "", readOnly: true, report: () => {} });

/** Reports an input's check result to its form while the input is drawn (null once it is gone). */
function useReport(id: string, path: string, valid: boolean) {
  const { report } = useContext(FormContext);
  useEffect(() => {
    report(id, path, valid);
    return () => report(id, path, null);
  }, [report, id, path, valid]);
}

/** What an input adapter needs: its element id, whether the form is read-only, and its check result reported. */
function useField(
  context: { componentModel: { id: string }; dataContext: { path: string } },
  props: { isValid?: boolean; validationErrors?: string[] },
) {
  const { surfaceId, readOnly } = useContext(FormContext);
  const id = context.componentModel.id;
  useReport(id, context.dataContext.path, props.isValid !== false);
  return { id: `${surfaceId}-${id}`, readOnly, error: props.validationErrors?.[0] };
}

async function loadRenderer() {
  const [react, core, { z }] = await Promise.all([
    import("@a2ui/react"),
    import("@a2ui/web_core/v1_0"),
    import("zod"),
  ]);
  const { createComponentImplementation: implement } = react;
  type Children = (string | { id: string; basePath: string })[] | undefined;
  const children = (list: Children, buildChild: (id: string, basePath?: string) => ReactNode) =>
    list?.map((c) => (typeof c === "string" ? buildChild(c) : buildChild(c.id, c.basePath)));

  // our own two components' APIs, as catalog.json defines them
  const S = core.CommonSchemas;
  const StatTileApi = {
    name: "StatTile",
    schema: z.object({
      label: S.DynamicString,
      value: S.DynamicString,
      caption: S.DynamicString.optional(),
      tone: z.enum(["neutral", "good", "warning", "bad"]).optional(),
      weight: z.number().optional(),
    }),
  };
  const TaskLinkApi = {
    name: "TaskLink",
    schema: z.object({ task: S.DynamicString, label: S.DynamicString.optional(), weight: z.number().optional() }),
  };

  // our components, under the v1.0 basic catalog's component APIs: no basic catalog element is ever drawn
  const components = [
    implement(core.ColumnApi, ({ props, buildChild }) => <Column>{children(props.children, buildChild)}</Column>),
    implement(core.RowApi, ({ props, buildChild }) => <Row>{children(props.children, buildChild)}</Row>),
    implement(core.CardApi, ({ props, buildChild }) => <Card>{buildChild(props.child)}</Card>),
    implement(core.DividerApi, () => <Divider />),
    implement(core.TextApi, ({ props }) => <Text text={props.text ?? ""} />),
    implement(core.TabsApi, function TabsView({ props, buildChild, context }) {
      const { surfaceId } = useContext(FormContext);
      return (
        <Tabs
          id={`${surfaceId}-${context.componentModel.id}`}
          tabs={(props.tabs ?? []).map((t) => ({ title: String(t.title ?? ""), panel: buildChild(t.child) }))}
        />
      );
    }),
    implement(core.ListApi, ({ props, buildChild }) => <List items={children(props.children, buildChild) ?? []} />),
    implement(StatTileApi, ({ props }) => (
      <StatTile
        label={String(props.label ?? "")}
        value={String(props.value ?? "")}
        caption={props.caption == null ? undefined : String(props.caption)}
        tone={props.tone}
      />
    )),
    implement(TaskLinkApi, ({ props }) => (
      <TaskLink task={String(props.task ?? "")} label={props.label == null ? undefined : String(props.label)} />
    )),
    implement(core.TextFieldApi, function TextFieldView({ props, context }) {
      const field = useField(context, props);
      return (
        <TextField
          {...field}
          label={props.label}
          // a number field's value may arrive as a number from the data model
          value={props.value == null ? "" : String(props.value)}
          onChange={props.setValue}
          variant={props.variant === "obscured" ? "shortText" : props.variant}
          placeholder={props.placeholder}
        />
      );
    }),
    implement(core.CheckBoxApi, function CheckBoxView({ props, context }) {
      const field = useField(context, props);
      return <CheckBox {...field} label={props.label} value={props.value === true} onChange={props.setValue} />;
    }),
    implement(core.ChoicePickerApi, function ChoicePickerView({ props, context }) {
      const field = useField(context, props);
      const value: unknown = props.value;
      return (
        <ChoicePicker
          {...field}
          label={props.label}
          value={Array.isArray(value) ? value.map(String) : typeof value === "string" ? [value] : []}
          onChange={props.setValue}
          options={(props.options ?? []).map((o) => ({ label: String(o.label ?? o.value), value: o.value }))}
          multiple={props.variant === "multipleSelection"}
          chips={props.displayStyle === "chips"}
        />
      );
    }),
    implement(core.SliderApi, function SliderView({ props, context }) {
      const field = useField(context, props);
      const min = props.min ?? 0;
      return (
        <Slider
          {...field}
          label={props.label}
          value={typeof props.value === "number" ? props.value : min}
          onChange={props.setValue}
          min={min}
          max={props.max}
          steps={props.steps}
        />
      );
    }),
    implement(core.DateTimeInputApi, function DateTimeInputView({ props, context }) {
      const field = useField(context, props);
      return (
        <DateTimeInput
          {...field}
          label={props.label}
          value={typeof props.value === "string" ? props.value : ""}
          onChange={props.setValue}
          enableDate={props.enableDate}
          enableTime={props.enableTime}
          min={typeof props.min === "string" ? props.min : undefined}
          max={typeof props.max === "string" ? props.max : undefined}
        />
      );
    }),
  ];
  const catalog = new core.Catalog(CATALOG_ID, "1.0", components, core.V10_VALIDATION_FUNCTION_IMPLEMENTATIONS);
  return { A2uiSurface: react.A2uiSurface, MessageProcessor: core.MessageProcessor, catalog };
}

type Renderer = Awaited<ReturnType<typeof loadRenderer>>;
let loading: Promise<Renderer> | null = null;
// the renderer is large: it loads the first time a page has a form, and again on the next form if that failed
const load = () =>
  (loading ??= loadRenderer().catch((e: unknown) => {
    loading = null;
    throw e;
  }));

/** Catches what the renderer or one of our components throws while drawing. */
class Boundary extends Component<{ children: ReactNode; fallback: ReactNode; onError: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    return this.state.failed ? (this.props.fallback ?? <Failed />) : this.props.children;
  }
}

function Failed() {
  return <p role="alert" className="text-sm text-muted-foreground">{FAILED}</p>;
}

type SurfaceModel = ComponentProps<Renderer["A2uiSurface"]>["surface"];
type Drawn = { A2uiSurface: Renderer["A2uiSurface"]; surface: SurfaceModel; report: Form["report"] };

/** a2ui-core (the backend's validator) writes a component's checks as "@checks", web_core reads "checks" */
function forRenderer(message: SurfaceMessage) {
  const components = message.createSurface.components.map(({ "@checks": checks, ...rest }) =>
    checks === undefined ? rest : { ...rest, checks },
  );
  return { ...message, createSurface: { ...message.createSurface, components } };
}

/** An A2UI surface drawn with MegooColab's own components: a question's form or a thread's card. `onChange` gets the
 * surface's whole data model and whether every check passes: once all inputs are drawn, then on every change.
 * `fallback` is shown in place of the surface when it can't be drawn (a form's failure message by default). */
export function Surface({
  message,
  readOnly = false,
  onChange,
  fallback,
}: {
  message: SurfaceMessage;
  readOnly?: boolean;
  onChange?: (data: FormValues, valid: boolean) => void;
  fallback?: ReactNode;
}) {
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  // a failed form never reports: the person can only answer in their own words
  const [failed, setFailed] = useState(false);
  const failedRef = useRef(false);
  const fail = () => {
    failedRef.current = true;
    setFailed(true);
  };
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  // a refetched question brings an equal message: keep the surface, and what the person typed into it
  const source = JSON.stringify(message);

  useEffect(() => {
    const message = JSON.parse(source) as SurfaceMessage;
    let live = true;
    let dispose = () => {};
    load().then(({ A2uiSurface, MessageProcessor, catalog }) => {
      if (!live) return;
      const processor = new MessageProcessor<ReactCatalogComponent>([catalog], undefined, { version: "1.0" });
      processor.processMessages([forRenderer(message)]);
      const surface = processor.model.getSurface(message.createSurface.surfaceId)!;

      // every input of the message must report before the form says whether it is valid
      const inputs = message.createSurface.components.filter((c) => INPUTS.has(String(c.component))).map((c) => String(c.id));
      const results = new Map<string, Map<string, boolean>>(); // component id -> data path -> its checks pass
      let queued = false;
      const emit = () => {
        if (queued) return;
        queued = true;
        queueMicrotask(() => {
          queued = false;
          if (!live || failedRef.current || inputs.some((id) => !results.get(id)?.size)) return;
          const valid = [...results.values()].every((paths) => [...paths.values()].every(Boolean));
          onChangeRef.current?.(structuredClone(surface.dataModel.get("/") ?? {}) as FormValues, valid);
        });
      };
      const report = (id: string, path: string, valid: boolean | null) => {
        const paths = results.get(id) ?? new Map<string, boolean>();
        if (valid === null) paths.delete(path);
        else paths.set(path, valid);
        results.set(id, paths);
        emit();
      };
      const subscription = surface.dataModel.subscribe("/", emit);
      dispose = () => {
        subscription.unsubscribe();
        processor.dispose();
      };
      setDrawn({ A2uiSurface, surface, report });
      if (inputs.length === 0) emit();
    }).catch(() => {
      if (!live) return;
      failedRef.current = true;
      setFailed(true);
    });
    return () => {
      live = false;
      dispose();
    };
  }, [source]);

  const form = useMemo(
    () => drawn && { surfaceId: drawn.surface.id, readOnly, report: drawn.report },
    [drawn, readOnly],
  );
  if (failed) return fallback ?? <Failed />;
  if (!drawn || !form) return null;
  const { A2uiSurface, surface } = drawn;
  return (
    <Boundary fallback={fallback} onError={fail}>
      <FormContext.Provider value={form}>
        <A2uiSurface surface={surface} />
      </FormContext.Provider>
    </Boundary>
  );
}
