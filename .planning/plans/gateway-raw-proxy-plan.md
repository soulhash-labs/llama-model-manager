# Plan: Gateway Raw Endpoint Proxying

## Objective
Enable `routed` mode for raw clients (OpenClaw, legacy scripts) by transparently proxying `/v1/completions` and `/v1/responses` to the local `llama.cpp` backend. The GlyphOS pipeline should **not** intercept these requests; they must flow directly through to preserve client expectations and model behavior.

## Current State
- **File:** `scripts/glyphos_openai_gateway.py`
- **Handler:** `GatewayHandler.do_POST` (Line 1473)
- **Behavior:** Strictly allows `/v1/chat/completions`. Returns `405 Method Not Allowed` for anything else.
- **Problem:** Clients sending to `POST /v1/completions` (OpenClaw default) fail in routed mode.

## Implementation Strategy

### 1. Add `_proxy_raw_request` Method
Create a dedicated helper method in `GatewayHandler` that acts as a transparent pipe.
- **Signature:** `_proxy_raw_request(self, target_path: str) -> None`
- **Logic:**
  1. Read `Content-Length` from headers.
  2. Read request body.
  3. Construct target URL: `f"{backend_base_url}{target_path}"`.
  4. Create a new `urllib.request.Request` for the target.
  5. Copy relevant headers (`Content-Type`, `Authorization`) to the new request.
  6. Send request and read response.
  7. **Crucial:** Stream the response back to the client, including status code and headers.

### 2. Update `do_POST` Dispatch
Modify the existing routing logic in `do_POST`.
- **Current:** `if path != "/v1/chat/completions": send_error(405)`
- **New:**
  ```python
  if path == "/v1/chat/completions":
      self._handle_chat_completions()
  elif path in ["/v1/completions", "/v1/responses"]:
      self._proxy_raw_request(path)
  else:
      self.send_error(404, "Endpoint not supported")
  ```

### 3. Implementation Details
- **Backend URL:** Access via `getattr(self.server, "backend_base_url", "http://127.0.0.1:8081/v1")`.
- **Timeout:** Use the same timeout logic as existing health checks or requests to ensure we don't hang.
- **Streaming:** Ensure we support chunked transfer encoding or simple read-and-forward for the response body.

## Verification
1. **Raw Completion:** `curl -X POST http://localhost:4010/v1/completions ...` should succeed and return text from `llama.cpp`.
2. **Chat Completion:** Existing `sync-opencode` flows must remain unchanged.
3. **Error Handling:** Invalid JSON to `/v1/completions` should ideally be passed through or rejected by backend (transparent).

## Files Modified
- `scripts/glyphos_openai_gateway.py`

## Risks
- **Headers:** Must ensure we don't leak internal headers or strip necessary ones (like `Accept`).
- **Streaming:** If the backend streams chunks, the proxy must preserve this to avoid buffering large responses in memory.
