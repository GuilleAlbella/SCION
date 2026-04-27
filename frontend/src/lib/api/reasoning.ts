import client from "./client";
import type { ReasoningResponse, BatchReasoningResponse, AskResponse } from "./types";

export async function runReasoning(
  changeId: number
): Promise<ReasoningResponse> {
  const { data } = await client.post<ReasoningResponse>(
    `/reasoning/${changeId}`
  );
  return data;
}

export async function runBatchReasoning(
  snapshotFrom: number,
  snapshotTo: number
): Promise<BatchReasoningResponse> {
  const { data } = await client.post<BatchReasoningResponse>(
    "/reasoning/batch",
    { snapshot_from: snapshotFrom, snapshot_to: snapshotTo }
  );
  return data;
}

export async function askQuestion(
  changeId: number,
  question: string,
  history?: { role: string; text: string }[]
): Promise<AskResponse> {
  const { data } = await client.post<AskResponse>(
    `/reasoning/${changeId}/ask`,
    { question, history }
  );
  return data;
}
