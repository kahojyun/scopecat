export const primaryButton =
  "inline-flex min-h-9 cursor-pointer items-center justify-center gap-[7px] rounded-[8px] border border-accent bg-accent px-3 text-[0.7rem] font-[750] text-bg hover:not-disabled:border-[#9ff4ec] hover:not-disabled:bg-[#9ff4ec] disabled:cursor-not-allowed disabled:opacity-45";

export const secondaryButton =
  "inline-flex min-h-9 cursor-pointer items-center justify-center gap-[7px] rounded-[8px] border border-line-strong bg-panel px-3 text-[0.7rem] font-[750] text-text-soft hover:not-disabled:bg-panel-strong hover:not-disabled:text-text disabled:cursor-not-allowed disabled:opacity-45";

export const iconButton =
  "grid size-[34px] cursor-pointer place-items-center rounded-sm border border-line bg-panel p-0 text-text-soft hover:border-line-strong hover:bg-panel-strong hover:text-text";

export const detailCard = "min-w-0 rounded-md border border-line bg-panel-soft p-3.5";

export const countBadge =
  "inline-flex h-[23px] min-w-6 items-center justify-center rounded-md border border-line bg-panel px-[7px] text-[0.64rem] font-[750] text-text-dim";

export const eyebrow =
  "mb-[7px] text-[0.68rem] font-extrabold tracking-[0.14em] text-accent uppercase";

export const dialogBackdrop = "fixed inset-0 z-50 bg-[rgb(3_6_9_/_70%)]";

export const dialogViewport =
  "fixed inset-0 z-51 grid overflow-auto p-5 place-items-center max-[460px]:p-2.5";

export const dialogPopup =
  "w-[min(520px,100%)] overflow-hidden rounded-lg border border-line-strong bg-panel shadow-[0_24px_70px_rgb(0_0_0_/_50%)] outline-0";

export const dialogTitle = "m-0 text-[0.86rem] font-bold text-text";

export const dialogDescription = "mt-[5px] mb-0 text-[0.66rem] leading-normal text-text-dim";

export function classes(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}
