export const primaryButton =
  "inline-flex min-h-9 cursor-pointer items-center justify-center gap-[7px] rounded-[8px] border border-accent bg-accent px-3 text-[0.7rem] font-[750] text-bg hover:not-disabled:border-[#9ff4ec] hover:not-disabled:bg-[#9ff4ec] disabled:cursor-not-allowed disabled:opacity-45";

export const secondaryButton =
  "inline-flex min-h-9 cursor-pointer items-center justify-center gap-[7px] rounded-[8px] border border-line-strong bg-panel px-3 text-[0.7rem] font-[750] text-text-soft hover:not-disabled:bg-panel-strong hover:not-disabled:text-text disabled:cursor-not-allowed disabled:opacity-45";

export const iconButton =
  "grid size-[34px] cursor-pointer place-items-center rounded-sm border border-line bg-panel p-0 text-text-soft hover:border-line-strong hover:bg-panel-strong hover:text-text";

export function classes(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}
