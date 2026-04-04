import { OTP_LENGTH } from "./constants.js";

export function createPublicState() {
  return {
    booting: true,
    loading: false,
    actionBusy: false,
    timeoutSubmitting: false,
    error: "",
    smsSending: false,
    smsFeedback: { kind: "", message: "" },
    smsCooldownRemaining: 0,
    smsCooldownDeadline: 0,
    smsCooldownTimer: null,
    verifySubmitting: false,
    viewCard: "unavailable",
    route: { kind: "", token: "" },
    sessionId: "",
    state: { step: "", assignment: {}, quiz: {}, result: {}, resume: {}, verify: {}, unavailable: {} },
    forms: {
      verify: { name: "", phone: "", sms_code: "", sms_code_digits: Array(OTP_LENGTH).fill("") },
    },
    textDraft: "",
    selectedMultiple: [],
    autosaveMessage: "",
    autosaveTimer: null,
    questionTimer: null,
    questionRemainingSeconds: 0,
    questionRemainingMs: 0,
    touchStart: null,
    fragmentCache: {},
  };
}
