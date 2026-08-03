/** Minimal typed Vapi REST client. No SDK — the surface we need is small and stable. */

const BASE = 'https://api.vapi.ai';

export interface VapiEntity {
  id: string;
  name?: string;
  [k: string]: unknown;
}

export class VapiError extends Error {
  constructor(
    readonly status: number,
    readonly method: string,
    readonly path: string,
    readonly body: string,
  ) {
    super(`${method} ${path} → ${String(status)}\n${body}`);
    this.name = 'VapiError';
  }
}

export class VapiClient {
  constructor(private readonly apiKey: string) {
    if (!apiKey) throw new Error('VAPI_API_KEY is not set');
  }

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const text = await res.text();
    if (!res.ok) throw new VapiError(res.status, method, path, text);
    return (text ? JSON.parse(text) : {}) as T;
  }

  listAssistants(): Promise<VapiEntity[]> {
    return this.req('GET', '/assistant?limit=100');
  }
  getAssistant(id: string): Promise<VapiEntity> {
    return this.req('GET', `/assistant/${id}`);
  }
  createAssistant(body: unknown): Promise<VapiEntity> {
    return this.req('POST', '/assistant', body);
  }
  updateAssistant(id: string, body: unknown): Promise<VapiEntity> {
    return this.req('PATCH', `/assistant/${id}`, body);
  }

  listTools(): Promise<VapiEntity[]> {
    return this.req('GET', '/tool?limit=200');
  }
  createTool(body: unknown): Promise<VapiEntity> {
    return this.req('POST', '/tool', body);
  }
  updateTool(id: string, body: unknown): Promise<VapiEntity> {
    return this.req('PATCH', `/tool/${id}`, body);
  }

  listStructuredOutputs(): Promise<{ results?: VapiEntity[] } | VapiEntity[]> {
    return this.req('GET', '/structured-output?limit=100');
  }
  createStructuredOutput(body: unknown): Promise<VapiEntity> {
    return this.req('POST', '/structured-output', body);
  }
  updateStructuredOutput(id: string, body: unknown): Promise<VapiEntity> {
    return this.req('PATCH', `/structured-output/${id}`, body);
  }
}

/** Tool identity is `function.name` for function tools, else the tool `type`. */
export function toolIdentity(tool: Record<string, unknown>): string {
  const fn = tool['function'] as { name?: string } | undefined;
  return fn?.name ?? String(tool['type'] ?? '');
}
