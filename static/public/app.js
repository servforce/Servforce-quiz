import { createPublicApiModule } from "./modules/api.js";
import { createPublicQuizModule } from "./modules/quiz.js";
import { createPublicResumeModule } from "./modules/resume.js";
import { createPublicRouterModule } from "./modules/router.js";
import { createPublicState } from "./modules/state.js";
import { createPublicVerifyModule } from "./modules/verify.js";
import { createPublicViewLoaderModule } from "./modules/view-loader.js";

const register = () => {
  if (!window.Alpine) return;
  window.Alpine.data("publicApp", () => ({
    ...createPublicState(),
    ...createPublicApiModule(),
    ...createPublicViewLoaderModule(),
    ...createPublicRouterModule(),
    ...createPublicVerifyModule(),
    ...createPublicResumeModule(),
    ...createPublicQuizModule(),
  }));
};

if (window.Alpine) {
  register();
} else {
  document.addEventListener("alpine:init", register, { once: true });
}
