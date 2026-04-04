import { createAdminApiModule } from "./modules/api.js";
import { createAdminRouterModule } from "./modules/router.js";
import { createAdminShellModule } from "./modules/shell.js";
import { createAdminState } from "./modules/state.js";
import { createAdminAssignmentsModule } from "./modules/pages/assignments.js";
import { createAdminCandidatesModule } from "./modules/pages/candidates.js";
import { createAdminLogsModule } from "./modules/pages/logs.js";
import { createAdminQuizzesModule } from "./modules/pages/quizzes.js";
import { createAdminStatusModule } from "./modules/pages/status.js";

const register = () => {
  if (!window.Alpine) return;
  window.Alpine.data("adminApp", () => ({
    ...createAdminState(),
    ...createAdminApiModule(),
    ...createAdminShellModule(),
    ...createAdminQuizzesModule(),
    ...createAdminCandidatesModule(),
    ...createAdminAssignmentsModule(),
    ...createAdminLogsModule(),
    ...createAdminStatusModule(),
    ...createAdminRouterModule(),
  }));
};

if (window.Alpine) {
  register();
} else {
  document.addEventListener("alpine:init", register, { once: true });
}
