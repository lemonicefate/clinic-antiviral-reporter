import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, test, expect } from "vitest";
import { App } from "./App";
import { invoke } from "@tauri-apps/api/core";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (command: string) => {
    if (command === "connection_settings")
      return { endpoint: "", credentialConfigured: false };
    throw new Error("synthetic offline transport");
  }),
}));

test("unpaired device presents connection setup and an actionable connection error", async () => {
  render(<App />);
  await screen.findByLabelText("中央服務位址");
  await userEvent.type(
    screen.getByLabelText("中央服務位址"),
    "https://central.invalid:8000",
  );
  await userEvent.type(screen.getByLabelText("操作身分"), "測試醫師");
  await userEvent.click(screen.getByRole("button", { name: "連線" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("紙本");
  expect(
    screen.queryByRole("heading", { name: "裝置管理" }),
  ).not.toBeInTheDocument();
});

test("offline event removes the authorized device screen and delayed rows cannot restore it", async () => {
  let finishDevices: ((value: unknown) => void) | undefined;
  vi.mocked(invoke).mockImplementation(async (command, args) => {
    if (command === "connection_settings")
      return {
        endpoint: "https://central.invalid",
        credentialConfigured: true,
      };
    if (command === "configure_connection") return;
    const request = (args as { request: { path: string } }).request;
    if (request.path === "/api/v1/sessions")
      return {
        status: 200,
        body: JSON.stringify({
          sessionId: "synthetic-session",
          deviceId: "synthetic-device",
          operator: "測試管理者",
          capabilities: ["admin"],
          revision: 1,
          expiresAt: 9999999999,
        }),
      };
    if (request.path === "/api/v1/devices")
      return new Promise((resolve) => {
        finishDevices = resolve;
      });
    throw new Error("Unexpected synthetic request");
  });
  render(<App />);
  await screen.findByDisplayValue("https://central.invalid");
  await userEvent.type(screen.getByLabelText("操作身分"), "測試管理者");
  await userEvent.click(screen.getByRole("button", { name: "連線" }));
  await screen.findByRole("heading", { name: "裝置管理" });
  window.dispatchEvent(new Event("offline"));
  expect(await screen.findByRole("alert")).toHaveTextContent("紙本");
  finishDevices?.({
    status: 200,
    body: JSON.stringify([
      {
        deviceId: "late-device",
        name: "延遲裝置",
        capabilities: ["admin"],
        revision: 1,
        revoked: false,
      },
    ]),
  });
  expect(screen.queryByText("延遲裝置")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "裝置管理" }),
  ).not.toBeInTheDocument();
});

test("a pairing whose response was lost keeps its request ID after reconnecting", async () => {
  const ids: string[] = [];
  vi.mocked(invoke).mockImplementation(async (command, args) => {
    if (command === "connection_settings")
      return {
        endpoint: "https://central.invalid",
        credentialConfigured: true,
      };
    if (command === "configure_connection") return;
    const request = (
      args as { request: { path: string; body: { requestId: string } } }
    ).request;
    if (request.path === "/api/v1/sessions")
      return {
        status: 200,
        body: JSON.stringify({
          sessionId: "synthetic",
          deviceId: "admin",
          operator: "管理者",
          capabilities: ["admin"],
          revision: 1,
          expiresAt: 9999999999,
        }),
      };
    if (request.path === "/api/v1/devices") return { status: 200, body: "[]" };
    if (request.path === "/api/v1/pairings") {
      ids.push(request.body.requestId);
      if (ids.length === 1)
        throw new Error("Synthetic lost response after commit");
      return {
        status: 200,
        body: JSON.stringify({
          pairingCode: "synthetic-pairing",
          expiresAt: 9999999999,
        }),
      };
    }
    throw new Error("Unexpected request");
  });
  render(<App />);
  await screen.findByDisplayValue("https://central.invalid");
  await userEvent.type(screen.getByLabelText("操作身分"), "管理者");
  await userEvent.click(screen.getByRole("button", { name: "連線" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "建立配對碼" }),
  );
  await screen.findByRole("alert");
  await userEvent.click(screen.getByRole("button", { name: "連線" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "建立配對碼" }),
  );
  await screen.findByDisplayValue("synthetic-pairing");
  expect(ids).toHaveLength(2);
  expect(ids[1]).toBe(ids[0]);
});

test("device loading, recoverable failure and empty recovery are explicit", async () => {
  let finish: ((result: unknown) => void) | undefined;
  let loads = 0;
  vi.mocked(invoke).mockImplementation(async (command, args) => {
    if (command === "connection_settings") return { endpoint: "https://central.invalid", credentialConfigured: true };
    if (command === "configure_connection") return;
    const request = (args as {request: {path: string}}).request;
    if (request.path === "/api/v1/sessions") return {status: 200, body: JSON.stringify({sessionId: "synthetic", deviceId: "admin", operator: "管理者", capabilities: ["admin"], revision: 1, expiresAt: 9999999999})};
    if (++loads === 1) return new Promise(resolve => { finish = resolve; });
    return {status: 200, body: "[]"};
  });
  render(<App />);
  await screen.findByDisplayValue("https://central.invalid");
  await userEvent.type(screen.getByLabelText("操作身分"), "管理者");
  await userEvent.click(screen.getByRole("button", {name: "連線"}));
  expect(await screen.findByRole("status")).toHaveTextContent("正在載入");
  await act(async () => { finish?.({status: 400, body: '{"detail":"synthetic temporary rejection"}'}); });
  expect(await screen.findByRole("alert")).toHaveTextContent("載入失敗");
  await userEvent.click(screen.getByRole("button", {name: "重新載入"}));
  await screen.findByText("目前沒有可顯示的裝置。");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("a stale reload cannot replace the device state obtained after revocation", async () => {
  let finishOldLoad: ((result: unknown) => void) | undefined;
  let loads = 0;
  const old = {deviceId: "physician", name: "測試診間", capabilities: ["physician"], revision: 1, revoked: false};
  vi.mocked(invoke).mockImplementation(async (command, args) => {
    if (command === "connection_settings") return {endpoint: "https://central.invalid", credentialConfigured: true};
    if (command === "configure_connection") return;
    const request = (args as {request: {path: string}}).request;
    if (request.path === "/api/v1/sessions") return {status: 200, body: JSON.stringify({sessionId: "synthetic", deviceId: "admin", operator: "管理者", capabilities: ["admin"], revision: 1, expiresAt: 9999999999})};
    if (request.path.endsWith("/revoke")) return {status: 200, body: JSON.stringify({...old, revision: 2, revoked: true})};
    loads++;
    if (loads === 2) return new Promise(resolve => {finishOldLoad = resolve;});
    return {status: 200, body: JSON.stringify([loads === 1 ? old : {...old, revision: 2, revoked: true}])};
  });
  render(<App />);
  await screen.findByDisplayValue("https://central.invalid");
  await userEvent.type(screen.getByLabelText("操作身分"), "管理者");
  await userEvent.click(screen.getByRole("button", {name: "連線"}));
  await screen.findByText("測試診間");
  await userEvent.click(screen.getByRole("button", {name: "重新載入"}));
  await userEvent.click(screen.getByRole("button", {name: "撤銷授權"}));
  await userEvent.type(screen.getByLabelText("撤銷原因"), "合成撤銷演練");
  await userEvent.click(screen.getByRole("button", {name: "確認撤銷"}));
  await screen.findByText("已撤銷", {selector: "td"});
  await act(async () => {finishOldLoad?.({status: 200, body: JSON.stringify([old])});});
  await waitFor(() => expect(screen.getByRole("button", {name: "撤銷授權"})).toBeDisabled());
  expect(screen.getByText("已撤銷", {selector: "td"})).toBeInTheDocument();
});
