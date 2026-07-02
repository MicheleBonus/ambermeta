import { QueryClient, MutationCache } from "@tanstack/react-query";
import { pushToast } from "@/lib/toast";
import { ApiError } from "./client";
import type { DocumentResponse } from "@/types";

export const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: (err) => pushToast(err instanceof ApiError ? err.detail : "Something went wrong", "error"),
  }),
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

export const DOCUMENT_KEY = ["document"] as const;

export function setDocument(doc: DocumentResponse): void {
  queryClient.setQueryData(DOCUMENT_KEY, doc);
  queryClient.invalidateQueries({ queryKey: ["sequences"] });
}
