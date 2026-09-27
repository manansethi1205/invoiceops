"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 5_000 } } }));
  return (
    <QueryClientProvider client={client}>
      <Tooltip.Provider delayDuration={250}>{children}</Tooltip.Provider>
    </QueryClientProvider>
  );
}
