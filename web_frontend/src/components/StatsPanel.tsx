import { AlertTriangle, BarChart3, Maximize2, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import type { ClassStats, DatasetStats, ImageItem, ImageStats } from "../types";

type Props = {
  stats: DatasetStats | null;
  loading: boolean;
  onRefresh: () => void;
  onImageSelect: (image: ImageItem) => void;
};

const T = {
  title: "全数据集类别统计",
  expand: "展开统计",
  refresh: "扫描全数据集",
  loading: "统计中...",
  empty: "点击刷新，扫描全数据集中每一类的目标框数和主轴标注数。",
  overview: "数据集总览",
  quickCounts: "每类目标框数 / 主轴数",
  classCounts: "详细类别统计",
  yawDist: "Yaw 状态分布",
  issueImages: "问题图片",
  className: "类别",
  images: "图片",
  bboxCount: "目标框",
  axisCount: "主轴数",
  yawValid: "yaw有效",
  share: "占比",
  errors: "错误",
  warnings: "警告",
  annotated: "已标图片",
  unannotated: "未标图片",
  emptyImages: "空标注",
  classes: "类别",
  totalImages: "总图片",
  totalRoi: "总目标框",
  totalAxis: "总主轴标注",
  totalErrors: "总错误",
  totalWarnings: "总警告",
  noData: "暂无数据"
};

const YAW_STATUSES = ["valid", "not_required", "ambiguous", "occluded", "optional"] as const;
const OCCLUSIONS = [0, 1, 2, 3] as const;
const DIFFICULTIES = ["easy", "medium", "hard"] as const;

function fmt(value: number | null | undefined, digits = 1) {
  return value == null || Number.isNaN(value) ? "-" : value.toFixed(digits);
}

function pct(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? "-" : `${(value * 100).toFixed(1)}%`;
}

function rowStatusClass(cls: ClassStats) {
  if (cls.error_count > 0) return "bad";
  if (cls.warning_count > 0 || cls.object_count === 0) return "warn";
  if (cls.graspable && cls.yaw_valid_count === 0 && cls.object_count > 0) return "warn";
  return "ok";
}

function StatsOverview({ stats }: { stats: DatasetStats }) {
  return (
    <>
      <div className="stats-subtitle">{T.overview}</div>
      <div className="stats-kpi-grid stats-kpi-grid-wide">
        <div><strong>{stats.dataset.image_count}</strong><span>{T.totalImages}</span></div>
        <div><strong>{stats.dataset.annotated_image_count}</strong><span>{T.annotated}</span></div>
        <div><strong>{stats.dataset.unannotated_image_count}</strong><span>{T.unannotated}</span></div>
        <div><strong>{stats.dataset.empty_image_count}</strong><span>{T.emptyImages}</span></div>
        <div><strong>{stats.dataset.class_count}</strong><span>{T.classes}</span></div>
        <div><strong>{stats.dataset.object_count}</strong><span>{T.totalRoi}</span></div>
        <div><strong>{stats.dataset.axis_count}</strong><span>{T.totalAxis}</span></div>
        <div><strong>{stats.dataset.error_count}</strong><span>{T.totalErrors}</span></div>
        <div><strong>{stats.dataset.warning_count}</strong><span>{T.totalWarnings}</span></div>
      </div>
    </>
  );
}

function CompactClassCounts({ classes }: { classes: ClassStats[] }) {
  return (
    <table className="class-count-table">
      <thead>
        <tr>
          <th>{T.className}</th>
          <th>{T.bboxCount}数</th>
          <th>{T.axisCount}</th>
          <th>{T.yawValid}</th>
        </tr>
      </thead>
      <tbody>
        {classes.map((cls) => (
          <tr key={`count-${cls.class_id}`} className={rowStatusClass(cls)}>
            <td>{cls.class_id}: {cls.class_name}</td>
            <td>{cls.object_count}</td>
            <td>{cls.axis_count}</td>
            <td>{cls.yaw_valid_count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ClassStatsTable({ classes }: { classes: ClassStats[] }) {
  return (
    <div className="class-stats-table-scroll">
      <table className="class-stats-table">
        <thead>
          <tr>
            <th>{T.className}</th>
            <th>{T.images}</th>
            <th>{T.bboxCount}</th>
            <th>{T.axisCount}</th>
            <th>{T.yawValid}</th>
            <th>{T.share}</th>
            {YAW_STATUSES.map((s) => <th key={s}>{s}</th>)}
            {OCCLUSIONS.map((o) => <th key={`occ${o}`}>occ{o}</th>)}
            {DIFFICULTIES.map((d) => <th key={d}>{d}</th>)}
            <th>{T.errors}</th>
            <th>{T.warnings}</th>
          </tr>
        </thead>
        <tbody>
          {classes.map((cls) => (
            <tr key={cls.class_id} className={rowStatusClass(cls)}>
              <td>
                <strong>{cls.class_id}: {cls.class_name}</strong>
                <span>{cls.graspable ? "graspable" : "report-only"}</span>
              </td>
              <td>{cls.image_count}</td>
              <td>{cls.object_count}</td>
              <td>{cls.axis_count}</td>
              <td>{cls.yaw_valid_count}</td>
              <td>{pct(cls.object_share)}</td>
              {YAW_STATUSES.map((s) => (
                <td key={s}>{cls.yaw_status_counts[s] || 0}</td>
              ))}
              {OCCLUSIONS.map((o) => (
                <td key={`occ${o}`}>{cls.occlusion_counts[o] || 0}</td>
              ))}
              {DIFFICULTIES.map((d) => (
                <td key={d}>{cls.difficulty_counts[d] || 0}</td>
              ))}
              <td>{cls.error_count}</td>
              <td>{cls.warning_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function YawDistList({ classes }: { classes: ClassStats[] }) {
  return (
    <div className="stats-class-list">
      {classes.map((cls) => (
        <div key={`yaw-${cls.class_id}`} className={`stats-class-row ${rowStatusClass(cls)}`}>
          <div className="stats-class-head">
            <strong>{cls.class_id}: {cls.class_name}</strong>
            <span>
              yaw_valid {cls.yaw_valid_count}/{cls.object_count}
              {" | "}axis {cls.axis_count}/{cls.object_count}
              {" | "}obb {cls.obb_count}
            </span>
          </div>
          {cls.suggestions.length > 0 ? cls.suggestions.map((item) => (
            <em key={item}><AlertTriangle size={12} /> {item}</em>
          )) : <span>{T.noData}</span>}
        </div>
      ))}
    </div>
  );
}

function IssueImageList({
  issueImages,
  onImageSelect
}: {
  issueImages: ImageStats[];
  onImageSelect: (image: ImageItem) => void;
}) {
  if (issueImages.length === 0) return null;
  return (
    <div className="stats-issue-list">
      <strong>{T.issueImages}</strong>
      {issueImages.map((item) => (
        <button key={item.image_id} type="button" className="stats-issue-row" onClick={() => onImageSelect(item)}>
          <span>{item.image_key}</span>
          <em>{item.error_count}E / {item.warning_count}W</em>
        </button>
      ))}
    </div>
  );
}

export function StatsPanel({ stats, loading, onRefresh, onImageSelect }: Props) {
  const [expanded, setExpanded] = useState(false);
  const issueImages = (stats?.images || [])
    .filter((item) => item.error_count || item.warning_count)
    .slice(0, 10);

  return (
    <>
      <section className="source-block stats-panel">
        <div className="stats-title-row">
          <div className="section-title">{T.title}</div>
          <div className="stats-title-actions">
            <button type="button" onClick={() => setExpanded(true)} disabled={!stats} title={T.expand}>
              <Maximize2 size={16} />
            </button>
            <button type="button" onClick={onRefresh} disabled={loading} title={T.refresh}>
              {loading ? <BarChart3 size={16} /> : <RefreshCw size={16} />}
            </button>
          </div>
        </div>
        {!stats && <p className="stats-empty">{loading ? T.loading : T.empty}</p>}
        {stats && (
          <>
            <div className="stats-subtitle">{T.quickCounts}</div>
            <CompactClassCounts classes={stats.classes} />
            <StatsOverview stats={stats} />
            <div className="stats-subtitle">{T.classCounts}</div>
            <ClassStatsTable classes={stats.classes} />
            <div className="stats-subtitle">{T.yawDist}</div>
            <YawDistList classes={stats.classes} />
            <IssueImageList issueImages={issueImages} onImageSelect={onImageSelect} />
          </>
        )}
      </section>

      {stats && expanded && (
        <div className="modal-backdrop" role="presentation">
          <section className="modal-panel stats-modal" role="dialog" aria-modal="true" aria-label={T.title}>
            <header className="modal-header">
              <div>
                <h2>{T.title}</h2>
                <p>{stats.dataset.image_count} images / {stats.dataset.object_count} 目标框 / {stats.dataset.axis_count} 主轴标注</p>
              </div>
              <div className="modal-header-actions">
                <button type="button" onClick={onRefresh} disabled={loading}>
                  {loading ? <BarChart3 size={16} /> : <RefreshCw size={16} />} {T.refresh}
                </button>
                <button type="button" title="Close" onClick={() => setExpanded(false)}>
                  <X size={16} />
                </button>
              </div>
            </header>
            <div className="stats-modal-body">
              <div className="stats-subtitle">{T.quickCounts}</div>
              <CompactClassCounts classes={stats.classes} />
              <StatsOverview stats={stats} />
              <div className="stats-subtitle">{T.classCounts}</div>
              <ClassStatsTable classes={stats.classes} />
              <div className="stats-subtitle">{T.yawDist}</div>
              <YawDistList classes={stats.classes} />
              <IssueImageList issueImages={issueImages} onImageSelect={onImageSelect} />
            </div>
          </section>
        </div>
      )}
    </>
  );
}
