import { invoke } from "@tauri-apps/api/core";
import createClient from "openapi-fetch";
import type { paths, components } from "./generated/api";

export type Session = components["schemas"]["SessionView"];
export type Device = components["schemas"]["DeviceView"];
export type Capability = Device["capabilities"][number];
export type ConnectionSettings = {
  endpoint: string;
  credentialConfigured: boolean;
};
export class OperationError extends Error {}

export function clinicApi(
  sessionId: string | undefined,
  disconnected: () => void,
) {
  return createClient<paths>({
    // Rust resolves the actual configured endpoint and inserts the device secret.
    baseUrl: "https://central.invalid",
    fetch: async (input) => {
      const request = input instanceof Request ? input : new Request(input);
      const url = new URL(request.url);
      if (request.signal.aborted)
        throw new DOMException("Aborted", "AbortError");
      const text = await request.text();
      let result: { status: number; body: string };
      try {
        result = await invoke("central_request", {
          request: {
            method: request.method,
            path: url.pathname + url.search,
            sessionId,
            body: text ? JSON.parse(text) : null,
          },
        });
      } catch {
        disconnected();
        throw new OperationError(
          "中央服務無法連線。請確認網路與憑證，並改用診所核准的紙本流程。",
        );
      }
      if (request.signal.aborted)
        throw new DOMException("Aborted", "AbortError");
      if (result.status === 401 || result.status >= 500) disconnected();
      return new Response(result.body, {
        status: result.status,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "no-store",
        },
      });
    },
  });
}

export function requireData<T>(result: { data?: T; response: Response }): T {
  if (result.data !== undefined && result.response.ok) return result.data;
  const status = result.response.status;
  if (status === 401)
    throw new OperationError(
      "裝置未獲授權、配對碼已失效或連線已到期，請重新連線或聯絡管理者。",
    );
  if (status === 403)
    throw new OperationError(
      "這台裝置沒有此操作的能力，請使用已授權的管理裝置。",
    );
  if (status === 409)
    throw new OperationError(
      "資料版本或裝置狀態已變更。請重新核對；最後一台管理裝置須先有另一台管理裝置才能撤銷。",
    );
  throw new OperationError("操作未完成，請檢查輸入內容並重試。");
}
