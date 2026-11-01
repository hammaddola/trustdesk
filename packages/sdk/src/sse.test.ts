import { describe, expect, it } from "vitest";

import { SSEParser } from "./sse";

describe("SSEParser", () => {
  it("parses events split across chunks and ignores heartbeats and unknown events", () => {
    const p = new SSEParser();
    const raw = 'retry: 5000\n\n: ping\n\nid: 1\nevent: token\ndata: {"text":"Hi [1]."}\n\nevent: bogus\ndata: {}\n\nid: 2\nevent: confidence\ndata: {"level":"high"}\n\n';
    const events = [];
    for (let i = 0; i < raw.length; i += 7) events.push(...p.feed(raw.slice(i, i + 7)));
    expect(events).toEqual([
      { event: "token", data: { text: "Hi [1]." } },
      { event: "confidence", data: { level: "high" } },
    ]);
  });

  it("handles CRLF line endings and malformed JSON safely", () => {
    const p = new SSEParser();
    expect(p.feed('event: token\r\ndata: {"text":"a"}\r\n\r\nevent: token\ndata: {not json}\n\n')).toEqual([
      { event: "token", data: { text: "a" } },
    ]);
  });
});
