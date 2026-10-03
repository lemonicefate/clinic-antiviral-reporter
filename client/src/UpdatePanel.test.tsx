import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { UpdatePanel } from "./UpdatePanel";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
const state = {
  enabled: true, currentVersion: "0.1.0", available: null,
  planToken: null, preparedVersion: null, rollbackVersion: null, recoveryAvailable: false,
};
test("checking and preparing an update never install it before explicit confirmation", async () => {
  const calls: string[] = [];
  vi.mocked(invoke).mockImplementation(async (command) => {
    calls.push(command);
    if (command === "update_state") return state;
    if (command === "check_updates") return { ...state, available: { version: "0.1.1", notes: "合成版本" } };
    if (command === "prepare_update") return { ...state, preparedVersion: "0.1.1", planToken: "synthetic-plan", recoveryAvailable: true };
    if (command === "install_update") throw "合成安裝拒絕：目前程式保持開啟。";
    throw new Error("Unexpected synthetic operation");
  });
  render(<UpdatePanel connectionEpoch="synthetic-device" />);
  await userEvent.click(screen.getByText("程式更新與回復"));
  await screen.findByText(/有新版本 0.1.1/);
  expect(calls).not.toContain("prepare_update");
  expect(calls).not.toContain("install_update");
  await userEvent.click(screen.getByRole("button", { name: "下載並驗證更新與回復包" }));
  const install = await screen.findByRole("button", { name: "結束程式並安裝 0.1.1" });
  expect(install).toBeDisabled();
  expect(calls).not.toContain("install_update");
  await userEvent.click(screen.getByLabelText("我已儲存所有工作，現在可以結束回報工具"));
  await userEvent.click(install);
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("install_update", {
    token: "synthetic-plan", confirmed: true, rollback: false,
  }));
  expect(await screen.findByText(/合成安裝拒絕/)).toBeInTheDocument();
  expect(install).toBeDisabled();
});

test("a failed online check preserves the offline recovery action", async () => {
  vi.mocked(invoke).mockImplementation(async (command) => {
    if (command === "update_state") return { ...state, currentVersion: "0.1.1", planToken: "synthetic-plan",
      rollbackVersion: "0.1.0", recoveryAvailable: true };
    if (command === "check_updates") throw "合成中央離線";
    if (command === "open_update_recovery") return;
    throw new Error("Unexpected synthetic operation");
  });
  render(<UpdatePanel connectionEpoch="" />);
  await userEvent.click(screen.getByText("程式更新與回復"));
  await screen.findByText(/更新檢查未完成/);
  expect(screen.getByRole("button", { name: "結束程式並回復 0.1.0" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "開啟回復工具資料夾" }));
  expect(invoke).toHaveBeenCalledWith("open_update_recovery", undefined);
});

test("startup checks prevent manual operations until the check settles", async () => {
  let finish!: (value: typeof state) => void;
  const pending = new Promise<typeof state>((resolve) => { finish = resolve; });
  vi.mocked(invoke).mockImplementation(async (command) => {
    if (command === "update_state") return state;
    if (command === "check_updates") return pending;
    throw new Error("Unexpected synthetic operation");
  });
  render(<UpdatePanel connectionEpoch="synthetic-device" />);
  await userEvent.click(screen.getByText("程式更新與回復"));
  const check = screen.getByRole("button", { name: "檢查更新" });
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("check_updates"));
  expect(check).toBeDisabled();
  await userEvent.click(check);
  finish(state);
  await waitFor(() => expect(check).toBeEnabled());
});
