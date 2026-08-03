/** Minimal n8n public-API client. Header is `X-N8N-API-KEY`, not a bearer. */

export interface N8nWorkflow {
  id?: string;
  name: string;
  nodes: Array<Record<string, unknown>>;
  connections: Record<string, unknown>;
  settings?: Record<string, unknown>;
  active?: boolean;
  tags?: Array<{ id: string; name: string }>;
  [k: string]: unknown;
}

export interface N8nCredential {
  id: string;
  name: string;
  type: string;
}
export interface N8nTag {
  id: string;
  name: string;
}

export class N8nError extends Error {
  constructor(readonly status: number, readonly method: string, readonly path: string, readonly body: string) {
    super(`${method} ${path} → ${String(status)}\n${body}`);
    this.name = 'N8nError';
  }
}

export class N8nClient {
  private readonly base: string;

  constructor(baseUrl: string, private readonly apiKey: string) {
    if (!baseUrl) throw new Error('N8N_API_URL is not set');
    if (!apiKey) throw new Error('N8N_API_KEY is not set');
    this.base = `${baseUrl.replace(/\/+$/, '')}/api/v1`;
  }

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      method,
      headers: {
        'X-N8N-API-KEY': this.apiKey,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const text = await res.text();
    if (!res.ok) throw new N8nError(res.status, method, path, text);
    return (text ? JSON.parse(text) : {}) as T;
  }

  async listWorkflows(tags?: string[]): Promise<N8nWorkflow[]> {
    // NB: do not also pass projectId — n8n#19283, the two filters do not work together.
    const q = new URLSearchParams({ limit: '250', excludePinnedData: 'true' });
    if (tags?.length) q.set('tags', tags.join(','));
    const r = await this.req<{ data: N8nWorkflow[] }>('GET', `/workflows?${q.toString()}`);
    return r.data;
  }

  getWorkflow(id: string): Promise<N8nWorkflow> {
    return this.req('GET', `/workflows/${id}?excludePinnedData=true`);
  }

  createWorkflow(body: unknown): Promise<N8nWorkflow> {
    return this.req('POST', '/workflows', body);
  }

  /** Body must be EXACTLY { name, nodes, connections, settings } — additionalProperties:false. */
  updateWorkflow(id: string, body: unknown): Promise<N8nWorkflow> {
    return this.req('PUT', `/workflows/${id}`, body);
  }

  setTags(id: string, tagIds: string[]): Promise<unknown> {
    return this.req('PUT', `/workflows/${id}/tags`, tagIds.map((t) => ({ id: t })));
  }

  /**
   * Activation route differs by n8n version: `/publish` is newer, `/activate` older and
   * still the only one present on some Cloud instances. Try the new one, fall back on 404.
   * Hard-coding either guarantees a future break, since Cloud auto-updates (doc 09 §6.4).
   */
  async activate(id: string): Promise<'publish' | 'activate'> {
    try {
      await this.req('POST', `/workflows/${id}/publish`);
      return 'publish';
    } catch (err) {
      if (err instanceof N8nError && err.status === 404) {
        await this.req('POST', `/workflows/${id}/activate`);
        return 'activate';
      }
      throw err;
    }
  }

  async listCredentials(): Promise<N8nCredential[]> {
    // Secrets are never returned by this endpoint — only id, name, type, timestamps.
    const r = await this.req<{ data: N8nCredential[] }>('GET', '/credentials?limit=250');
    return r.data;
  }

  async listTags(): Promise<N8nTag[]> {
    const r = await this.req<{ data: N8nTag[] }>('GET', '/tags?limit=250');
    return r.data;
  }

  createTag(name: string): Promise<N8nTag> {
    return this.req('POST', '/tags', { name });
  }
}
