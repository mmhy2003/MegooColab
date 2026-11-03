import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ImageGallery } from "@/components/images/ImageGallery";

const images = [
  { id: "i1", filename: "phone-ios.png", size: 412 * 1024 },
  { id: "i2", filename: "phone-android.png", size: 388 * 1024 },
  { id: "i3", filename: "design.png", size: 1.1 * 1024 * 1024 },
];

afterEach(cleanup);

describe("ImageGallery", () => {
  it("shows each image as a thumbnail served in the page", () => {
    render(<ImageGallery images={images} />);
    const thumbs = screen.getAllByRole("img");
    expect(thumbs.map((t) => t.getAttribute("src"))).toEqual([
      "/api/attachments/i1?inline=1", "/api/attachments/i2?inline=1", "/api/attachments/i3?inline=1",
    ]);
    expect(screen.getByRole("button", { name: "Open phone-ios.png" })).toBeInTheDocument();
  });

  it("opens one full size, moves through the message's images, and closes", () => {
    render(<ImageGallery images={images} />);
    fireEvent.click(screen.getByRole("button", { name: "Open phone-android.png" }));
    const viewer = screen.getByRole("dialog", { name: "phone-android.png" });
    expect(within(viewer).getByText("2 of 3")).toBeInTheDocument();
    expect(within(viewer).getByText("388.0 KB")).toBeInTheDocument();
    expect(within(viewer).getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/attachments/i2");
    fireEvent.keyDown(viewer, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "design.png" })).toBeInTheDocument();
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous image" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous image" }));
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows nothing without images", () => {
    const { container } = render(<ImageGallery images={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
