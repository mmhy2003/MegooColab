import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SkillUpload } from "@/components/hub/SkillUpload";

let fetchMock: ReturnType<typeof vi.fn<(url: string, init?: RequestInit) => Promise<Response>>>;
let status = 201;

beforeEach(() => {
  status = 201;
  fetchMock = vi.fn(async () =>
    status === 201
      ? new Response(JSON.stringify({ id: "t9" }), { status })
      : new Response(JSON.stringify({ detail: "hub_skill_no_skill_md" }), { status }),
  );
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fileAt(path: string, text: string): File {
  const f = new File([text], path.split("/").pop()!, { type: "text/plain" });
  Object.defineProperty(f, "webkitRelativePath", { value: path });
  return f;
}

describe("SkillUpload", () => {
  it("a folder goes up file by file, each named by its path", async () => {
    const onDone = vi.fn();
    render(<SkillUpload onDone={onDone} />);
    const input = screen.getByLabelText("Upload a folder");
    expect(input).toHaveAttribute("webkitdirectory");
    fireEvent.change(input, { target: { files: [fileAt("ui/SKILL.md", "# x"), fileAt("ui/a/b.sh", "echo")] } });
    await waitFor(() => expect(onDone).toHaveBeenCalledWith({ id: "t9" }));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/hub/skills");
    expect(init?.method).toBe("POST");
    const form = init?.body as FormData;
    expect((form.getAll("files") as File[]).map((f) => f.name)).toEqual(["ui/SKILL.md", "ui/a/b.sh"]);
  });

  it("a zip replaces the files of an existing skill", async () => {
    status = 201;
    render(<SkillUpload toolId="t1" onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Upload a .zip"), { target: { files: [new File(["zip"], "s.zip")] } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/hub/tools/t1/files");
    expect(init?.method).toBe("PUT");
    expect((init?.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("says what is wrong with the upload", async () => {
    status = 422;
    render(<SkillUpload onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Upload a .zip"), { target: { files: [new File(["zip"], "s.zip")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("A skill needs a SKILL.md at its top level.");
  });
});
