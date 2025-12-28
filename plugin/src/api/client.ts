import {
  EstimateRequest,
  EstimateResponse,
  JobCreateResponse,
  JobResultResponse,
  JobStatusResponse,
  UploadResponse
} from '../types';

async function parseJson(response: Response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  return JSON.parse(text);
}

async function request<T>(url: string, apiKey: string, options: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {})
  };
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    const data = await parseJson(response);
    const message = data?.detail || data?.message || response.statusText;
    throw new Error(message);
  }
  return (await parseJson(response)) as T;
}

export async function estimateCost(apiBaseUrl: string, apiKey: string, payload: EstimateRequest): Promise<EstimateResponse> {
  return request<EstimateResponse>(`${apiBaseUrl}/estimate`, apiKey, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function getUploadUrl(
  apiBaseUrl: string,
  apiKey: string,
  payload: { bundleSha256: string; bundleSizeBytes: number; projectHash: string; manifestHash: string }
): Promise<UploadResponse> {
  return request<UploadResponse>(`${apiBaseUrl}/upload`, apiKey, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function createJob(
  apiBaseUrl: string,
  apiKey: string,
  payload: Record<string, unknown>
): Promise<JobCreateResponse> {
  return request<JobCreateResponse>(`${apiBaseUrl}/jobs/create`, apiKey, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function getJobStatus(apiBaseUrl: string, apiKey: string, jobId: string): Promise<JobStatusResponse> {
  return request<JobStatusResponse>(`${apiBaseUrl}/jobs/status/${jobId}`, apiKey, {
    method: 'GET'
  });
}

export async function getJobResult(apiBaseUrl: string, apiKey: string, jobId: string): Promise<JobResultResponse> {
  return request<JobResultResponse>(`${apiBaseUrl}/jobs/result/${jobId}`, apiKey, {
    method: 'GET'
  });
}

export async function cancelJob(apiBaseUrl: string, apiKey: string, jobId: string) {
  return request(`${apiBaseUrl}/jobs/cancel/${jobId}`, apiKey, { method: 'POST' });
}
