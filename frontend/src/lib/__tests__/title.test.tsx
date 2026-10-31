import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { pageTitle, usePageTitle, useRecordTitle } from "@/lib/title";

function Page({ parts }: { parts: (string | null | undefined)[] }) {
  usePageTitle(...parts);
  return null;
}

function Record({ parts }: { parts: (string | null | undefined)[] }) {
  useRecordTitle(...parts);
  return null;
}

afterEach(() => {
  cleanup();
  document.title = "MegooColab";
});

describe("pageTitle", () => {
  it("puts the page first and the app name last", () => {
    expect(pageTitle("PAY-12 Fix login")).toBe("PAY-12 Fix login · MegooColab");
    expect(pageTitle("Users", "Admin")).toBe("Users · Admin · MegooColab");
  });

  it("leaves out what isn't known yet, down to the app name alone", () => {
    expect(pageTitle(undefined, "Admin", null, "")).toBe("Admin · MegooColab");
    expect(pageTitle()).toBe("MegooColab");
  });
});

describe("usePageTitle", () => {
  it("names the page while it shows, and the app again when it goes", () => {
    const { unmount } = render(<Page parts={["Projects"]} />);
    expect(document.title).toBe("Projects · MegooColab");
    unmount();
    expect(document.title).toBe("MegooColab");
  });

  it("follows the record once it loads", () => {
    const { rerender } = render(<Page parts={[undefined]} />);
    expect(document.title).toBe("MegooColab");
    rerender(<Page parts={["Fix login"]} />);
    expect(document.title).toBe("Fix login · MegooColab");
  });

  it("a record opened over a page names the tab, whichever mounts first, and the page's comes back when it closes", () => {
    // the record inside the page: its effect runs before the page's
    const { rerender } = render(
      <>
        <Page parts={["PAY Board"]} />
        <Record parts={["PAY-12 Fix login"]} />
      </>,
    );
    expect(document.title).toBe("PAY-12 Fix login · MegooColab");
    rerender(<Page parts={["PAY Board"]} />);
    expect(document.title).toBe("PAY Board · MegooColab");
    rerender(
      <>
        <Page parts={["PAY Board"]} />
        <Record parts={["PAY-7 Retry"]} />
      </>,
    );
    expect(document.title).toBe("PAY-7 Retry · MegooColab");
  });

  it("the page shown latest names the tab", () => {
    const { rerender } = render(<Page parts={["Projects"]} />);
    rerender(
      <>
        <Page parts={["Projects"]} />
        <Page parts={["New project"]} />
      </>,
    );
    expect(document.title).toBe("New project · MegooColab");
  });
});
