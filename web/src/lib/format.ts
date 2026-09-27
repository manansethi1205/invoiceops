export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

export function formatMoney(value: string | null, currency: string | null): string {
  if (value === null) return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount) || currency === null) return `${currency ?? ""} ${value}`.trim();
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${currency} ${value}`;
  }
}

export function ageSince(value: string | null): string {
  if (!value) return "No waiting reviews";
  const hours = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 3_600_000));
  return hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d ${hours % 24}h`;
}
