import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FollowUps, initialRows, MAX_FOLLOW_UPS, type FollowUpRow } from "@/components/workflow/FollowUps";
import type { DocumentDetail, FollowUpOut, FollowUpRef } from "@/lib/types";

afterEach(cleanup);

const entry = (title: string, more: Partial<FollowUpOut> = {}): FollowUpOut => ({
  title,
  type: "story",
  description_md: `About ${title}`,
  created: false,
  task_key: null,
  ...more,
});

function doc(status: DocumentDetail["status"], follow_ups: FollowUpOut[], earlier_follow_ups: FollowUpRef[] = []): DocumentDetail {
  return {
    kind: "design",
    version: 2,
    status,
    created_at: "2026-11-19T10:00:00Z",
    decided_by: null,
    decision_comment: null,
    follow_up_count: follow_ups.length,
    body_md: "# Design",
    steps: null,
    attached_mockup_ids: [],
    mockup_id: null,
    follow_ups,
    earlier_follow_ups,
    creates_in: status === "submitted" ? { column: "Backlog", epic: null } : null,
  } as DocumentDetail;
}

/** Holds the review rows in state, like DocumentView does, and reports every change. */
function Review({ detail, onChange }: { detail: DocumentDetail; onChange: (rows: FollowUpRow[]) => void }) {
  const [rows, setRows] = useState(() => initialRows(detail));
  return (
    <FollowUps
      detail={detail}
      projectKey="PAY"
      review={{
        rows,
        onChange: (next) => {
          onChange(next);
          setRows(next);
        },
      }}
    />
  );
}

function review(entries: FollowUpOut[]) {
  const onChange = vi.fn();
  render(<Review detail={doc("submitted", entries)} onChange={onChange} />);
  return { onChange, last: (): FollowUpRow[] => onChange.mock.calls.at(-1)![0] };
}

const two = [entry("Phase 2: refunds"), entry("Phase 3: reports", { type: "task" })];

describe("FollowUps in review", () => {
  it("starts from every proposed entry, ticked", () => {
    expect(initialRows(doc("submitted", two))).toEqual([
      { title: "Phase 2: refunds", type: "story", description_md: "About Phase 2: refunds", create: true, added: false },
      { title: "Phase 3: reports", type: "task", description_md: "About Phase 3: reports", create: true, added: false },
    ]);
  });

  it("unticking a row calls back with create: false", () => {
    const { last } = review(two);
    const box = screen.getByRole("checkbox", { name: "Create task 1" });
    expect(box).toBeChecked();
    fireEvent.click(box);
    expect(last()[0].create).toBe(false);
    expect(last()[1].create).toBe(true);
    expect(screen.getByRole("checkbox", { name: "Create task 1" })).not.toBeChecked();
  });

  it("edits a row's title and type", () => {
    const { onChange, last } = review(two);
    const before = onChange.mock.calls.length;
    fireEvent.change(screen.getByRole("textbox", { name: "Title of task 2" }), { target: { value: "Phase 3: exports" } });
    expect(last()[1].title).toBe("Phase 3: exports");
    fireEvent.change(screen.getByRole("combobox", { name: "Type of task 2" }), { target: { value: "bug" } });
    expect(last()[1]).toMatchObject({ title: "Phase 3: exports", type: "bug" });
    expect(last()[0]).toMatchObject({ title: "Phase 2: refunds", type: "story" });
    expect(onChange.mock.calls.length).toBe(before + 2);
    // a new array every time
    expect(onChange.mock.calls.at(-1)![0]).not.toBe(onChange.mock.calls.at(-2)![0]);
  });

  it("opens the description textarea", () => {
    const { last } = review(two);
    const area = screen.getByLabelText("Description of task 1");
    expect(area).not.toBeVisible();
    fireEvent.click(screen.getAllByText("Description")[0]);
    expect(area).toBeVisible();
    expect(area).toHaveValue("About Phase 2: refunds");
    fireEvent.change(area, { target: { value: "Refunds only" } });
    expect(last()[0].description_md).toBe("Refunds only");
  });

  it("adds a row of the person's own and removes it; proposed rows have no remove button", () => {
    const { last } = review(two);
    expect(screen.queryByRole("button", { name: /^Remove task/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "+ Add a task" }));
    expect(last()).toHaveLength(3);
    expect(last()[2]).toEqual({ title: "", type: "task", description_md: "", create: true, added: true });
    expect(screen.getByText("added by you")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Title of task 3" })).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Remove task 3" }));
    expect(last()).toHaveLength(2);
    expect(screen.queryByText("added by you")).toBeNull();
  });

  it("can't add more than 10 tasks", () => {
    expect(MAX_FOLLOW_UPS).toBe(10);
    review(Array.from({ length: 10 }, (_, i) => entry(`Phase ${i + 2}`)));
    expect(screen.getByRole("button", { name: "+ Add a task" })).toBeDisabled();
  });

  it("shows None proposed. for an empty list, and still lets the person add one", () => {
    review([]);
    expect(screen.getByRole("region", { name: "Follow-up tasks" })).toBeInTheDocument();
    expect(screen.getByText("None proposed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Add a task" })).toBeEnabled();
  });
});

describe("FollowUps read-only", () => {
  it("lists a submitted version's entries without checkboxes", () => {
    render(<FollowUps detail={doc("submitted", two)} projectKey="PAY" />);
    const block = screen.getByRole("region", { name: "Follow-up tasks" });
    expect(within(block).getByRole("heading", { name: "Follow-up tasks" })).toBeInTheDocument();
    const items = within(block).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("story · Phase 2: refunds");
    expect(items[1]).toHaveTextContent("task · Phase 3: reports");
    expect(within(items[0]).getByText("About Phase 2: refunds")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Add a task" })).toBeNull();
    expect(screen.queryByText(/created/)).toBeNull();
  });

  it("shows what an approved version created", () => {
    const entries = [
      entry("Phase 2: refunds", { created: true, task_key: "PAY-13" }),
      entry("Phase 3: reports", { created: true, task_key: null }),
      entry("Phase 4: exports"),
    ];
    render(<FollowUps detail={doc("approved", entries)} projectKey="PAY" />);
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("created PAY-13");
    expect(within(items[0]).getByRole("link", { name: "PAY-13" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-13");
    expect(items[1]).toHaveTextContent("created");
    expect(within(items[1]).queryByRole("link")).toBeNull();
    expect(items[2]).toHaveTextContent("not created");
    expect(within(items[2]).queryByRole("link")).toBeNull();
  });

  it("names what earlier approved designs created", () => {
    const earlier = [
      { key: "PAY-13", title: "Phase 2" },
      { key: "PAY-14", title: "Phase 3" },
    ];
    render(<FollowUps detail={doc("approved", [], earlier)} projectKey="PAY" />);
    const line = screen.getByText(/Already created from an earlier approved design:/);
    expect(line).toHaveTextContent("Already created from an earlier approved design: PAY-13, PAY-14.");
    expect(within(line).getByRole("link", { name: "PAY-14" })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-14");
  });

  it("shows nothing when there is nothing to show", () => {
    const { container } = render(<FollowUps detail={doc("approved", [])} projectKey="PAY" />);
    expect(container).toBeEmptyDOMElement();
  });
});
