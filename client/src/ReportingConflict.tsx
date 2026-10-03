import type { components } from "./generated/api";

export type Conflict = {
  caseId?: string;
  currentRevision: number;
  differences: Record<string, unknown>;
};
export function readConflict(error: unknown): Conflict {
  const body = error as { detail?: Partial<Conflict> };
  const detail = body?.detail;
  if (
    typeof detail?.currentRevision !== "number" ||
    !detail.differences ||
    typeof detail.differences !== "object"
  )
    throw new Error("Invalid conflict response");
  return {
    caseId: detail.caseId,
    currentRevision: detail.currentRevision,
    differences: detail.differences,
  };
}

export function ReportingConflict({
  conflict,
  before,
  draft,
}: {
  conflict: Conflict;
  before: components["schemas"]["CaseView"];
  draft: Record<string, unknown>;
}) {
  const fields = [
    ["reportedQuantity", "實發數量"],
    ["lots", "批號分攤"],
    ["excluded", "排除狀態"],
    ["reason", "用藥理由"],
    ["exclusionReason", "排除／納入原因"],
    ["status", "案件狀態"],
    ["latestSourceSnapshot", "最新來源版本"],
  ];
  return (
    <section aria-label="回報資料衝突">
      <h4>請核對這筆案件的變更</h4>
      <p>
        {before.patientName}／{before.chartNumber}／{before.sourceOrder}
        ；讀取版本 {before.revision}，中央版本 {conflict.currentRevision}
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>欄位</th>
              <th>讀取時</th>
              <th>中央目前</th>
              <th>本次草稿</th>
            </tr>
          </thead>
          <tbody>
            {fields.map(([field, label]) => (
              <tr key={field}>
                <th>{label}</th>
                <td>
                  {display(
                    (before as unknown as Record<string, unknown>)[field],
                  )}
                </td>
                <td>{display(conflict.differences[field])}</td>
                <td>{field in draft ? display(draft[field]) : "未修改"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>尚未覆寫；請重新讀取，再核對本次決定。</p>
    </section>
  );
}

function display(value: unknown): string {
  if (value === "outside_completed") return "系統外已完成";
  if (value === null) return "未填";
  if (value === undefined) return "未提供";
  if (typeof value === "boolean") return value ? "已排除" : "未排除";
  if (Array.isArray(value))
    return (
      value
        .map((item) => String(item.lot) + "：" + String(item.quantity) + " 顆")
        .join("、") || "未填"
    );
  return String(value);
}
