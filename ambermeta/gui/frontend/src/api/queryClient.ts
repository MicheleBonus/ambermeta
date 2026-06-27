import { QueryClient } from "@tanstack/react-query";
import type { DocumentResponse } from "@/types";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

export const DOCUMENT_KEY = ["document"] as const;

export function setDocument(doc: DocumentResponse): void {
  queryClient.setQueryData(DOCUMENT_KEY, doc);
}
