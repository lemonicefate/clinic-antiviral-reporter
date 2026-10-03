import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { components } from "./generated/api";

type UpdateState = {
  enabled: boolean;
  currentVersion: string;
  available: components["schemas"]["ReleaseView"] | null;
  planToken: string | null;
  preparedVersion: string | null;
  rollbackVersion: string | null;
  recoveryAvailable: boolean;
};

export function UpdatePanel({ connectionEpoch }: { connectionEpoch: string }) {
  const [state, setState] = useState<UpdateState>();
  const [working, setBusy] = useState(false);
  const [backgroundChecking, setBackgroundChecking] = useState(false);
  const checking = useRef<Promise<UpdateState> | null>(null);
  const busy = working || backgroundChecking;
  const [confirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const sending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    const current = ++generation.current;
    setConfirmed(false);
    void (async () => {
      try {
        const local = await invoke<UpdateState>("update_state");
        if (current !== generation.current) return;
        setState(local);
        if (!local.enabled || sending.current) return;
        // A connection change must wait for the previous native check to release
        // its lock, then check the new connection rather than reuse stale metadata.
        if (checking.current) {
          try { await checking.current; } catch { /* the current check reports errors */ }
        }
        if (current !== generation.current || sending.current) return;
        const pending = invoke<UpdateState>("check_updates");
        checking.current = pending;
        setBackgroundChecking(true);
        try {
          const checked = await pending;
          if (current === generation.current) setState(checked);
        } finally {
          if (checking.current === pending) {
            checking.current = null;
            if (mounted.current) setBackgroundChecking(false);
          }
        }
      } catch {
        // Startup checks stay unobtrusive and do not hide a retained recovery plan.
        if (current === generation.current) setNotice("更新檢查未完成；可稍後重試，或使用已保留的回復工具。");
      }
    })();
    return () => { generation.current++; };
  }, [connectionEpoch]);

  async function perform(command: string, args?: Record<string, unknown>) {
    if (sending.current || checking.current) return;
    sending.current = true;
    const current = ++generation.current;
    setBusy(true);
    setConfirmed(false);
    setNotice("");
    try {
      const result = await invoke<UpdateState | undefined>(command, args);
      if (current !== generation.current) return;
      if (result) setState(result);
      if (command === "prepare_update") setNotice("新版本與回復包均已驗證及保存。請在結束本次使用後再安裝。");
    } catch (error) {
      if (current === generation.current) setNotice(typeof error === "string" ? error : "更新操作未完成；目前程式保持開啟，請稍後重試。");
    } finally {
      sending.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <details className="update-panel">
    <summary>程式更新與回復{state?.available ? ` · 有新版本 ${state.available.version}` : ""}</summary>
    <p>目前版本：{state?.currentVersion ?? "讀取中"}。更新只在你確認後安裝，請先儲存工作。</p>
    {state && !state.enabled && <p>本安裝版本尚未啟用安全更新，請聯絡管理者。</p>}
    <div className="actions">
      <button type="button" className="secondary" disabled={busy || !state?.enabled}
        onClick={() => void perform("check_updates")}>檢查更新</button>
      {state?.available && <button type="button" disabled={busy}
        onClick={() => void perform("prepare_update", { expectedVersion: state.available!.version })}>
        下載並驗證更新與回復包</button>}
      {state?.recoveryAvailable && <button type="button" className="secondary" disabled={busy}
        onClick={() => void perform("open_update_recovery")}>開啟回復工具資料夾</button>}
    </div>
    {state?.available?.notes && <p>{state.available.notes}</p>}
    {(state?.preparedVersion || state?.rollbackVersion) && <>
      <label className="check-label"><input type="checkbox" checked={confirmed} disabled={busy}
        onChange={(event) => setConfirmed(event.target.checked)} />我已儲存所有工作，現在可以結束回報工具</label>
      <div className="actions">
        {state.preparedVersion && <button type="button" disabled={busy || !confirmed}
          onClick={() => void perform("install_update", { token: state.planToken, confirmed, rollback: false })}>
          結束程式並安裝 {state.preparedVersion}</button>}
        {state.rollbackVersion && <button type="button" disabled={busy || !confirmed}
          onClick={() => void perform("install_update", { token: state.planToken, confirmed, rollback: true })}>
          結束程式並回復 {state.rollbackVersion}</button>}
      </div>
      <p>若新版本無法開啟，可從回復工具資料夾執行 recovery.exe。中央案件與資料庫不會回復舊版。</p>
      <p>安裝結束後，請從 Windows 開始功能表重新開啟回報工具。</p>
    </>}
    <p role="status">{busy ? "正在處理更新，請稍候…" : notice}</p>
  </details>;
}
