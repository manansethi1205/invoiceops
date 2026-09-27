"use client";

import { ErrorState } from "./feedback";

export function RouteError({ reset }: { reset: () => void }) {
  return <ErrorState message="This workspace could not be loaded. No document content was logged." retry={reset} />;
}
