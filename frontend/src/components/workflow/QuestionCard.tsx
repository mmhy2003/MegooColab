"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { FormSurface } from "@/components/a2ui/FormSurface";
import { ImageAttach, ImageDropZone } from "@/components/images/ImageAttach";
import { ImageGallery } from "@/components/images/ImageGallery";
import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useImageDraft } from "@/lib/images";
import { qk } from "@/lib/queries";
import type { ActivityItem, ActivityQuestion, FormValues, MockupInfo } from "@/lib/types";

import { MockupFrame } from "./MockupFrame";

const MAX_ANSWER = 4000;
const OTHER = "\u0000other"; // cannot collide with a choice id ([a-z0-9_-])

export function QuestionCard({
  item,
  taskKey,
  canAct,
  readOnly = false,
  onAnswered,
}: {
  item: ActivityItem;
  taskKey: string;
  /** the viewer may answer (workflow.can_act) */
  canAct: boolean;
  /** a read-only view: nobody answers from here */
  readOnly?: boolean;
  /** called after every answer attempt, also a conflicting one, so the thread can refetch */
  onAnswered?: () => void;
}) {
  const q = item.question as unknown as ActivityQuestion;
  const client = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState("");
  const textRef = useRef("");
  useEffect(() => {
    textRef.current = text;
  }, [text]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const images = useImageDraft(); // with an answer in the person's own words
  // a form question: what the form holds, whether its checks pass, and whether the person answers in their own words
  const [data, setData] = useState<FormValues | null>(null);
  const [valid, setValid] = useState(false);
  const [ownWords, setOwnWords] = useState(false);
  const open = q.status === "open";
  const answerable = canAct && !readOnly && open;

  const mockups = useQuery({
    queryKey: qk.mockups(taskKey),
    queryFn: () => api<MockupInfo[]>(`/api/tasks/${taskKey}/mockups`),
    enabled: !!q.mockup,
  });
  const mockup = q.mockup ? mockups.data?.find((m) => m.id === q.mockup!.id) : undefined;
  // a mockup click only preselects; a person has to press "Send answer". It never replaces typed text.
  const preselect = useCallback((choice: string) => setSelected((cur) => (cur === OTHER && textRef.current.trim() ? cur : choice)), []);

  // recommended first, otherwise the agent's order
  const choices = [...q.choices].sort((a, b) => Number(!!b.recommended) - Number(!!a.recommended));
  const label = (id: string) => q.choices.find((c) => c.id === id)?.label ?? id;
  const other = selected === OTHER;
  const ready = selected !== null && (!other || text.trim().length > 0) && !(other && images.uploading);
  const sendSelected = () => {
    if (!ready) return;
    if (other) sendOwnWords();
    else void send({ choice: selected! });
  };

  const ownWordsReady = text.trim().length > 0 && !images.uploading;
  const sendOwnWords = () => void send({ text: text.trim(), ...(images.ids.length ? { image_ids: images.ids } : {}) });
  const formReady = ownWords ? ownWordsReady : valid && data !== null;
  const sendForm = () => {
    if (!formReady) return;
    if (ownWords) sendOwnWords();
    else void send({ data: data! });
  };

  const send = async (json: { choice: string } | { text: string; image_ids?: string[] } | { data: FormValues }) => {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await api(`/api/tasks/${taskKey}/questions/${q.id}/answer`, { method: "POST", json });
    } catch (err) {
      setError(err instanceof ApiError && err.detail === "already_decided" ? "Someone already answered." : errorMessage(err));
    } finally {
      // also after a failure: a 409 means the question moved on
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.activity(taskKey) }),
        client.invalidateQueries({ queryKey: qk.workflow(taskKey) }),
        client.invalidateQueries({ queryKey: qk.agentRuns(taskKey) }),
        client.invalidateQueries({ queryKey: qk.task(taskKey) }),
      ]);
      setBusy(false);
      onAnswered?.();
    }
  };

  const ownWordsBox = (
    <div className="space-y-1">
      <ImageDropZone draft={images}>
        <textarea
          aria-label="Your answer"
          className="block w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm"
          rows={3}
          maxLength={MAX_ANSWER}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </ImageDropZone>
      <ImageAttach draft={images} />
      <p className="text-right text-xs text-muted-foreground">
        {text.length}/{MAX_ANSWER}
      </p>
    </div>
  );

  return (
    // data-waiting: the task's "waiting on you" button jumps here (JumpButtons)
    <div data-waiting={answerable ? "question" : undefined} className={`card min-w-0 flex-1 space-y-2 px-3 py-2 ${q.status === "withdrawn" ? "opacity-60" : ""}`}>
      <p className="text-xs text-muted-foreground">
        <span className="text-fg">Agent question</span>
        {q.status === "withdrawn" && <> · withdrawn</>}
        {q.status === "answered" && <> · answered</>}
      </p>
      <Markdown>{q.body}</Markdown>
      {q.mockup && mockups.error && <p className="text-xs text-pink">Couldn&apos;t load the mockup.</p>}
      {q.mockup && mockup && (
        <MockupFrame mockupId={mockup.id} version={mockup.version} title={mockup.title} choices={mockup.choices} onChoice={answerable ? preselect : noop} />
      )}

      {answerable && q.form ? (
        <div className="space-y-2">
          {/* hidden, not unmounted, in own-words mode: what the person filled in survives the switch */}
          <div className={ownWords ? "hidden" : undefined}>
            <FormSurface
              message={q.form}
              readOnly={busy}
              onChange={(d, v) => {
                setData(d);
                setValid(v);
              }}
            />
          </div>
          <button type="button" className="text-xs text-cyan-ink underline" onClick={() => setOwnWords((o) => !o)}>
            {ownWords ? "Back to the form" : "Answer in your own words instead"}
          </button>
          {ownWords && ownWordsBox}
          <Button disabled={!formReady || busy} onClick={sendForm}>
            Send answer
          </Button>
        </div>
      ) : answerable ? (
        <div className="space-y-2">
          <ul className="space-y-1">
            {choices.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  aria-pressed={selected === c.id}
                  disabled={busy}
                  onClick={() => void send({ choice: c.id })}
                  className={`w-full rounded border px-2 py-1 text-left text-sm ${selected === c.id ? "border-cyan bg-surface-2" : "border-line hover:border-cyan"}`}
                >
                  <span className="font-semibold">{c.label}</span>
                  {c.recommended && <span className="text-cyan-ink"> (Recommended)</span>}
                  {c.description && <span className="block text-xs text-muted-foreground">{c.description}</span>}
                </button>
              </li>
            ))}
            <li>
              <button
                type="button"
                aria-pressed={other}
                disabled={busy}
                onClick={() => setSelected(OTHER)}
                className={`w-full rounded border px-2 py-1 text-left text-sm ${other ? "border-cyan bg-surface-2" : "border-line hover:border-cyan"}`}
              >
                Other
              </button>
            </li>
          </ul>
          {selected !== null && !other && !q.choices.some((c) => c.id === selected) && (
            <p className="text-xs text-muted-foreground">Selected in the mockup: {selected}</p>
          )}
          {other && ownWordsBox}
          <Button disabled={!ready || busy} onClick={sendSelected}>
            Send answer
          </Button>
        </div>
      ) : (
        <>
          {q.form && q.status !== "answered" && <FormSurface message={q.form} readOnly />}
          {q.form && q.answer_data && (
            <FormSurface message={{ ...q.form, createSurface: { ...q.form.createSurface, dataModel: q.answer_data } }} readOnly />
          )}
          {q.choices.length > 0 && (
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {choices.map((c) => (
                <li key={c.id}>
                  <span className="text-fg">{c.label}</span>
                  {c.recommended && " (Recommended)"}
                  {c.description && ` — ${c.description}`}
                </li>
              ))}
            </ul>
          )}
          {open && (
            <p className="text-xs text-muted-foreground">
              {canAct ? "This is a read-only view." : "Waiting on the agent's owner, a project manager or an admin to answer."}
            </p>
          )}
        </>
      )}

      {q.status === "answered" && q.answer_data && (
        <p className="text-sm text-muted-foreground">{q.answered_by?.name ?? "Someone"} answered with the form.</p>
      )}
      {q.status === "answered" && !q.answer_data && (
        <p className="text-sm">
          <span className="text-muted-foreground">{q.answered_by?.name ?? "Someone"} answered: </span>
          {q.answer_choice ? label(q.answer_choice) : null}
          {q.answer_choice && q.answer_text ? " — " : null}
          {q.answer_text}
        </p>
      )}
      {q.status === "answered" && <ImageGallery images={item.images ?? []} />}
      {error && (
        <p role="alert" className="text-xs text-pink">
          {error}
        </p>
      )}
    </div>
  );
}

function noop() {}
