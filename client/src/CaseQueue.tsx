import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { clinicApi, requireData } from "./api";
import type { Session } from "./api";
import type { components } from "./generated/api";
import { ReasonEditor } from "./ReasonEditor";
import { ReportingEditor } from "./ReportingEditor";
import { BulkLotEditor } from "./BulkLotEditor";

type Queue = components["schemas"]["QueueView"];
type Detail = components["schemas"]["CaseDetail"];

export function CaseQueue({
  api,
  session,
}: {
  api: ReturnType<typeof clinicApi>;
  session: Session;
}) {
  const reporting = session.capabilities.includes("reporting");
  const initialPhysician = reporting ? "" : session.operator;
  const [physician, setPhysician] = useState(initialPhysician);
  const [caseStatus, setCaseStatus] = useState<
    | "active"
    | "all"
    | "unfinished"
    | "excluded"
    | "awaiting_reason"
    | "awaiting_reconciliation"
    | "internally_complete"
  >("active");
  const [exception, setException] = useState<
    "all" | "duplicate" | "overdue" | "quantity_changed"
  >("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [chart, setChart] = useState("");
  const [queue, setQueue] = useState<Queue>();
  const [detail, setDetail] = useState<Detail>();
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const pendingRefresh = useRef<
    { requestId: string; expectedRevision: number } | undefined
  >(undefined);

  useEffect(() => {
    void load(initialPhysician, "");
    return () => {
      generation.current += 1;
      detailGeneration.current += 1;
    };
  }, [api]);
  useEffect(() => {
    if (detail) heading.current?.focus();
  }, [detail]);

  async function load(selected = physician, exactChart = chart) {
    const current = ++generation.current;
    detailGeneration.current += 1;
    setDetail(undefined);
    setSelected([]);
    setQueue(undefined);
    setStatus("");
    setBusy(true);
    setError("");
    try {
      const data = requireData(
        await api.GET("/api/v1/cases", {
          params: {
            query: {
              physician: selected,
              ...(exactChart ? { chart: exactChart } : {}),
              ...(reporting
                ? {
                    caseStatus,
                    exception,
                    ...(dateFrom ? { dateFrom } : {}),
                    ...(dateTo ? { dateTo } : {}),
                  }
                : {}),
            },
          },
        }),
      );
      if (generation.current === current) {
        setQueue(data);
        return true;
      }
    } catch {
      if (generation.current === current)
        setError("清單讀取失敗，請重新查詢；無法連線時改用紙本流程。");
    } finally {
      if (generation.current === current) setBusy(false);
    }
    return false;
  }

  async function select(caseId: string) {
    const current = ++detailGeneration.current;
    setDetail(undefined);
    setError("");
    setStatus("正在讀取案件…");
    try {
      const data = requireData(
        await api.GET("/api/v1/cases/{case_id}", {
          params: { path: { case_id: caseId } },
        }),
      );
      if (detailGeneration.current === current) {
        setDetail(data);
        setStatus("");
      }
    } catch {
      if (detailGeneration.current === current) {
        setError("案件讀取失敗，請重新選取。");
        setStatus("");
      }
    }
  }

  async function refresh() {
    if (!queue) return;
    setBusy(true);
    setError("");
    const current = generation.current;
    const body = pendingRefresh.current ?? {
      requestId: crypto.randomUUID(),
      expectedRevision: queue.refreshRevision,
    };
    pendingRefresh.current = body;
    try {
      const result = await api.POST("/api/v1/synthetic/refresh", { body });
      if (generation.current !== current) return;
      if (result.response.status === 409) {
        pendingRefresh.current = undefined;
        await load();
        setError("來源刷新版本已變更，已重新讀取。請核對清單後再刷新。");
        return;
      }
      const data = requireData(result);
      if (!("created" in data))
        throw new Error("request replay belongs to another command");
      pendingRefresh.current = undefined;
      await load();
      if (generation.current === current + 1)
        setStatus(
          `合成來源刷新完成：新增 ${data.created} 案，未變 ${data.unchanged} 案。`,
        );
    } catch {
      if (generation.current === current)
        setError("合成來源刷新未完成，請重試。");
    } finally {
      if (generation.current === current) setBusy(false);
    }
  }

  function search(event: FormEvent) {
    event.preventDefault();
    setStatus("");
    void load();
  }

  return (
    <section aria-labelledby="case-queue-title">
      <h2 id="case-queue-title">
        {reporting ? "回報管理清單" : "醫師工作清單"}
      </h2>
      <p className="notice">
        合成資料測試：非真實 HIS。來源鍵與編碼尚未完成真機驗證；正式匯出停用。
      </p>
      <form onSubmit={search} className="queue-filters">
        <label>
          醫師篩選
          <select
            value={physician}
            disabled={busy}
            onChange={(e) => setPhysician(e.target.value)}
          >
            <option value="">全部醫師（協助處理）</option>
            {[
              ...new Set([
                session.operator,
                ...(queue?.physicians ?? []),
                physician,
              ]),
            ]
              .filter(Boolean)
              .map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
          </select>
        </label>
        <label>
          完整病歷號
          <input
            autoComplete="off"
            value={chart}
            disabled={busy}
            maxLength={100}
            onChange={(e) => setChart(e.target.value)}
            placeholder="例如 SYN-0001"
          />
        </label>
        {reporting && (
          <>
            <label>
              狀態篩選
              <select
                aria-label="狀態篩選"
                value={caseStatus}
                disabled={busy}
                onChange={(e) =>
                  setCaseStatus(e.target.value as typeof caseStatus)
                }
              >
                <option value="active">未排除案件</option>
                <option value="all">所有案件</option>
                <option value="unfinished">尚未補齊</option>
                <option value="awaiting_reason">待填理由</option>
                <option value="awaiting_reconciliation">待核對批號</option>
                <option value="internally_complete">內部資料已齊</option>
                <option value="excluded">已排除</option>
              </select>
            </label>
            <label>
              異常篩選
              <select
                aria-label="異常篩選"
                value={exception}
                disabled={busy}
                onChange={(e) =>
                  setException(e.target.value as typeof exception)
                }
              >
                <option value="all">全部</option>
                <option value="duplicate">同日多筆</option>
                <option value="overdue">跨日未完成</option>
                <option value="quantity_changed">來源與實發量不同</option>
              </select>
            </label>
            <label>
              給藥日期起
              <input
                type="date"
                value={dateFrom}
                disabled={busy}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </label>
            <label>
              給藥日期迄
              <input
                type="date"
                value={dateTo}
                disabled={busy}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </label>
          </>
        )}
        <button disabled={busy} type="submit">
          查詢清單
        </button>
      </form>
      <p>
        病歷號採完整相符搜尋，會跨醫師查詢。同日醫令沒有可判定先後的時間，請逐案核對。
      </p>
      {session.capabilities.includes("admin") &&
        queue?.syntheticRefreshEnabled && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void refresh()}
          >
            刷新合成來源
          </button>
        )}
      <p role="status">{busy ? "正在讀取清單…" : status}</p>
      {error && <p role="alert">{error}</p>}
      {queue && (
        <>
          <p>待填理由 {queue.awaitingReason} 案；已填理由仍須完成回報核對。</p>
          <p>
            符合條件 {queue.total} 案 · 跨日未完成 {queue.overdue}{" "}
            案（優先顯示）
          </p>
          {queue.total === 0 ? (
            <p>沒有符合條件的案件。可改選全部醫師，或核對完整病歷號。</p>
          ) : (
            <div className="table-scroll">
              <table>
                <caption>未完成案件；同日排列不代表開立先後</caption>
                <thead>
                  <tr>
                    {reporting && <th>選取</th>}
                    <th>病人／病歷號</th>
                    <th>給藥日期／醫師</th>
                    <th>來源醫令／數量</th>
                    <th>待辦提醒</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.items.map((item) => (
                    <tr key={item.caseId}>
                      {reporting && (
                        <td>
                          <input
                            type="checkbox"
                            aria-label={"選取 " + item.sourceOrder}
                            disabled={item.excluded}
                            checked={selected.includes(item.caseId)}
                            onChange={(e) =>
                              setSelected(
                                e.target.checked
                                  ? [...selected, item.caseId]
                                  : selected.filter((id) => id !== item.caseId),
                              )
                            }
                          />
                        </td>
                      )}
                      <td>
                        <span>{item.patientName}</span>
                        <br />
                        {item.chartNumber}
                      </td>
                      <td>
                        {item.reportingDate}
                        <br />
                        {item.physician}
                      </td>
                      <td>
                        {item.sourceOrder}
                        <br />
                        {item.sourceQuantity} 顆
                      </td>
                      <td>
                        {item.overdue && (
                          <strong>
                            跨日未完成
                            <br />
                          </strong>
                        )}
                        {item.duplicateConcern && (
                          <>
                            同病人同日多筆，請核對
                            <br />
                          </>
                        )}
                        {
                          {
                            awaiting_reason: "待填理由",
                            awaiting_reconciliation: "理由已填，待回報核對",
                            internally_complete: "內部資料已齊；正式匯出停用",
                            excluded: "已排除",
                          }[item.status]
                        }
                      </td>
                      <td>
                        <button onClick={() => void select(item.caseId)}>
                          核對此案
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {reporting && selected.length > 0 && (
            <BulkLotEditor
              key={selected.join(",")}
              api={api}
              cases={queue.items.filter((item) =>
                selected.includes(item.caseId),
              )}
              onSaved={() => {
                const expected = generation.current + 1;
                void load().then((ok) => {
                  if (generation.current === expected)
                    setStatus(
                      ok
                        ? "批次批號已儲存，清單已更新。"
                        : "批次批號已儲存；請重新查詢清單。",
                    );
                });
              }}
            />
          )}
        </>
      )}
      {detail && (
        <section className="case-detail" aria-labelledby="case-detail-title">
          <h2 id="case-detail-title" tabIndex={-1} ref={heading}>
            核對案件
          </h2>
          <p>
            <strong>{detail.patientName}</strong> · 病歷號 {detail.chartNumber}{" "}
            · 出生日期 {detail.birthDate}
          </p>
          <p>
            給藥日期 {detail.reportingDate} · 醫師 {detail.physician} · 醫令{" "}
            {detail.sourceOrder}
          </p>
          <p>
            來源量 {detail.sourceQuantity} 顆；回報量 {detail.reportedQuantity}{" "}
            顆
          </p>
          <p>{detail.material}</p>
          {detail.duplicateConcern && (
            <p className="notice">
              同病人同日另有醫令，請確認這一筆；系統不會自動合併或代選。
            </p>
          )}
          <p>目前理由：{detail.reason ?? "尚未填寫"}</p>
          {reporting && (
            <ReportingEditor
              key={"reporting:" + detail.caseId + ":" + detail.revision}
              api={api}
              detail={detail}
              onReload={setDetail}
              onSaved={() => {
                const expected = generation.current + 1;
                void load().then((ok) => {
                  if (generation.current === expected)
                    setStatus(
                      ok
                        ? "回報核對已儲存，清單已更新。"
                        : "回報核對已儲存；請重新查詢清單。",
                    );
                });
              }}
            />
          )}
          {session.capabilities.some(
            (c) => c === "physician" || c === "reporting",
          ) && (
            <ReasonEditor
              key={`${detail.caseId}:${detail.revision}`}
              api={api}
              detail={detail}
              onReload={setDetail}
              onSaved={() => {
                const expected = generation.current + 1;
                void load().then((ok) => {
                  if (generation.current === expected)
                    setStatus(
                      ok
                        ? "用藥理由已儲存，清單已更新。"
                        : "用藥理由已儲存；清單讀取失敗，請重新查詢。",
                    );
                });
              }}
            />
          )}
          <details>
            <summary>原始合成來源（{detail.snapshots.length} 版）</summary>
            {detail.snapshots.map((snapshot) => (
              <dl key={snapshot.sequence}>
                {Object.entries(snapshot.raw).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            ))}
          </details>
          <button
            className="secondary"
            onClick={() => {
              detailGeneration.current += 1;
              setDetail(undefined);
            }}
          >
            關閉案件
          </button>
        </section>
      )}
    </section>
  );
}
