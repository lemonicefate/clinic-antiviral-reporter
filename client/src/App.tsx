import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { clinicApi, OperationError, requireData } from "./api";
import type { Capability, ConnectionSettings, Device, Session } from "./api";
import { CaseQueue } from "./CaseQueue";

const capabilityNames: Record<Capability, string> = {
  admin: "管理者",
  physician: "醫師",
  reporting: "回報管理",
};

function useRequestId() {
  const pending = useRef<{ body: string; id: string } | null>(null);
  return {
    get: (body: unknown) => {
      const serialized = JSON.stringify(body);
      if (pending.current?.body !== serialized)
        pending.current = { body: serialized, id: crypto.randomUUID() };
      return pending.current.id;
    },
    complete: () => {
      pending.current = null;
    },
  };
}

export function App() {
  const [endpoint, setEndpoint] = useState("");
  const [operator, setOperator] = useState("");
  const [mode, setMode] = useState("connect");
  const [pairingCode, setPairingCode] = useState("");
  const [deviceName, setDeviceName] = useState("");
  const [credential, setCredential] = useState("");
  const [session, setSession] = useState<Session>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState("devices");
  const epoch = useRef(0);
  const enrollmentRequest = useRequestId();
  const sessionRequest = useRequestId();
  // Only device-management retry identifiers survive a disconnect. No patient
  // command or offline work queue is retained here.
  const pairingRequest = useRequestId();
  const revokeRequest = useRequestId();
  const disconnect = useCallback(() => {
    epoch.current += 1;
    setSession(undefined);
    setError(
      "中央連線已中斷或裝置授權失效。請重新連線；無法連線時改用診所核准的紙本流程。",
    );
  }, []);

  useEffect(() => {
    let active = true;
    invoke<ConnectionSettings>("connection_settings")
      .then((settings) => {
        if (active) setEndpoint(settings.endpoint);
      })
      .catch(() => {
        if (active) setError("無法讀取裝置設定，請重新輸入中央位址。");
      });
    window.addEventListener("offline", disconnect);
    return () => {
      active = false;
      window.removeEventListener("offline", disconnect);
    };
  }, [disconnect]);

  const api = useMemo(() => {
    const generation = epoch.current;
    return clinicApi(session?.sessionId, () => {
      if (epoch.current === generation) disconnect();
    });
  }, [session?.sessionId, disconnect]);
  useEffect(() => {
    if (!session) return;
    let active = true;
    let checking = false;
    const check = async () => {
      if (checking) return;
      checking = true;
      try {
        const result = await api.GET("/api/v1/session");
        if (active && !result.response.ok) disconnect();
      } catch {
        if (active) disconnect();
      } finally {
        checking = false;
      }
    };
    const timer = window.setInterval(check, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [session, api, disconnect]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    const currentEpoch = epoch.current;
    try {
      await invoke("configure_connection", {
        endpoint,
        credential: mode === "import" ? credential : null,
      });
      setCredential("");
      if (mode === "pair") {
        const body = {
          expectedRevision: 0,
          pairingCode,
          name: deviceName,
          credential: "managed-by-desktop",
        };
        const enrollmentId = enrollmentRequest.get(body);
        await invoke("prepare_identity", { requestId: enrollmentId });
        requireData(
          await api.POST("/api/v1/devices/enroll", {
            body: { ...body, requestId: enrollmentId },
          }),
        );
      }
      const body = { expectedRevision: 0, operator };
      const result = requireData(
        await api.POST("/api/v1/sessions", {
          body: { ...body, requestId: sessionRequest.get(body) },
        }),
      );
      if (!("sessionId" in result))
        throw new Error("此請求編號已有其他操作結果，請重新連線。");
      if (currentEpoch !== epoch.current) return;
      enrollmentRequest.complete();
      sessionRequest.complete();
      setPairingCode("");
      setPage(result.capabilities.includes("admin") ? "devices" : "cases");
      setSession(result);
    } catch (failure) {
      setCredential("");
      setError(
        failure instanceof OperationError
          ? failure.message
          : "無法完成連線。請確認設定，並改用診所核准的紙本流程。",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <strong>公費抗病毒藥劑回報</strong>
        <span>{session ? "中央服務已連線" : "尚未連線"}</span>
      </header>
      <main>
        {session ? (
          <>
            <div className="page-heading">
              <div>
                <h1>{page === "cases" ? "案件工作區" : "裝置與連線"}</h1>
                <p>
                  操作身分：{session.operator} ·{" "}
                  {session.capabilities
                    .map((c) => capabilityNames[c as Capability])
                    .join("、")}
                </p>
              </div>
              <button
                className="secondary"
                onClick={() => {
                  epoch.current += 1;
                  setSession(undefined);
                  setError("");
                }}
              >
                結束本次操作
              </button>
            </div>
            <p className="notice">
              操作身分用於篩選與稽核，不代表已驗證本人。切換身分不會增加裝置能力。
            </p>
            {session.capabilities.includes("admin") && (
              <nav aria-label="工作區">
                <button
                  className="secondary"
                  onClick={() => setPage("devices")}
                  aria-pressed={page === "devices"}
                >
                  裝置與連線
                </button>{" "}
                <button
                  className="secondary"
                  onClick={() => setPage("cases")}
                  aria-pressed={page === "cases"}
                >
                  案件工作清單
                </button>
              </nav>
            )}
            {page === "cases" ? (
              <CaseQueue key={session.sessionId} api={api} session={session} />
            ) : session.capabilities.includes("admin") ? (
              <DeviceManager
                key={session.sessionId}
                api={api}
                pairingRequest={pairingRequest}
                revokeRequest={revokeRequest}
              />
            ) : (
              <section>
                <h2>裝置已獲授權</h2>
                <p>此版本已提供安全連線；案件工作清單仍在開發中。</p>
              </section>
            )}
          </>
        ) : (
          <section className="connection-layout">
            <div className="connection-context">
              <h1>
                連線至診所
                <br />
                中央服務
              </h1>
              <p>使用已授權裝置，選定本次操作身分後開始。</p>
              <div className="paper-note">
                <h2>中央無法連線時</h2>
                <p>
                  改用診所核准的紙本流程。此工具不提供離線查看、編輯或匯出。
                </p>
              </div>
            </div>
            <form onSubmit={connect} className="connection-form">
              <h2>本機連線設定</h2>
              <label>
                中央服務位址
                <input
                  type="url"
                  required
                  placeholder="https://中央主機:8000"
                  value={endpoint}
                  onChange={(e) => setEndpoint(e.target.value)}
                  disabled={busy}
                  autoComplete="off"
                />
              </label>
              <label>
                操作身分
                <input
                  required
                  value={operator}
                  onChange={(e) => setOperator(e.target.value)}
                  maxLength={100}
                  disabled={busy}
                  autoComplete="off"
                />
              </label>
              <label>
                裝置設定方式
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  disabled={busy}
                >
                  <option value="connect">使用已配對裝置</option>
                  <option value="pair">以管理者配對碼啟用</option>
                  <option value="import">匯入初始管理裝置金鑰</option>
                </select>
              </label>
              {mode === "pair" && (
                <>
                  <label>
                    裝置名稱
                    <input
                      required
                      value={deviceName}
                      onChange={(e) => setDeviceName(e.target.value)}
                      maxLength={100}
                      disabled={busy}
                      autoComplete="off"
                    />
                  </label>
                  <label>
                    配對碼
                    <input
                      type="password"
                      required
                      value={pairingCode}
                      onChange={(e) => setPairingCode(e.target.value)}
                      disabled={busy}
                      autoComplete="off"
                    />
                  </label>
                </>
              )}
              {mode === "import" && (
                <label>
                  初始裝置金鑰
                  <input
                    type="password"
                    required
                    value={credential}
                    onChange={(e) => setCredential(e.target.value)}
                    disabled={busy}
                    autoComplete="off"
                  />
                </label>
              )}
              <p className="field-help">
                裝置憑證由 Windows 保管。這裡不需要 HIS 路徑或共用資料夾密碼。
              </p>
              {error && (
                <p role="alert" className="error">
                  {error}
                </p>
              )}
              <button disabled={busy}>{busy ? "正在連線…" : "連線"}</button>
            </form>
          </section>
        )}
      </main>
      <footer>開發驗證版本 · 正式 Excel 匯出尚未啟用</footer>
    </div>
  );
}

function DeviceManager({
  api,
  pairingRequest,
  revokeRequest,
}: {
  api: ReturnType<typeof clinicApi>;
  pairingRequest: ReturnType<typeof useRequestId>;
  revokeRequest: ReturnType<typeof useRequestId>;
}) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [capability, setCapability] = useState<Capability>("physician");
  const [code, setCode] = useState("");
  const [expiresAt, setExpiresAt] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Device>();
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const reasonField = useRef<HTMLInputElement>(null);
  const revokeTrigger = useRef<HTMLButtonElement | null>(null);
  const managementHeading = useRef<HTMLHeadingElement>(null);
  const active = useRef(true);
  const loadGeneration = useRef(0);
  const reload = useCallback(async () => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    try {
      const data = requireData(await api.GET("/api/v1/devices"));
      if (active.current && generation === loadGeneration.current) {
        setDevices(data);
        setLoadError("");
      }
    } catch {
      if (active.current && generation === loadGeneration.current)
        setLoadError("裝置清單載入失敗，請重新載入；現有資料可能已變更。");
    } finally {
      if (active.current && generation === loadGeneration.current)
        setLoading(false);
    }
  }, [api]);
  useEffect(() => {
    active.current = true;
    void reload();
    return () => {
      active.current = false;
    };
  }, [reload]);
  useEffect(() => {
    if (selected) reasonField.current?.focus();
  }, [selected]);

  async function createPairing(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("正在建立配對碼…");
    try {
      const body = { expectedRevision: 0, capabilities: [capability] };
      const result = requireData(
        await api.POST("/api/v1/pairings", {
          body: { ...body, requestId: pairingRequest.get(body) },
        }),
      );
      if (!("pairingCode" in result))
        throw new Error("請求已有其他操作結果，請重新進入裝置管理。");
      if (active.current) {
        pairingRequest.complete();
        setCode(result.pairingCode);
        setExpiresAt(result.expiresAt);
        setNotice("配對碼已建立。請將下方配對碼交給受授權的裝置操作者。");
      }
    } catch (failure) {
      if (active.current) {
        setNotice("");
        setError(
          failure instanceof Error ? failure.message : "無法建立配對碼。",
        );
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }

  async function revoke(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    loadGeneration.current += 1;
    setBusy(true);
    setError("");
    setNotice("正在撤銷裝置授權…");
    try {
      const body = { expectedRevision: selected.revision, reason };
      requireData(
        await api.POST("/api/v1/devices/{device_id}/revoke", {
          params: { path: { device_id: selected.deviceId } },
          body: {
            ...body,
            requestId: revokeRequest.get({
              deviceId: selected.deviceId,
              ...body,
            }),
          },
        }),
      );
      if (active.current) {
        revokeRequest.complete();
        setSelected(undefined);
        setReason("");
        setNotice(`已撤銷「${selected.name}」的授權。`);
        await reload();
        managementHeading.current?.focus();
      }
    } catch (failure) {
      if (active.current) {
        setNotice("");
        setError(failure instanceof Error ? failure.message : "撤銷未完成。");
        setSelected(undefined);
        await reload().catch(() => {});
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }

  return (
    <section className="device-manager">
      <div className="section-heading">
        <h2 ref={managementHeading} tabIndex={-1}>
          裝置管理
        </h2>
        <button
          className="secondary"
          disabled={busy || loading}
          onClick={() => void reload()}
        >
          重新載入
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      <p role="status" className="operation-status">
        {notice || (loading ? "正在載入裝置清單…" : "")}
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>裝置名稱</th>
              <th>能力</th>
              <th>狀態</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {!loading && !loadError && devices.length === 0 && (
              <tr>
                <td colSpan={4}>目前沒有可顯示的裝置。</td>
              </tr>
            )}
            {devices.map((device) => (
              <tr key={device.deviceId}>
                <td>{device.name}</td>
                <td>
                  {device.capabilities
                    .map((c) => capabilityNames[c])
                    .join("、")}
                </td>
                <td>{device.revoked ? "已撤銷" : "已授權"}</td>
                <td>
                  <button
                    className="secondary"
                    disabled={device.revoked || busy}
                    onClick={(event) => {
                      revokeTrigger.current = event.currentTarget;
                      setSelected(device);
                      setReason("");
                    }}
                  >
                    撤銷授權
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && (
        <form onSubmit={revoke} className="revoke-form">
          <h3>撤銷「{selected.name}」</h3>
          <p>此裝置將立即無法使用中央服務。請核對裝置及原因。</p>
          <label>
            撤銷原因
            <input
              required
              maxLength={500}
              ref={reasonField}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={busy}
            />
          </label>
          <div className="actions">
            <button disabled={busy}>確認撤銷</button>
            <button
              className="secondary"
              type="button"
              onClick={() => {
                setSelected(undefined);
                revokeTrigger.current?.focus();
              }}
            >
              取消
            </button>
          </div>
        </form>
      )}
      <form onSubmit={createPairing} className="pairing-form">
        <h3>配對另一台裝置</h3>
        <p>在新裝置輸入配對碼；能力由此處指定。</p>
        <div className="inline-controls">
          <label>
            新裝置能力
            <select
              value={capability}
              onChange={(e) => setCapability(e.target.value as Capability)}
              disabled={busy}
            >
              <option value="physician">醫師</option>
              <option value="reporting">回報管理</option>
              <option value="admin">管理者</option>
            </select>
          </label>
          <button disabled={busy}>建立配對碼</button>
        </div>
        {code && (
          <div className="pairing-result">
            <label>
              配對碼
              <input readOnly value={code} autoComplete="off" />
            </label>
            <p>
              有效至 {new Date(expiresAt * 1000).toLocaleTimeString("zh-TW")}
              ，限使用一次。請僅交給受授權的裝置操作者。
            </p>
          </div>
        )}
      </form>
    </section>
  );
}
