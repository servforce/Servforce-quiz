import {
  MCP_CAPABILITY_GROUPS,
  MCP_FLOW_STEPS,
  MCP_SECURITY_RULES,
  createCandidateResumeUploadState,
  createCandidateResumeReparseState,
} from "./constants.js";

function formatLocalDateYmd(date) {
  const value = date instanceof Date ? new Date(date.getTime()) : new Date(date || Date.now());
  if (Number.isNaN(value.getTime())) return "";
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localDateOffsetYmd(offsetDays = 0) {
  const value = new Date();
  value.setHours(0, 0, 0, 0);
  value.setDate(value.getDate() + Number(offsetDays || 0));
  return formatLocalDateYmd(value);
}

export function createAdminState() {
  const todayYmd = localDateOffsetYmd(0);
  const sixDaysAgoYmd = localDateOffsetYmd(-6);
  const tomorrowYmd = localDateOffsetYmd(1);
  return {
booting: true,
error: "",
notice: "",
notices: [],
noticeSeq: 0,
session: { authenticated: false, username: "" },
route: { name: "login", path: "/admin/login", fullPath: "/admin/login", search: "", query: {}, title: "管理员登录", section: "Login", params: {} },
navItems: [
  { href: "/admin/quizzes", label: "测验", icon: "library_books" },
  { href: "/admin/quiz-analytics", label: "测验分析", icon: "analytics" },
  { href: "/admin/candidates", label: "候选人", icon: "group" },
  { href: "/admin/assignments", label: "邀约与答题", icon: "assignment" },
  { href: "/admin/logs", label: "系统日志", icon: "receipt_long" },
  { href: "/admin/status", label: "系统状态", icon: "monitoring" },
  { href: "/admin/mcp", label: "MCP", iconKind: "mcp" },
],
loginForm: { username: "", password: "" },
filters: {
  quizzes: { q: "" },
  quizAnalytics: { q: "", start_date: "", end_date: "" },
  candidates: { q: "" },
  assignments: { q: "", start_from: sixDaysAgoYmd, end_to: todayYmd },
},
syncForm: { repoUrl: "" },
repoBinding: {},
rebindForm: { open: false, repoUrl: "", confirmationText: "" },
candidateForm: { name: "", phone: "" },
candidateResumeUploadState: createCandidateResumeUploadState(),
candidateResumeReparseState: createCandidateResumeReparseState(),
candidateResumeUploadPollTimer: null,
candidateResumeUploadPollIntervalMs: 1500,
candidateResumeReparsePollTimer: null,
candidateResumeReparsePollIntervalMs: 1500,
candidateEvaluation: "",
assignmentForm: {
  quiz_key: "",
  candidate_id: "",
  invite_start_date: todayYmd,
  invite_end_date: tomorrowYmd,
  require_phone_verification: false,
  ignore_timing: false,
},
assignmentSelect: {
  quiz: { open: false, query: "" },
  candidate: { open: false, query: "" },
},
quizzes: { items: [] },
quizDetail: { quiz: {}, selected_quiz_version: {}, quiz_version_history: [], stats: {} },
quizAnalytics: { items: [], page: 1, per_page: 20, total: 0, total_pages: 1, filters: { q: "" } },
quizAnalyticsDetail: { quiz: {}, filters: {}, summary: {}, distribution_groups: [], items: [] },
candidates: { items: [] },
candidateDetail: { candidate: {}, profile: {}, resume_parsed: {} },
assignments: { items: [], summary: { unhandled_finished_count: 0 }, page: 1, per_page: 20, total: 0, total_pages: 1 },
attemptDetail: { assignment: {}, quiz_paper: {}, archive: {}, review: { answers: [], evaluation: {} } },
logs: { items: [], counts: {}, trend: { days: [], series: {} } },
logsChart: null,
logsChartContainer: null,
logsChartSeries: {},
logsChartResizeObserver: null,
logsChartWindowResize: null,
isAdminCompactLayout: false,
adminCompactTabsState: {},
adminCompactMediaQuery: null,
adminCompactMediaQueryHandler: null,
adminCompactScrollHandler: null,
syncState: {},
syncPollTimer: null,
syncPollIntervalMs: 2000,
assignmentsPollTimer: null,
assignmentsPollIntervalMs: 3000,
assignmentStatusSnapshot: {},
statusSummary: {},
statusRange: { data: {} },
statusConfig: { llm_tokens_limit: "", sms_calls_limit: "" },
systemBootstrap: {},
mcpSummary: {},
mcpTokenVisible: false,
mcpCapabilityGroups: MCP_CAPABILITY_GROUPS,
mcpFlowSteps: MCP_FLOW_STEPS,
mcpSecurityRules: MCP_SECURITY_RULES,
    fragmentCache: {},
  };
}
