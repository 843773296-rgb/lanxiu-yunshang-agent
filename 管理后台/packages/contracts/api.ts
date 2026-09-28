// 从 packages/contracts/openapi.json 生成 —— **不要手改**。
// 改契约请改 services/api/app/contract/,然后 `make gen`。
//
// ⚠️ 这里**只有信封、路径和权限**,没有业务字段 —— 因为契约还没登记
// 每条接口的请求体形状。硬编一份出来的话,那份类型会看起来很完整,
// 而它描述的是猜的形状。**一份看起来完整的假类型,比一份明显不完整的真类型危险。**

/* ── 信封 ─────────────────────────────────────────── */

/** 分页列表。`total` 未知时是 `null` —— **不是 0**(0 会被读成「一条都没有」)。 */
export interface ListEnvelope<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}

/** 异步受理。**不会返回「已完成」来冒充同步执行**;去 status_url 看进度。 */
export interface AsyncAccepted {
  job_id: string;
  status: "排队中" | "执行中" | "已完成" | "失败" | "取消请求中" | "已取消" | "状态待核实";
  resource_id: string | null;
  status_url: string;
  trace_id: string | null;
}

/** 统一错误。`advice` 必填 —— 一个只说「失败了」的错误,和没有提示是一回事。 */
export interface ApiError {
  code: string;
  message: string;
  field_errors: Record<string, string>;
  /** 能不能重试由服务端说 —— 客户端猜错的两个方向代价都很大。 */
  retryable: boolean;
  trace_id: string | null;
  /** 下一步该干什么。 */
  advice: string;
}

/* ── 角色与能力(和权限矩阵同源)────────────────────── */

export type Role = "viewer" | "editor" | "annotator" | "trainer" | "approver" | "admin";

export const ROLE_LABEL: Record<Role, string> = {
  viewer: "查看者",
  editor: "编辑 / 知识运营",
  annotator: "标注 / 测试",
  trainer: "训练操作员",
  approver: "审核发布者",
  admin: "管理员",
};

export type Capability =
  | "查看有权配置"
  | "改 Prompt/知识候选"
  | "改训练样本"
  | "运行评测"
  | "提交真实训练"
  | "生产审核/发布/回滚"
  | "查看敏感输入/独立测试答案"
  | "配置密钥与预算"
  | "查看审计"
  | "改编排草稿"
  | "运行编排测试"
  | "审批工具动作";

/* ── 接口:路径 + 它要的权限 ───────────────────────── */

/** 每条接口要哪条权限 —— **前端据此决定按钮显示成「无权」还是隐藏**,
  * 但**授权由服务端每次请求执行**:前端藏起来不等于挡住了。 */
export interface EndpointSpec {
  method: string;
  path: string;
  summary: string;
  capability: Capability;
  /** 部分字段要额外授权才返回(如 trace 原文、独立测试答案)。 */
  fieldCapabilities: Capability[];
  /** 异步动作:返回 202 + AsyncAccepted,不要指望它直接给结果。 */
  isAsync: boolean;
  /** 要 Idempotency-Key 请求头。 */
  needsIdempotencyKey: boolean;
  /** 要 If-Match 请求头(拿列表/详情里的 revision 填)。 */
  needsIfMatch: boolean;
}

export const API_PREFIX = "/api/v1/projects/{project_id}";

export const ENDPOINTS = [
  { method: "GET", path: "/model-connections", summary: "模型连接列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/model-connections", summary: "建模型连接", capability: "配置密钥与预算", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/model-connections/{id}/probe", summary: "探测连接", capability: "配置密钥与预算", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/prompts", summary: "Prompt 列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/prompts", summary: "建 Prompt", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "PATCH", path: "/prompts/{id}/draft", summary: "改草稿", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: true },
  { method: "POST", path: "/prompts/{id}/versions", summary: "从草稿发正式版本", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/prompt-runs", summary: "Prompt 调试跑一次", capability: "运行评测", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/runs/{id}", summary: "看一次运行", capability: "查看有权配置", fieldCapabilities: ["查看敏感输入/独立测试答案"], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/uploads", summary: "要一个受限上传地址", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "PUT", path: "/uploads/{id}/bytes", summary: "把字节传上来", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/uploads/{id}/complete", summary: "上传完成,服务端校验", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/uploads", summary: "上传列表(含校验失败的)", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/knowledge-bases", summary: "知识库列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/knowledge-bases", summary: "建知识库", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/knowledge-bases/{id}/documents", summary: "加资料", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/documents/{id}/versions", summary: "发文档新版本", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/document-versions/{id}/revisions", summary: "改片段(出新候选)", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/knowledge-bases/{id}/index-builds", summary: "某个知识库的索引构建", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/knowledge-bases/{id}/index-builds", summary: "建索引", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "POST", path: "/retrieval-tests", summary: "检索实验室跑一次", capability: "运行评测", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/datasets", summary: "数据集列表", capability: "查看有权配置", fieldCapabilities: ["查看敏感输入/独立测试答案"], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/datasets", summary: "建数据集", capability: "改训练样本", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "PATCH", path: "/datasets/{id}/samples/{sample_id}", summary: "改样本", capability: "改训练样本", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: true },
  { method: "POST", path: "/datasets/{id}/versions", summary: "冻结数据集", capability: "改训练样本", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/training-jobs", summary: "训练任务列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/training-jobs", summary: "提交训练", capability: "提交真实训练", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/training-jobs/{id}", summary: "训练详情", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/training-jobs/{id}/cancel", summary: "请求取消", capability: "提交真实训练", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/model-artifacts", summary: "产物列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/model-artifacts", summary: "登记产物", capability: "提交真实训练", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/deployments", summary: "部署产物", capability: "生产审核/发布/回滚", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "POST", path: "/feedback", summary: "应用层上报一次人工判读", capability: "运行评测", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/agent-health", summary: "智能体健康(采纳率)", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/evaluations", summary: "评测列表", capability: "查看有权配置", fieldCapabilities: ["查看敏感输入/独立测试答案"], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/evaluations/compare", summary: "实验对比(同一套题两个版本并排)", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/evaluations", summary: "建评测", capability: "运行评测", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "POST", path: "/evaluations/{id}/reviews", summary: "人工复核", capability: "运行评测", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/applications", summary: "应用列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/applications", summary: "建应用", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "PATCH", path: "/applications/{id}/draft", summary: "改应用候选配置", capability: "改 Prompt/知识候选", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: true },
  { method: "POST", path: "/applications/{id}/releases", summary: "出发布候选(冻结依赖)", capability: "生产审核/发布/回滚", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/releases/{id}/reviews", summary: "审核发布", capability: "生产审核/发布/回滚", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/releases/{id}/deploy", summary: "发布(切环境指针)", capability: "生产审核/发布/回滚", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: true },
  { method: "POST", path: "/applications/{id}/rollbacks", summary: "回滚到历史清单", capability: "生产审核/发布/回滚", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "POST", path: "/applications/{id}/runs", summary: "按环境绑定执行", capability: "查看有权配置", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/traces", summary: "运行记录列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/traces/{id}", summary: "运行详情(脱敏)", capability: "查看有权配置", fieldCapabilities: ["查看敏感输入/独立测试答案"], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/jobs/{id}", summary: "任务详情", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/jobs/{id}/events", summary: "任务事件(SSE)", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/model-calls", summary: "应用层上报一次模型调用", capability: "运行评测", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/usage", summary: "用量与成本", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/budgets", summary: "预算", capability: "配置密钥与预算", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/budgets", summary: "设预算", capability: "配置密钥与预算", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/memberships", summary: "成员与权限", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/memberships", summary: "加成员/改权限", capability: "配置密钥与预算", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/audit-events", summary: "审计记录", capability: "查看审计", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/workflows", summary: "工作流列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/workflows", summary: "建工作流", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/workflows/{id}", summary: "工作流详情", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "PATCH", path: "/workflows/{id}/draft", summary: "改图草稿", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: true },
  { method: "POST", path: "/workflows/{id}/validate", summary: "校验图", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/workflows/{id}/versions", summary: "冻结图版本", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/agents", summary: "Agent 列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/agents", summary: "建 Agent", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/agents/{id}", summary: "Agent 详情", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "PATCH", path: "/agents/{id}/draft", summary: "改 Agent 草稿", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: true },
  { method: "POST", path: "/agents/{id}/validate", summary: "校验 Agent", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/agents/{id}/versions", summary: "冻结 Agent 版本", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/tools", summary: "工具目录", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/tools", summary: "注册工具", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "PATCH", path: "/tools/{id}/draft", summary: "改工具草稿", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: true },
  { method: "POST", path: "/tools/{id}/versions", summary: "冻结工具版本", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/capability-connections", summary: "工具连接列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/capability-connections", summary: "建工具连接", capability: "配置密钥与预算", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/skills", summary: "Skill 指南列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/skills", summary: "建 Skill 指南", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/skills/{id}/versions", summary: "冻结指南版本", capability: "改编排草稿", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/policies", summary: "规则策略列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/policies", summary: "建规则策略", capability: "配置密钥与预算", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/execution-runs", summary: "发起一次运行", capability: "运行编排测试", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "POST", path: "/node-tests", summary: "从选中节点测试", capability: "运行编排测试", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/execution-runs", summary: "运行列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/execution-runs/{id}", summary: "运行详情", capability: "查看有权配置", fieldCapabilities: ["查看敏感输入/独立测试答案"], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/execution-runs/{id}/events", summary: "运行事件(SSE)", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/execution-runs/{id}/pause", summary: "请求暂停", capability: "运行编排测试", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: true },
  { method: "POST", path: "/execution-runs/{id}/resume", summary: "继续", capability: "运行编排测试", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: true },
  { method: "POST", path: "/execution-runs/{id}/cancel", summary: "请求取消", capability: "运行编排测试", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: true },
  { method: "POST", path: "/execution-runs/{id}/reconcile", summary: "核实外部状态", capability: "运行编排测试", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "POST", path: "/execution-runs/{id}/steps/{step_id}/retry", summary: "安全重试这一步", capability: "运行编排测试", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "POST", path: "/execution-runs/{id}/fork-test", summary: "从历史点另开调试", capability: "运行编排测试", fieldCapabilities: [], isAsync: true, needsIdempotencyKey: true, needsIfMatch: false },
  { method: "GET", path: "/human-requests", summary: "人工待办列表", capability: "查看有权配置", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "GET", path: "/human-requests/{id}", summary: "待办详情", capability: "查看有权配置", fieldCapabilities: ["查看敏感输入/独立测试答案"], isAsync: false, needsIdempotencyKey: false, needsIfMatch: false },
  { method: "POST", path: "/human-requests/{id}/decisions", summary: "处理待办", capability: "审批工具动作", fieldCapabilities: [], isAsync: false, needsIdempotencyKey: true, needsIfMatch: true },
] as const satisfies readonly EndpointSpec[];

/** 共 94 条接口 · 19 条异步 · 22 条要幂等键 · 11 条要 If-Match */
