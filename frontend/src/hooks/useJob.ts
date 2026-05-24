/**
 * useJob
 *
 * Manages the full lifecycle of a single swarm job:
 *  1. Creating the job (POST /api/generate)
 *  2. Storing the resulting job_id
 *  3. Fetching the final output once the swarm completes (GET /api/output/:id)
 *
 * Works alongside useSwarm — useJob handles the REST lifecycle while useSwarm
 * handles the live WebSocket state.
 *
 * Usage:
 *   const { jobId, output, createJob, fetchOutput, isCreating, outputError } = useJob();
 */

import { useState, useCallback } from "react";
import {
  generateJob,
  getJobOutput,
  GenerateRequest,
  JobOutput,
} from "../lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface UseJobResult {
  /** The active job id, or null if no job has been created yet */
  jobId: string | null;
  /** The final output, populated after fetchOutput() resolves */
  output: JobOutput | null;
  /** Whether the POST /api/generate request is in-flight */
  isCreating: boolean;
  /** Whether the GET /api/output request is in-flight */
  isFetchingOutput: boolean;
  /** Error from job creation, if any */
  createError: string | null;
  /** Error from output fetching, if any */
  outputError: string | null;
  /** Kick off a new swarm job */
  createJob: (req: GenerateRequest) => Promise<string | null>;
  /** Fetch the completed artifacts — call once isComplete is true */
  fetchOutput: (jobId: string) => Promise<void>;
  /** Reset all state to start fresh */
  reset: () => void;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useJob(): UseJobResult {
  const [jobId, setJobId] = useState<string | null>(null);
  const [output, setOutput] = useState<JobOutput | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isFetchingOutput, setIsFetchingOutput] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [outputError, setOutputError] = useState<string | null>(null);

  /**
   * What does this do?
   * Sends the requirement to the backend, stores the returned job_id,
   * and returns it so the caller can immediately start the WebSocket.
   * Returns null if the request failed.
   */
  const createJob = useCallback(async (req: GenerateRequest): Promise<string | null> => {
    setIsCreating(true);
    setCreateError(null);
    setOutput(null);
    setJobId(null);

    try {
      const res = await generateJob(req);
      setJobId(res.job_id);
      return res.job_id;
    } catch (err) {
      console.error("API error: createJob →", err);
      setCreateError(err instanceof Error ? err.message : "Unknown error creating job");
      return null;
    } finally {
      setIsCreating(false);
    }
  }, []);

  /**
   * What does this do?
   * Fetches the completed file tree and deployment URLs once the swarm
   * signals completion. Safe to call multiple times — subsequent calls
   * overwrite the previous output.
   */
  const fetchOutput = useCallback(async (id: string): Promise<void> => {
    setIsFetchingOutput(true);
    setOutputError(null);

    try {
      const result = await getJobOutput(id);
      setOutput(result);
    } catch (err) {
      console.error("API error: fetchOutput →", err);
      setOutputError(err instanceof Error ? err.message : "Unknown error fetching output");
    } finally {
      setIsFetchingOutput(false);
    }
  }, []);

  /**
   * What does this do?
   * Clears all job state so the user can submit a new requirement.
   */
  const reset = useCallback(() => {
    setJobId(null);
    setOutput(null);
    setIsCreating(false);
    setIsFetchingOutput(false);
    setCreateError(null);
    setOutputError(null);
  }, []);

  return {
    jobId,
    output,
    isCreating,
    isFetchingOutput,
    createError,
    outputError,
    createJob,
    fetchOutput,
    reset,
  };
}
