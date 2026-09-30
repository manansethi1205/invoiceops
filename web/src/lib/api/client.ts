import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export const api = createClient<paths>({ baseUrl: "/api/backend" });

export type ApiSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function sanitizeMessage(value: unknown, fallback = "The request could not be completed. Try again."): string {
  const candidate = typeof value === "string" ? value : fallback;
  const normalized = candidate.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
  return (normalized || fallback).slice(0, 300);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return sanitizeMessage(error.message);
  if (error instanceof Error && error.message) return sanitizeMessage(error.message);
  return sanitizeMessage(undefined);
}

export async function uploadInvoice(file: File): Promise<ApiSchema<"UploadAccepted">> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/backend/v1/invoices", { method: "POST", body: form });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String(body.detail)
        : "Invoice upload failed";
    throw new ApiError(sanitizeMessage(detail, "Invoice upload failed"), response.status);
  }
  return (await response.json()) as ApiSchema<"UploadAccepted">;
}

export async function createPayableCase(idempotencyKey: string): Promise<ApiSchema<"CaseRead">> {
  return required(api.POST("/v1/cases", { body: { idempotency_key: idempotencyKey } }));
}

export async function attachCaseDocument(
  caseId: string,
  options: {
    file: File;
    role: ApiSchema<"DocumentRole">;
    idempotencyKey: string;
    expectedCaseVersion: number;
    supersedesId?: string;
  },
): Promise<ApiSchema<"CaseAttachmentAccepted">> {
  const form = new FormData();
  form.append("file", options.file);
  form.append("role", options.role);
  form.append("idempotency_key", options.idempotencyKey);
  form.append("expected_case_version", String(options.expectedCaseVersion));
  if (options.supersedesId) form.append("supersedes_id", options.supersedesId);
  const response = await fetch(`/api/backend/v1/cases/${caseId}/documents`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? JSON.stringify(body.detail)
        : "Document attachment failed";
    throw new ApiError(sanitizeMessage(detail, "Document attachment failed"), response.status);
  }
  return (await response.json()) as ApiSchema<"CaseAttachmentAccepted">;
}

export async function required<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const result = await request;
  if (result.data !== undefined) return result.data;
  const detail =
    typeof result.error === "object" && result.error !== null && "detail" in result.error
      ? JSON.stringify(result.error.detail)
      : `Request failed (${result.response.status})`;
  throw new ApiError(sanitizeMessage(detail), result.response.status);
}
