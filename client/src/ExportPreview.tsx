import { useEffect, useRef, useState } from "react";
import { clinicApi, requireData } from "./api";
import type { components } from "./generated/api";

type Preview = components["schemas"]["ExportPreview"];
const messages: Record<string, string> = {
  excluded: "已排除，不納入匯出選取",
  reason_missing: "未填用藥理由",
  lots_missing: "未填批號分攤",
  lot_total_mismatch: "批號分攤合計不等於回報數量",
  quantity_out_of_range: "回報數量超出來源範圍",
  source_unresolved: "來源仍在隔離，等待處理",
  source_review_required: "HIS 異動尚待人工核對",
  source_changed: "來源有異動，請回案件工作清單核對",
  duplicate_concern: "同病人同日多筆醫令，請人工確認，系統不合併",
  official_required_fields_unverified: "官方必填與條件必填規則尚未驗證",
  official_quantity_rules_unverified: "官方投藥劑量／數量格式尚未驗證",
  official_lot_rules_unverified: "官方多批號拆列規則尚未驗證",
  live_source_unverified: "實際 HIS 契約尚未完成驗證",
  mapping_unassigned: "此來源快照尚無映射版本引用",
};

export function ExportPreviewPanel({
  api,
}: {
  api: ReturnType<typeof clinicApi>;
}) {
  const [view, setView] = useState<Preview>();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const applied = useRef({ from: "", to: "" });
  async function load(
    bounds: { from: string; to: string },
    selected?: string[],
  ) {
    const current = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const dates = {
        dateFrom: bounds.from || undefined,
        dateTo: bounds.to || undefined,
      };
      const data = requireData(
        selected === undefined
          ? await api.GET("/api/v1/export-preview", {
              params: { query: dates },
            })
          : await api.POST("/api/v1/export-preview", {
              body: { ...dates, selected },
            }),
      );
      if (current !== generation.current) return;
      applied.current = bounds;
      setView(data);
    } catch {
      if (current === generation.current) {
        setView(undefined);
        setError(
          "預覽讀取失敗。請確認日期範圍與裝置權限後重新查詢；舊預覽不能當成匯出依據。",
        );
      }
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  useEffect(() => {
    void load({ from: "", to: "" });
    return () => {
      generation.current++;
    };
  }, [api]);
  function select(caseId: string, checked: boolean) {
    if (!view || busy) return;
    const ids = view.items
      .filter((item) => item.selected && item.case.caseId !== caseId)
      .map((item) => item.case.caseId);
    if (checked) ids.push(caseId);
    void load(applied.current, ids);
  }
  return (
    <section aria-label="匯出前核對">
      <h2>匯出前核對</h2>
      <p>
        預覽只供核對。內部完整不等於正式可匯出；勾選也不會產生 Excel
        或記錄上傳。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void load({ from, to });
        }}
      >
        <fieldset disabled={busy}>
          <legend>給藥日期範圍（留空為全部）</legend>
          <label>
            預覽起日
            <input
              type="date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
            />
          </label>
          <label>
            預覽迄日
            <input
              type="date"
              value={to}
              onChange={(event) => setTo(event.target.value)}
            />
          </label>
          <button type="submit">重新查詢並套用預設選取</button>
        </fieldset>
      </form>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">正在由中央重新檢查資料與選取…</p>}
      {view && (
        <>
          <p role="status">
            內部完整 {view.internallyCompleteCount} 筆；目前選取{" "}
            {view.selectedCount} 筆
          </p>
          <p>已選資料仍須通過官方規則與所有 M0 證據。正式匯出目前不可用。</p>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void load(applied.current, [])}
          >
            清除選取
          </button>
          <button disabled>產生正式 Excel</button>{" "}
          <button disabled>下載正式 Excel</button>
          <h3>正式匯出阻擋項</h3>
          <p>
            環境啟用旗標：
            {view.operationalFlagEnabled
              ? "已開啟，但不能取代驗證證據"
              : "關閉"}
          </p>
          <ul>
            {view.gates.map((gate) => (
              <li key={gate.key}>
                {gate.status}：{gate.label}
              </li>
            ))}
          </ul>
          {view.items.length === 0 ? (
            <p>此範圍沒有案件。</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>選取</th>
                    <th>病人／醫令</th>
                    <th>給藥日期</th>
                    <th>回報數量與批號</th>
                    <th>核對結果</th>
                  </tr>
                </thead>
                <tbody>
                  {view.items.map((item) => (
                    <tr key={item.case.caseId}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`選取 ${item.case.sourceOrder}`}
                          checked={item.selected}
                          disabled={busy || item.case.excluded}
                          onChange={(event) =>
                            select(item.case.caseId, event.target.checked)
                          }
                        />
                      </td>
                      <td>
                        {item.case.patientName}
                        <br />
                        {item.case.chartNumber}
                        <br />
                        {item.case.sourceOrder}
                      </td>
                      <td>{item.case.reportingDate}</td>
                      <td>
                        {item.case.reportedQuantity} 顆
                        <ul>
                          {item.case.lots?.map((lot) => (
                            <li key={lot.lot}>
                              {lot.lot}：{lot.quantity} 顆
                            </li>
                          ))}
                        </ul>
                      </td>
                      <td>
                        <p>
                          {item.case.internallyComplete
                            ? "內部資料完整"
                            : "內部資料待核對"}
                          ；正式匯出受阻
                        </p>
                        <ul>
                          {[
                            ...item.internalIssues,
                            ...item.warnings,
                            ...item.officialBlockers,
                          ].map((code) => (
                            <li key={code}>{messages[code] ?? code}</li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
