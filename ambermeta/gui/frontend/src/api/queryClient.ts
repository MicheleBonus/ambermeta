import { QueryClient, MutationCache } from "@tanstack/react-query";
import { expireToastActions, pushToast } from "@/lib/toast";
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
  // Every path that replaces the document retires any outstanding "Undo" offer — not just
  // the ones going through docMutation. Discover and Save write the document too, and both
  // push an undo snapshot server-side, so a toast that survived one of them would pop that
  // snapshot instead: clicking "Undo" on a delete would throw away the whole discovery.
  expireToastActions();
  queryClient.setQueryData(DOCUMENT_KEY, doc);
}
