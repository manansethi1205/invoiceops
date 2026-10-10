export const rowAssociationReason = {
  code: "EXTRACTION_ROW_ASSOCIATION_UNRESOLVED",
  label: "Invoice row association needs review",
  explanation: "Extracted cells could not be safely linked to the invoice rows. Check descriptions, quantities and amounts against the source document. Automatic matching was withheld; this case requires review.",
} as const;

export function reviewReasonLabel(code: string): string {
  return code === rowAssociationReason.code ? rowAssociationReason.label : code;
}

export function reviewReasonExplanation(code: string): string | undefined {
  return code === rowAssociationReason.code ? rowAssociationReason.explanation : undefined;
}
