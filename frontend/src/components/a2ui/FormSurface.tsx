"use client";

import type { ReactCatalogComponent } from "@a2ui/react";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ComponentProps } from "react";

import type { FormMessage, FormValues } from "@/lib/types";

import { CATALOG_ID, Column, Text, TextField } from "./catalog";

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

async function loadRenderer() {
  const [react, core] = await Promise.all([import("@a2ui/react"), import("@a2ui/web_core/v1_0")]);
  const { createComponentImplementation: implement } = react;

  // our components, under the v1.0 basic catalog's component APIs: no basic catalog element is ever drawn
  const components = [
    implement(core.ColumnApi, ({ props, buildChild }) => (
      <Column>{props.children?.map((c) => (typeof c === "string" ? buildChild(c) : buildChild(c.id, c.basePath)))}</Column>
    )),
    implement(core.TextApi, ({ props }) => <Text text={props.text ?? ""} />),
    implement(core.TextFieldApi, function TextFieldView({ props, context }) {
      const { surfaceId, readOnly } = useContext(FormContext);
      const id = context.componentModel.id;
      useReport(id, context.dataContext.path, props.isValid !== false);
      return (
        <TextField
          id={`${surfaceId}-${id}`}
          label={props.label}
          value={props.value ?? ""}
          onChange={props.setValue}
          readOnly={readOnly}
          error={props.validationErrors?.[0]}
        />
      );
    }),
  ];
  const catalog = new core.Catalog(CATALOG_ID, "1.0", components, core.V10_VALIDATION_FUNCTION_IMPLEMENTATIONS);
  return { A2uiSurface: react.A2uiSurface, MessageProcessor: core.MessageProcessor, catalog };
}

type Renderer = Awaited<ReturnType<typeof loadRenderer>>;
let loading: Promise<Renderer> | null = null;
// the renderer is large: it loads the first time a page has a form
const load = () => (loading ??= loadRenderer());

type Surface = ComponentProps<Renderer["A2uiSurface"]>["surface"];
type Drawn = { A2uiSurface: Renderer["A2uiSurface"]; surface: Surface; report: Form["report"] };

/** a2ui-core (the backend's validator) writes a component's checks as "@checks", web_core reads "checks" */
function forRenderer(message: FormMessage) {
  const components = message.createSurface.components.map(({ "@checks": checks, ...rest }) =>
    checks === undefined ? rest : { ...rest, checks },
  );
  return { ...message, createSurface: { ...message.createSurface, components } };
}

/** An A2UI form drawn with MegooColab's own components. `onChange` gets the surface's whole data model and whether
 * every check passes: once all inputs are drawn, then on every change. */
export function FormSurface({
  message,
  readOnly = false,
  onChange,
}: {
  message: FormMessage;
  readOnly?: boolean;
  onChange?: (data: FormValues, valid: boolean) => void;
}) {
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  // a refetched question brings an equal message: keep the surface, and what the person typed into it
  const source = JSON.stringify(message);

  useEffect(() => {
    const message = JSON.parse(source) as FormMessage;
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
          if (!live || inputs.some((id) => !results.get(id)?.size)) return;
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
  if (!drawn || !form) return null;
  const { A2uiSurface, surface } = drawn;
  return (
    <FormContext.Provider value={form}>
      <A2uiSurface surface={surface} />
    </FormContext.Provider>
  );
}
