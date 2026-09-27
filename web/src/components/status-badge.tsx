const tones: Record<string, string> = {
  MATCHED: "success",
  succeeded: "success",
  RESOLVED: "success",
  CLEAR: "success",
  NEEDS_REVIEW: "warning",
  OPEN: "warning",
  CLAIMED: "accent",
  queued: "neutral",
  processing: "accent",
  failed: "danger",
  NOT_ASSESSABLE: "neutral",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const label = value?.replaceAll("_", " ") ?? "Not available";
  return <span className={`status status-${tones[value ?? ""] ?? "neutral"}`}>{label}</span>;
}
