export const SESSION_HEADER = "X-Public-Session-Id";
export const OTP_LENGTH = 4;

export const createSessionId = () => {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
};
