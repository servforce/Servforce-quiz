const QUIZ_ANALYTICS_WINDOW_OPTIONS = [
  { key: "week", label: "周" },
  { key: "month", label: "月" },
  { key: "half_year", label: "半年" },
  { key: "year", label: "年" },
];

const QUIZ_ANALYTICS_VERSION_SCOPE_OPTIONS = [
  { key: "all", label: "全部版本" },
  { key: "current", label: "当前版本" },
];

const QUIZ_ANALYTICS_LIST_SORT_OPTIONS = [
  { key: "time", label: "时间" },
  { key: "score", label: "得分" },
];

export function createAdminQuizAnalyticsModule() {
  return {
    quizAnalyticsWindowOptions() {
      return QUIZ_ANALYTICS_WINDOW_OPTIONS;
    },

    quizAnalyticsVersionScopeOptions() {
      return QUIZ_ANALYTICS_VERSION_SCOPE_OPTIONS;
    },

    currentQuizAnalyticsWindow() {
      return String(this.route?.query?.window || "month").trim() || "month";
    },

    currentQuizAnalyticsStartDate() {
      return String(this.route?.query?.start_date || "").trim();
    },

    currentQuizAnalyticsEndDate() {
      return String(this.route?.query?.end_date || "").trim();
    },

    currentQuizAnalyticsVersionScope() {
      return String(this.route?.query?.version_scope || "all").trim() || "all";
    },

    currentQuizAnalyticsVersionId() {
      return String(this.route?.query?.version_id || "").trim();
    },

    currentQuizAnalyticsDistributionMode() {
      return "range";
    },

    currentQuizAnalyticsListSortKey() {
      const current = String(this.route?.query?.list_sort || "time").trim().toLowerCase();
      return current === "score" ? "score" : "time";
    },

    currentQuizAnalyticsListSortOrder() {
      const current = String(this.route?.query?.list_order || "desc").trim().toLowerCase();
      return current === "asc" ? "asc" : "desc";
    },

    currentQuizAnalyticsScoreFilter() {
      const scoreMax = Number(this.route?.query?.score_filter_score_max || 0);
      const start = Number(this.route?.query?.score_filter_start || 0);
      const end = Number(this.route?.query?.score_filter_end || 0);
      if (!Number.isFinite(scoreMax) || scoreMax <= 0) return null;
      if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
      if (start < 0 || end < start) return null;
      return {
        scoreMax,
        start,
        end,
      };
    },

    currentQuizAnalyticsKey() {
      return String(this.route?.query?.quiz_key || "").trim();
    },

    quizAnalyticsListSortOptions() {
      return QUIZ_ANALYTICS_LIST_SORT_OPTIONS;
    },

    quizAnalyticsAvailableVersions() {
      return Array.isArray(this.quizAnalyticsDetail?.quiz?.available_versions)
        ? this.quizAnalyticsDetail.quiz.available_versions
        : [];
    },

    shouldShowQuizAnalyticsVersionSelect() {
      return this.currentQuizAnalyticsVersionScope() === "current" && this.quizAnalyticsAvailableVersions().length > 0;
    },

    quizAnalyticsSelectedTitle() {
      return String(this.quizAnalyticsDetail?.quiz?.title || "").trim();
    },

    syncQuizAnalyticsDateInputs(startDate = this.currentQuizAnalyticsStartDate(), endDate = this.currentQuizAnalyticsEndDate()) {
      if (!this.filters?.quizAnalytics) return;
      this.filters.quizAnalytics.start_date = String(startDate || "").trim();
      this.filters.quizAnalytics.end_date = String(endDate || "").trim();
    },

    quizAnalyticsCanApplyCustomDateRange() {
      const startDate = String(this.filters?.quizAnalytics?.start_date || "").trim();
      const endDate = String(this.filters?.quizAnalytics?.end_date || "").trim();
      return Boolean(startDate && endDate && startDate <= endDate);
    },

    quizAnalyticsSummaryCards() {
      const summary = this.quizAnalyticsDetail?.summary || {};
      return [
        { key: "total", label: "答题数量", value: Number(summary.total_attempt_count || 0), tone: "slate" },
        { key: "finished", label: "已完成", value: Number(summary.finished_count || 0), tone: "emerald" },
        { key: "progress", label: "进行中", value: Number(summary.in_progress_count || 0), tone: "amber" },
        { key: "scored", label: "可计分完成", value: Number(summary.scored_finished_count || 0), tone: "blue" },
        { key: "traits", label: "Traits 完成", value: Number(summary.traits_only_finished_count || 0), tone: "violet" },
      ];
    },

    quizAnalyticsCardClass(tone) {
      const key = String(tone || "slate").trim();
      if (key === "emerald") return "border-emerald-100 bg-emerald-50/75";
      if (key === "amber") return "border-amber-100 bg-amber-50/75";
      if (key === "blue") return "border-blue-100 bg-blue-50/75";
      if (key === "violet") return "border-violet-100 bg-violet-50/75";
      return "border-slate-200 bg-slate-50/85";
    },

    quizAnalyticsVersionLabel(item) {
      const versionNo = Number(item?.version_no || 0);
      return versionNo > 0 ? `V${versionNo}` : "未知版本";
    },

    quizAnalyticsStatusBadgeClass(item) {
      const status = String(item?.status || "").trim();
      if (status === "finished") {
        return "rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700";
      }
      if (status === "grading") {
        return "rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-700";
      }
      return "rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-[11px] font-semibold text-sky-700";
    },

    quizAnalyticsSourceBadgeClass(item) {
      if (String(item?.source_kind || "").trim() === "public") {
        return "rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-[11px] font-semibold text-violet-700";
      }
      return "rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-600";
    },

    quizAnalyticsListSortButtonClass(sortKey) {
      const active = this.currentQuizAnalyticsListSortKey() === String(sortKey || "").trim();
      return active
        ? "rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 transition"
        : "rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-blue-200 hover:text-blue-700";
    },

    quizAnalyticsListSortDirectionLabel(sortKey) {
      if (this.currentQuizAnalyticsListSortKey() !== String(sortKey || "").trim()) {
        return "";
      }
      return this.currentQuizAnalyticsListSortOrder() === "asc" ? "↑" : "↓";
    },

    quizAnalyticsHasActiveScoreFilter() {
      return Boolean(this.currentQuizAnalyticsScoreFilter());
    },

    quizAnalyticsScoreFilterLabel() {
      const filter = this.currentQuizAnalyticsScoreFilter();
      if (!filter) return "";
      const rangeLabel = filter.start === filter.end
        ? `${filter.start} 分`
        : `${filter.start}-${filter.end} 分`;
      return `已筛选：满分 ${filter.scoreMax} · ${rangeLabel}`;
    },

    quizAnalyticsVisibleItems() {
      const items = this.quizAnalyticsSortedItems();
      const filter = this.currentQuizAnalyticsScoreFilter();
      if (!filter) return items;
      return items.filter((item) => this.quizAnalyticsItemMatchesScoreFilter(item, filter));
    },

    quizAnalyticsVisibleItemsCount() {
      return this.quizAnalyticsVisibleItems().length;
    },

    quizAnalyticsSortedItems() {
      const items = Array.isArray(this.quizAnalyticsDetail?.items) ? this.quizAnalyticsDetail.items.slice() : [];
      const sortKey = this.currentQuizAnalyticsListSortKey();
      const sortOrder = this.currentQuizAnalyticsListSortOrder();
      const factor = sortOrder === "asc" ? 1 : -1;
      items.sort((left, right) => {
        const primary = this.compareQuizAnalyticsListItems(left, right, sortKey, factor);
        if (primary !== 0) return primary;
        if (sortKey !== "time") {
          const byTime = this.compareQuizAnalyticsListItems(left, right, "time", -1);
          if (byTime !== 0) return byTime;
        }
        if (sortKey !== "score") {
          const byScore = this.compareQuizAnalyticsListItems(left, right, "score", -1);
          if (byScore !== 0) return byScore;
        }
        return Number(right?.attempt_id || 0) - Number(left?.attempt_id || 0);
      });
      return items;
    },

    compareQuizAnalyticsListItems(left, right, sortKey, factor) {
      const leftValue = this.quizAnalyticsListSortValue(left, sortKey);
      const rightValue = this.quizAnalyticsListSortValue(right, sortKey);
      const leftMissing = leftValue === null;
      const rightMissing = rightValue === null;
      if (leftMissing && rightMissing) return 0;
      if (leftMissing) return 1;
      if (rightMissing) return -1;
      if (leftValue === rightValue) return 0;
      return leftValue > rightValue ? factor : -factor;
    },

    quizAnalyticsListSortValue(item, sortKey) {
      if (String(sortKey || "").trim() === "score") {
        const raw = Number(item?.score);
        return Number.isFinite(raw) ? raw : null;
      }
      const timestamp = Date.parse(String(item?.attempt_at || "").trim());
      return Number.isFinite(timestamp) ? timestamp : null;
    },

    quizAnalyticsItemMatchesScoreFilter(item, filter = this.currentQuizAnalyticsScoreFilter()) {
      if (!filter) return true;
      const score = Number(item?.score);
      const scoreMax = Number(item?.score_max);
      if (!Number.isFinite(score) || !Number.isFinite(scoreMax)) return false;
      return scoreMax === filter.scoreMax && score >= filter.start && score <= filter.end;
    },

    quizAnalyticsHasDistribution() {
      return (this.quizAnalyticsDetail?.distribution_groups || []).length > 0;
    },

    quizAnalyticsDistributionGroups() {
      return Array.isArray(this.quizAnalyticsDetail?.distribution_groups)
        ? this.quizAnalyticsDetail.distribution_groups
        : [];
    },

    quizAnalyticsDistributionRows(group) {
      return this.quizAnalyticsRangeRows(group);
    },

    quizAnalyticsRangeRows(group) {
      const scoreMax = Math.max(0, Number(group?.score_max || 0));
      const buckets = Array.isArray(group?.buckets) ? group.buckets : [];
      const countByScore = new Map(
        buckets.map((bucket) => [Number(bucket?.score || 0), Number(bucket?.count || 0)]),
      );
      const rows = [];
      for (let start = 0; start <= scoreMax; start += 10) {
        const end = Math.min(scoreMax, start + 9);
        let count = 0;
        for (let score = start; score <= end; score += 1) {
          count += Number(countByScore.get(score) || 0);
        }
        rows.push({
          kind: "bucket",
          key: `range-${start}-${end}`,
          label: start === end ? `${start} 分` : `${start}-${end} 分`,
          count,
          start,
          end,
        });
      }
      return rows;
    },

    quizAnalyticsDistributionMaxCount(group) {
      const rows = this.quizAnalyticsDistributionRows(group);
      return rows.reduce(
        (max, row) => row?.kind === "bucket" ? Math.max(max, Number(row?.count || 0)) : max,
        0,
      );
    },

    quizAnalyticsDistributionColumnStyle(group, bucket) {
      const maxCount = this.quizAnalyticsDistributionMaxCount(group);
      const count = Number(bucket?.count || 0);
      const percent = maxCount > 0 && count > 0 ? Math.max(8, Math.round((count / maxCount) * 100)) : 0;
      return { height: `${percent}%` };
    },

    quizAnalyticsDistributionColumnButtonClass(group, row) {
      const count = Number(row?.count || 0);
      const active = this.quizAnalyticsDistributionRowIsActive(group, row);
      const widthClass = "w-14";
      if (count <= 0) {
        return `flex ${widthClass} shrink-0 flex-col items-center gap-2 rounded-xl px-1 py-1 text-center opacity-55`;
      }
      if (active) {
        return `flex ${widthClass} shrink-0 flex-col items-center gap-2 rounded-xl border border-blue-200 bg-blue-50/80 px-1 py-1 text-center transition`;
      }
      return `flex ${widthClass} shrink-0 flex-col items-center gap-2 rounded-xl px-1 py-1 text-center transition hover:bg-slate-100/90 cursor-pointer`;
    },

    quizAnalyticsDistributionColumnsClass() {
      return "flex min-w-max items-end gap-2";
    },

    quizAnalyticsDistributionColumnTrackClass(group, row) {
      return this.quizAnalyticsDistributionRowIsActive(group, row)
        ? "flex h-40 w-full items-end overflow-hidden rounded-xl border border-blue-200 bg-white px-1.5 py-1"
        : "flex h-40 w-full items-end overflow-hidden rounded-xl bg-slate-100/85 px-1.5 py-1";
    },

    quizAnalyticsDistributionGapClass() {
      return "flex h-[13.5rem] w-8 shrink-0 flex-col items-center justify-end gap-3 pb-1";
    },

    quizAnalyticsDistributionRowIsActive(group, row) {
      const filter = this.currentQuizAnalyticsScoreFilter();
      if (!filter || row?.kind !== "bucket") return false;
      return Number(group?.score_max || 0) === filter.scoreMax
        && Number(row?.start || 0) === filter.start
        && Number(row?.end || 0) === filter.end;
    },

    resetQuizAnalyticsDetail() {
      this.quizAnalyticsDetail = { quiz: {}, filters: {}, summary: {}, distribution_groups: [], items: [] };
    },

    syncQuizAnalyticsRoute({
      quizKey,
      window,
      startDate,
      endDate,
      versionScope,
      versionId,
      distributionMode,
      listSort,
      listOrder,
      scoreFilter,
    } = {}) {
      const normalizedVersionId = versionId ?? this.currentQuizAnalyticsVersionId() ?? "";
      const normalizedStartDate = startDate ?? this.currentQuizAnalyticsStartDate();
      const normalizedEndDate = endDate ?? this.currentQuizAnalyticsEndDate();
      const activeScoreFilter = scoreFilter === null ? null : (scoreFilter || this.currentQuizAnalyticsScoreFilter());
      this.setRouteSearchParams({
        quiz_key: String(quizKey || "").trim(),
        window: String(window || this.currentQuizAnalyticsWindow()).trim() || "month",
        start_date: String(normalizedStartDate || "").trim(),
        end_date: String(normalizedEndDate || "").trim(),
        version_scope: String(versionScope || this.currentQuizAnalyticsVersionScope()).trim() || "all",
        version_id: String(normalizedVersionId || "").trim(),
        distribution_mode: String(distributionMode || this.currentQuizAnalyticsDistributionMode()).trim() || "range",
        list_sort: String(listSort || this.currentQuizAnalyticsListSortKey()).trim() || "time",
        list_order: String(listOrder || this.currentQuizAnalyticsListSortOrder()).trim() || "desc",
        score_filter_score_max: activeScoreFilter ? String(activeScoreFilter.scoreMax) : "",
        score_filter_start: activeScoreFilter ? String(activeScoreFilter.start) : "",
        score_filter_end: activeScoreFilter ? String(activeScoreFilter.end) : "",
      });
    },

    async loadQuizAnalyticsList({ quiet = false, page = null } = {}) {
      const query = new URLSearchParams();
      const keyword = String(this.filters?.quizAnalytics?.q || "").trim();
      const currentPage = Math.max(1, Number(page || this.quizAnalytics?.page || 1));
      if (keyword) query.set("q", keyword);
      query.set("page", String(currentPage));
      const data = await this.api(`/api/admin/quiz-analytics?${query.toString()}`, { quiet });
      if (!data) return null;
      this.quizAnalytics = data;
      return data;
    },

    async loadQuizAnalyticsDetail(quizKey, { quiet = false, syncRoute = true } = {}) {
      const currentKey = String(quizKey || "").trim();
      if (!currentKey) {
        this.resetQuizAnalyticsDetail();
        return null;
      }
      const window = this.currentQuizAnalyticsWindow();
      const startDate = this.currentQuizAnalyticsStartDate();
      const endDate = this.currentQuizAnalyticsEndDate();
      const versionScope = this.currentQuizAnalyticsVersionScope();
      const versionId = this.currentQuizAnalyticsVersionId();
      const query = new URLSearchParams({
        window,
        version_scope: versionScope,
      });
      if (startDate && endDate) {
        query.set("start_date", startDate);
        query.set("end_date", endDate);
      }
      if (versionScope === "current" && versionId) {
        query.set("version_id", versionId);
      }
      const data = await this.api(`/api/admin/quiz-analytics/${encodeURIComponent(currentKey)}?${query.toString()}`, { quiet });
      if (!data) return null;
      this.quizAnalyticsDetail = data;
      if (syncRoute) {
        this.syncQuizAnalyticsRoute({
          quizKey: currentKey,
          window,
          startDate: String(data?.filters?.start_date || ""),
          endDate: String(data?.filters?.end_date || ""),
          versionScope,
          versionId: String(data?.filters?.version_id || ""),
          distributionMode: this.currentQuizAnalyticsDistributionMode(),
          listSort: this.currentQuizAnalyticsListSortKey(),
          listOrder: this.currentQuizAnalyticsListSortOrder(),
          scoreFilter: this.currentQuizAnalyticsScoreFilter(),
        });
      }
      this.syncQuizAnalyticsDateInputs(
        String(data?.filters?.start_date || ""),
        String(data?.filters?.end_date || ""),
      );
      if (this.route.name === "quiz-analytics" && this.isAdminCompactLayout) {
        await this.setAdminCompactTab("quiz-analytics", "detail", { scroll: true });
      }
      return data;
    },

    async loadQuizAnalyticsPage() {
      await this.loadQuizAnalyticsList({ quiet: true });
      const items = Array.isArray(this.quizAnalytics?.items) ? this.quizAnalytics.items : [];
      const requestedKey = this.currentQuizAnalyticsKey();
      const selected =
        items.find((item) => String(item?.quiz_key || "").trim() === requestedKey)
        || items[0]
        || null;
      if (!selected) {
        this.resetQuizAnalyticsDetail();
        return;
      }
      this.syncQuizAnalyticsDateInputs();
      await this.loadQuizAnalyticsDetail(String(selected.quiz_key || "").trim(), { quiet: true });
    },

    async selectQuizAnalyticsItem(item) {
      const quizKey = String(item?.quiz_key || "").trim();
      if (!quizKey) return;
      await this.loadQuizAnalyticsDetail(quizKey);
    },

    async changeQuizAnalyticsWindow(window) {
      const next = String(window || "").trim();
      if (!next || next === this.currentQuizAnalyticsWindow()) return;
      const quizKey = this.currentQuizAnalyticsKey() || this.quizAnalyticsDetail?.quiz?.quiz_key || "";
      this.syncQuizAnalyticsRoute({
        quizKey,
        window: next,
        startDate: "",
        endDate: "",
        versionScope: this.currentQuizAnalyticsVersionScope(),
        versionId: this.currentQuizAnalyticsVersionId(),
        distributionMode: this.currentQuizAnalyticsDistributionMode(),
        listSort: this.currentQuizAnalyticsListSortKey(),
        listOrder: this.currentQuizAnalyticsListSortOrder(),
        scoreFilter: this.currentQuizAnalyticsScoreFilter(),
      });
      this.syncQuizAnalyticsDateInputs("", "");
      await this.loadQuizAnalyticsDetail(quizKey);
    },

    async changeQuizAnalyticsVersionScope(scope) {
      const next = String(scope || "").trim();
      if (!next || next === this.currentQuizAnalyticsVersionScope()) return;
      const quizKey = this.currentQuizAnalyticsKey() || this.quizAnalyticsDetail?.quiz?.quiz_key || "";
      this.syncQuizAnalyticsRoute({
        quizKey,
        window: this.currentQuizAnalyticsWindow(),
        startDate: this.currentQuizAnalyticsStartDate(),
        endDate: this.currentQuizAnalyticsEndDate(),
        versionScope: next,
        versionId: next === "current"
          ? String(this.quizAnalyticsDetail?.filters?.version_id || this.quizAnalyticsDetail?.quiz?.current_version_id || "")
          : "",
        distributionMode: this.currentQuizAnalyticsDistributionMode(),
        listSort: this.currentQuizAnalyticsListSortKey(),
        listOrder: this.currentQuizAnalyticsListSortOrder(),
        scoreFilter: this.currentQuizAnalyticsScoreFilter(),
      });
      await this.loadQuizAnalyticsDetail(quizKey);
    },

    async changeQuizAnalyticsVersionId(versionId) {
      const quizKey = this.currentQuizAnalyticsKey() || this.quizAnalyticsDetail?.quiz?.quiz_key || "";
      const next = String(versionId || "").trim();
      if (!quizKey || !next || next === this.currentQuizAnalyticsVersionId()) return;
      this.syncQuizAnalyticsRoute({
        quizKey,
        window: this.currentQuizAnalyticsWindow(),
        startDate: this.currentQuizAnalyticsStartDate(),
        endDate: this.currentQuizAnalyticsEndDate(),
        versionScope: "current",
        versionId: next,
        distributionMode: this.currentQuizAnalyticsDistributionMode(),
        listSort: this.currentQuizAnalyticsListSortKey(),
        listOrder: this.currentQuizAnalyticsListSortOrder(),
        scoreFilter: this.currentQuizAnalyticsScoreFilter(),
      });
      await this.loadQuizAnalyticsDetail(quizKey);
    },

    changeQuizAnalyticsListSort(sortKey) {
      const nextKey = String(sortKey || "").trim().toLowerCase();
      if (!["time", "score"].includes(nextKey)) return;
      const currentKey = this.currentQuizAnalyticsListSortKey();
      const currentOrder = this.currentQuizAnalyticsListSortOrder();
      const nextOrder = currentKey === nextKey
        ? (currentOrder === "desc" ? "asc" : "desc")
        : "desc";
      this.syncQuizAnalyticsRoute({
        quizKey: this.currentQuizAnalyticsKey() || this.quizAnalyticsDetail?.quiz?.quiz_key || "",
        window: this.currentQuizAnalyticsWindow(),
        startDate: this.currentQuizAnalyticsStartDate(),
        endDate: this.currentQuizAnalyticsEndDate(),
        versionScope: this.currentQuizAnalyticsVersionScope(),
        versionId: this.currentQuizAnalyticsVersionId(),
        distributionMode: this.currentQuizAnalyticsDistributionMode(),
        listSort: nextKey,
        listOrder: nextOrder,
        scoreFilter: this.currentQuizAnalyticsScoreFilter(),
      });
    },

    toggleQuizAnalyticsScoreFilter(group, row) {
      if (row?.kind !== "bucket") return;
      const count = Number(row?.count || 0);
      if (count <= 0) return;
      const nextFilter = {
        scoreMax: Number(group?.score_max || 0),
        start: Number(row?.start || 0),
        end: Number(row?.end || 0),
      };
      if (!nextFilter.scoreMax || nextFilter.end < nextFilter.start) return;
      const active = this.quizAnalyticsDistributionRowIsActive(group, row);
      this.syncQuizAnalyticsRoute({
        quizKey: this.currentQuizAnalyticsKey() || this.quizAnalyticsDetail?.quiz?.quiz_key || "",
        window: this.currentQuizAnalyticsWindow(),
        startDate: this.currentQuizAnalyticsStartDate(),
        endDate: this.currentQuizAnalyticsEndDate(),
        versionScope: this.currentQuizAnalyticsVersionScope(),
        versionId: this.currentQuizAnalyticsVersionId(),
        distributionMode: this.currentQuizAnalyticsDistributionMode(),
        listSort: this.currentQuizAnalyticsListSortKey(),
        listOrder: this.currentQuizAnalyticsListSortOrder(),
        scoreFilter: active ? null : nextFilter,
      });
    },

    clearQuizAnalyticsScoreFilter() {
      if (!this.currentQuizAnalyticsScoreFilter()) return;
      this.syncQuizAnalyticsRoute({
        quizKey: this.currentQuizAnalyticsKey() || this.quizAnalyticsDetail?.quiz?.quiz_key || "",
        window: this.currentQuizAnalyticsWindow(),
        startDate: this.currentQuizAnalyticsStartDate(),
        endDate: this.currentQuizAnalyticsEndDate(),
        versionScope: this.currentQuizAnalyticsVersionScope(),
        versionId: this.currentQuizAnalyticsVersionId(),
        distributionMode: this.currentQuizAnalyticsDistributionMode(),
        listSort: this.currentQuizAnalyticsListSortKey(),
        listOrder: this.currentQuizAnalyticsListSortOrder(),
        scoreFilter: null,
      });
    },

    async applyQuizAnalyticsCustomDateRange() {
      const quizKey = this.currentQuizAnalyticsKey() || this.quizAnalyticsDetail?.quiz?.quiz_key || "";
      const startDate = String(this.filters?.quizAnalytics?.start_date || "").trim();
      const endDate = String(this.filters?.quizAnalytics?.end_date || "").trim();
      if (!startDate || !endDate) {
        this.showNotice("请选择开始日期和结束日期");
        return;
      }
      if (startDate > endDate) {
        this.showNotice("开始日期不能晚于结束日期");
        return;
      }
      this.syncQuizAnalyticsRoute({
        quizKey,
        window: "custom",
        startDate,
        endDate,
        versionScope: this.currentQuizAnalyticsVersionScope(),
        versionId: this.currentQuizAnalyticsVersionId(),
        distributionMode: this.currentQuizAnalyticsDistributionMode(),
        listSort: this.currentQuizAnalyticsListSortKey(),
        listOrder: this.currentQuizAnalyticsListSortOrder(),
        scoreFilter: this.currentQuizAnalyticsScoreFilter(),
      });
      await this.loadQuizAnalyticsDetail(quizKey);
    },

    scheduleQuizAnalyticsReloadFromFirstPage() {
      window.clearTimeout(this.quizAnalyticsFilterTimer);
      this.quizAnalyticsFilterTimer = window.setTimeout(() => {
        this.changeQuizAnalyticsPage(1);
      }, 220);
    },

    async changeQuizAnalyticsPage(page) {
      const nextPage = Math.max(1, Number(page || 1));
      await this.loadQuizAnalyticsList({ page: nextPage });
      const items = Array.isArray(this.quizAnalytics?.items) ? this.quizAnalytics.items : [];
      const currentKey = this.currentQuizAnalyticsKey();
      const hasCurrent = items.some((item) => String(item?.quiz_key || "").trim() === currentKey);
      const nextItem = (hasCurrent && currentKey)
        ? items.find((item) => String(item?.quiz_key || "").trim() === currentKey)
        : items[0];
      if (nextItem) {
        await this.loadQuizAnalyticsDetail(String(nextItem.quiz_key || "").trim());
      } else {
        this.resetQuizAnalyticsDetail();
      }
    },

    quizAnalyticsHasPagination() {
      return Number(this.quizAnalytics?.total_pages || 1) > 1;
    },

    canGoToPreviousQuizAnalyticsPage() {
      return Number(this.quizAnalytics?.page || 1) > 1;
    },

    canGoToNextQuizAnalyticsPage() {
      return Number(this.quizAnalytics?.page || 1) < Number(this.quizAnalytics?.total_pages || 1);
    },

    quizAnalyticsPaginationButtonClass(disabled) {
      return disabled
        ? "rounded-xl border border-slate-200 bg-white/70 px-3 py-2 text-xs font-medium text-slate-300"
        : "rounded-xl border border-blue-100 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-blue-50 hover:text-blue-700";
    },
  };
}
