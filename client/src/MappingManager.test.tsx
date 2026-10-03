import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { clinicApi } from "./api";
import { MappingManager } from "./MappingManager";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

test("administrator explicitly sets dates and a conflict blocks overwrite until reload", async () => {
  const initial = {
    revision: 0,
    goLiveAt: null,
    initialDateFrom: null,
    versions: [],
    confirmedProfile: {
      internalCode: "ERA",
      nhiCode: "A059653100",
      materialValue: "DDMTR2018090002:易剋冒膠囊(顆)",
      quantityRule: "integer_capsules",
    },
    openGates: [
      "live_his_contract",
      "official_export_contract",
      "synthetic_smis_import",
    ],
    productionExportEnabled: false,
  };
  let current = initial;
  const submitted: Record<string, unknown>[] = [];
  vi.mocked(invoke).mockImplementation(async (_command, args) => {
    const { request } = args as {
      request: { method: string; body: Record<string, unknown> };
    };
    if (request.method === "GET")
      return { status: 200, body: JSON.stringify(current) };
    submitted.push(request.body);
    current = { ...initial, revision: 1 };
    return {
      status: 409,
      body: JSON.stringify({
        detail: { currentRevision: 1, differences: current },
      }),
    };
  });
  render(<MappingManager api={clinicApi("synthetic-session", vi.fn())} />);
  expect(await screen.findByText("尚未設定啟用時間")).toBeInTheDocument();
  const effective = screen.getByLabelText("生效日期（台灣時間 00:00）");
  expect(effective).toHaveValue("");
  fireEvent.change(effective, { target: { value: "2026-10-01" } });
  fireEvent.change(screen.getByLabelText("初始掃描起日"), {
    target: { value: "2026-10-01" },
  });
  await userEvent.type(
    screen.getByLabelText("設定原因"),
    "synthetic explicit decision",
  );
  await userEvent.click(screen.getByRole("button", { name: "儲存新版本" }));
  expect(await screen.findByText(/其他管理者已變更設定/)).toBeInTheDocument();
  expect(submitted[0]).toMatchObject({
    effectiveFrom: "2026-10-01T00:00:00+08:00",
    initialDateFrom: "2026-10-01",
    expectedRevision: 0,
  });
  expect(screen.getByRole("button", { name: "儲存新版本" })).toBeDisabled();
  expect(screen.getByLabelText("設定原因")).toHaveValue(
    "synthetic explicit decision",
  );
  await userEvent.click(screen.getByRole("button", { name: "重新載入並核對" }));
  expect(await screen.findByText("目前設定版本：1")).toBeInTheDocument();
  expect(screen.getByLabelText("設定原因")).toHaveValue("");
});
