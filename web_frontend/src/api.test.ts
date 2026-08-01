import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

class MockStorage implements Storage {
  private values = new Map<string, string>();

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.has(key) ? this.values.get(key)! : null;
  }

  key(index: number) {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

describe("api auth fallback", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("adds the stored username to fetch requests", async () => {
    const storage = new MockStorage();
    storage.setItem("aga_user", "lan user");
    vi.stubGlobal("localStorage", storage);
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ datasets: [] }),
      text: async () => ""
    }));
    vi.stubGlobal("fetch", fetchMock);

    await api.datasets();

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-AGA-User"]).toBe("lan%20user");
  });

  it("uses paged image requests instead of fetching the whole dataset", async () => {
    const storage = new MockStorage();
    storage.setItem("aga_user", "lan user");
    vi.stubGlobal("localStorage", storage);
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ items: [], total: 0, offset: 640, limit: 320 }),
      text: async () => ""
    }));
    vi.stubGlobal("fetch", fetchMock);

    await api.images("ds1", "mask_unreviewed", 640, 320);

    expect(String(fetchMock.mock.calls[0][0])).toContain("offset=640");
    expect(String(fetchMock.mock.calls[0][0])).toContain("limit=320");
    expect(String(fetchMock.mock.calls[0][0])).toContain("status=mask_unreviewed");
  });

  it("saves mask review scores through the sidecar endpoint", async () => {
    const storage = new MockStorage();
    storage.setItem("aga_user", "lan user");
    vi.stubGlobal("localStorage", storage);
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ score: 2, review_status: "usable" }),
      text: async () => ""
    }));
    vi.stubGlobal("fetch", fetchMock);

    await api.saveMaskReview("ds1", "img1", 3, { candidate_id: "abc", score: 2, failure_tags: ["edge_miss"] });

    expect(String(fetchMock.mock.calls[0][0])).toContain("/objects/3/mask-review");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toMatchObject({ candidate_id: "abc", score: 2 });
  });

  it("adds the stored username to chunk upload requests", async () => {
    const storage = new MockStorage();
    storage.setItem("aga_user", "lan user");
    vi.stubGlobal("localStorage", storage);

    class FakeXMLHttpRequest {
      static latest: FakeXMLHttpRequest | null = null;

      upload: { onprogress?: (event: ProgressEvent) => void } = {};
      headers: Record<string, string> = {};
      status = 200;
      statusText = "OK";
      responseText = JSON.stringify({ received: true, chunk_index: 0, total_chunks: 1 });
      withCredentials = false;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      constructor() {
        FakeXMLHttpRequest.latest = this;
      }

      open() {}

      setRequestHeader(name: string, value: string) {
        this.headers[name] = value;
      }

      send() {
        this.onload?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);

    await api.uploadChunk(new FormData());

    expect(FakeXMLHttpRequest.latest?.withCredentials).toBe(true);
    expect(FakeXMLHttpRequest.latest?.headers["X-AGA-User"]).toBe("lan%20user");
  });
});
