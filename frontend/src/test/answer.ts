import { fireEvent, screen, within } from "@testing-library/react";

/** Answers the confirm dialog (useConfirm) by clicking one of its buttons, e.g. "Delete" or "Cancel". */
export async function answer(button: string): Promise<HTMLElement> {
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: button }));
  return dialog;
}
