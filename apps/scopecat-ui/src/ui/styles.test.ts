import { describe, expect, it } from "vitest";
import { classes, dialogPopup, iconButton, secondaryButton } from "./styles";

describe("classes", () => {
  it("keeps the latest conflicting Tailwind utility", () => {
    expect(classes(iconButton, "size-[30px]")).not.toContain("size-[34px]");
    expect(classes(iconButton, "size-[30px]")).toContain("size-[30px]");

    expect(classes(dialogPopup, "w-[min(680px,100%)]")).not.toContain("w-[min(520px,100%)]");
    expect(classes(dialogPopup, "w-[min(680px,100%)]")).toContain("w-[min(680px,100%)]");

    expect(classes(secondaryButton, "min-h-[31px]")).not.toContain("min-h-9");
    expect(classes(secondaryButton, "min-h-[31px]")).toContain("min-h-[31px]");
  });

  it("ignores falsey conditional classes", () => {
    expect(classes("grid", false, null, undefined, "gap-2")).toBe("grid gap-2");
  });
});
