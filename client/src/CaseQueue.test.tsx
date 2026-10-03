import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { App } from "./App";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

test("physician explicitly selects a tied order and outage clears patient content", async () => {
  const item = {
    caseId: "11111111-1111-4111-8111-111111111111",
    revision: 1,
    chartNumber: "SYN-0001",
    patientName: "合成病人甲",
    birthDate: "1990-01-01",
    physician: "SYN-DR-A",
    reportingDate: "2026-10-03",
    sourceOrder: "SYN-ORDER-1",
    sourceQuantity: 10,
    reportedQuantity: 10,
    material: "DDMTR2018090002:易剋冒膠囊(顆)",
    overdue: false,
    duplicateConcern: true,
    status: "awaiting_reason",
    synthetic: true,
    liveIdentityVerified: false,
  };
  vi.mocked(invoke).mockImplementation(async (command, args) => {
    if (command === "connection_settings")
      return {
        endpoint: "https://central.invalid",
        credentialConfigured: true,
      };
    if (command === "configure_connection") return;
    const { request } = args as { request: { path: string } };
    if (request.path === "/api/v1/scans/status")
      return {status: 200, body: JSON.stringify({revision: 0, enabled: false, status: "disabled", intervalSeconds: 60})};
    if (request.path === "/api/v1/reason-options")
      return {
        status: 200,
        body: JSON.stringify({ values: ["23:未滿5歲及65歲以上之類流感患者"] }),
      };
    if (request.path === "/api/v1/sessions")
      return {
        status: 200,
        body: JSON.stringify({
          sessionId: "synthetic-session",
          deviceId: "synthetic-device",
          operator: "SYN-DR-A",
          capabilities: ["physician"],
          revision: 1,
          expiresAt: 9999999999,
        }),
      };
    if (request.path.startsWith("/api/v1/cases?"))
      return {
        status: 200,
        body: JSON.stringify({
          items: [
            item,
            {
              ...item,
              caseId: "22222222-2222-4222-8222-222222222222",
              sourceOrder: "SYN-ORDER-2",
            },
          ],
          total: 2,
          overdue: 0,
          physicians: ["SYN-DR-A", "SYN-DR-B"],
          physician: "SYN-DR-A",
          syntheticRefreshEnabled: true,
          refreshRevision: 1,
        }),
      };
    if (request.path.includes(item.caseId))
      return {
        status: 200,
        body: JSON.stringify({
          ...item,
          snapshots: [
            { sequence: 1, capturedAt: 1, raw: { "CH012M1.USE_TAMT": "10" } },
          ],
        }),
      };
    throw new Error("unexpected synthetic request");
  });
  render(<App />);
  await screen.findByDisplayValue("https://central.invalid");
  await userEvent.type(screen.getByLabelText("操作身分"), "SYN-DR-A");
  await userEvent.click(screen.getByRole("button", { name: "連線" }));
  await screen.findByRole("heading", { name: "醫師工作清單" });
  expect(await screen.findAllByText("合成病人甲")).toHaveLength(2);
  expect(
    screen.queryByRole("heading", { name: "核對案件" }),
  ).not.toBeInTheDocument();
  const rows = screen.getAllByRole("row");
  await userEvent.click(
    within(rows[1]).getByRole("button", { name: "核對此案" }),
  );
  expect(
    await screen.findByRole("heading", { name: "核對案件" }),
  ).toBeInTheDocument();
  expect(screen.getByText("來源量 10 顆；回報量 10 顆")).toBeInTheDocument();
  window.dispatchEvent(new Event("offline"));
  expect(await screen.findByRole("alert")).toHaveTextContent("紙本");
  expect(screen.queryByText("合成病人甲")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "核對案件" }),
  ).not.toBeInTheDocument();
  expect(localStorage.length).toBe(0);
});
