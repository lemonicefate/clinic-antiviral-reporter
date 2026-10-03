import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    let revoked = false;
    Object.assign(window, {
      __TAURI_INTERNALS__: {
        invoke: async (
          command: string,
          args: { request?: { path: string } },
        ) => {
          if (command === "connection_settings")
            return {
              endpoint: "https://central.invalid:8000",
              credentialConfigured: true,
            };
          if (command === "configure_connection") return;
          if (command === "central_request") {
            const session = {
              sessionId: "synthetic-session",
              deviceId: "synthetic-admin",
              operator: "測試管理者",
              capabilities: ["admin"],
              revision: 1,
              expiresAt: 9999999999,
            };
            if (args.request?.path === "/api/v1/pairings")
              return {
                status: 200,
                body: JSON.stringify({
                  pairingCode: "SYNTHETIC-PAIRING-NOT-A-REAL-SECRET-1234567890",
                  expiresAt: Date.now() / 1000 + 600,
                }),
              };
            if (args.request?.path?.endsWith("/revoke")) {
              revoked = true;
              return {
                status: 200,
                body: JSON.stringify({
                  deviceId: "synthetic-admin",
                  name: "測試管理工作站",
                  capabilities: ["admin"],
                  revision: 2,
                  revoked: true,
                }),
              };
            }
            if (args.request?.path === "/api/v1/devices")
              return {
                status: 200,
                body: JSON.stringify([
                  {
                    deviceId: "synthetic-admin",
                    name: "測試管理工作站",
                    capabilities: ["admin"],
                    revision: revoked ? 2 : 1,
                    revoked,
                  },
                  {
                    deviceId: "synthetic-physician",
                    name: "測試診間 A",
                    capabilities: ["physician"],
                    revision: 2,
                    revoked: true,
                  },
                  ...(location.search.includes("many")
                    ? Array.from({ length: 18 }, (_, i) => ({
                        deviceId: `synthetic-${i}`,
                        name: `測試診間 ${i + 1}`,
                        capabilities: [i === 0 ? "admin" : "physician"],
                        revision: 1,
                        revoked: false,
                      }))
                    : []),
                ]),
              };
            return { status: 200, body: JSON.stringify(session) };
          }
          throw new Error("Unexpected synthetic request");
        },
      },
    });
  });
});

test("revoke focus follows the task and pairing results are announced", async ({
  page,
}) => {
  await page.goto("/?many=1");
  await expect(page.getByLabel("中央服務位址")).toHaveValue(
    "https://central.invalid:8000",
  );
  await page.getByLabel("操作身分").fill("測試管理者");
  await page.getByRole("button", { name: "連線", exact: true }).click();
  const trigger = page.getByRole("button", { name: "撤銷授權" }).first();
  await trigger.click();
  await expect(page.getByLabel("撤銷原因")).toBeFocused();
  await page.getByLabel("撤銷原因").fill("合成裝置撤銷演練");
  await page.screenshot({ path: "../screenshots/revoke-focus-1080.png" });
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.getByLabel("撤銷原因").fill("合成裝置撤銷演練");
  await page.getByRole("button", { name: "確認撤銷" }).click();
  await expect(page.getByRole("heading", { name: "裝置管理" })).toBeFocused();
  await expect(page.getByRole("status")).toContainText("已撤銷");
  await page.getByRole("button", { name: "建立配對碼" }).click();
  await expect(page.getByRole("status")).toContainText("配對碼已建立");
  await page.getByLabel("配對碼", { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../screenshots/pairing-result-1080.png" });
});

test("connection and authorized management render without overflow at desktop sizes", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByLabel("中央服務位址")).toHaveValue(
    "https://central.invalid:8000",
  );
  await page.screenshot({
    path: "../screenshots/connection-1080.png",
    fullPage: true,
  });
  await page.getByLabel("操作身分").fill("測試管理者");
  await page.getByRole("button", { name: "連線", exact: true }).click();
  await expect(page.getByRole("heading", { name: "裝置管理" })).toBeVisible();
  await expect(page.getByText("測試管理工作站")).toBeVisible();
  await page.screenshot({
    path: "../screenshots/devices-1080.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 720, height: 700 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../screenshots/devices-720.png",
    fullPage: true,
  });
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.getByRole("heading", { name: "裝置管理" })).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("紙本");
  await page.screenshot({
    path: "../screenshots/offline-720.png",
    fullPage: true,
  });
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
});
