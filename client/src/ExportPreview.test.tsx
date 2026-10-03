import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { clinicApi } from "./api";
import { ExportPreviewPanel } from "./ExportPreview";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

test("manual selection is server-reviewed and an enabled flag never enables workbook actions", async () => {
  const requests: {
    path: string;
    method: string;
    body?: { selected: string[] };
  }[] = [];
  vi.mocked(invoke).mockImplementation(async (_command, args) => {
    const { request } = args as {
      request: { path: string; method: string; body?: { selected: string[] } };
    };
    requests.push(request);
    const ids = request.body?.selected ?? [];
    const items = [1, 2].map((i) => ({
      case: {
        caseId: `00000000-0000-4000-8000-00000000000${i}`,
        sourceOrder: `SYN-ORDER-${i}`,
        chartNumber: `SYN-${i}`,
        patientName: "合成病人",
        reportingDate: "2026-10-03",
        reportedQuantity: 10,
        lots: i === 1 ? [{ lot: "SYN-LOT", quantity: 10 }] : [],
        excluded: false,
      },
      selected:
        request.method === "POST"
          ? ids.includes(`00000000-0000-4000-8000-00000000000${i}`)
          : i === 1,
      defaultSelected: i === 1,
      internalIssues: i === 1 ? [] : ["lots_missing"],
      warnings: ["duplicate_concern"],
      officialBlockers: ["official_required_fields_unverified"],
      officiallyExportable: false,
    }));
    return {
      status: 200,
      body: JSON.stringify({
        items,
        selectedCount: items.filter((item) => item.selected).length,
        internallyCompleteCount: 1,
        gates: [
          {
            key: "official_export_contract",
            label: "官方必填規則",
            status: "OPEN",
          },
        ],
        operationalFlagEnabled: true,
        productionExportEnabled: false,
      }),
    };
  });
  render(<ExportPreviewPanel api={clinicApi("synthetic-session", vi.fn())} />);
  expect(
    await screen.findByText("內部完整 1 筆；目前選取 1 筆"),
  ).toBeInTheDocument();
  expect(screen.getByText("OPEN：官方必填規則")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "產生正式 Excel" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "下載正式 Excel" })).toBeDisabled();
  await userEvent.click(screen.getByLabelText("選取 SYN-ORDER-2"));
  expect(
    await screen.findByText("內部完整 1 筆；目前選取 2 筆"),
  ).toBeInTheDocument();
  expect(requests.at(-1)).toMatchObject({
    method: "POST",
    path: "/api/v1/export-preview",
    body: {
      selected: [
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
      ],
    },
  });
  expect(screen.getByText("未填批號分攤")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "產生正式 Excel" })).toBeDisabled();
});
