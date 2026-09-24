// The one copy of the exposure warning (SPEC_0330 section 12, Q16, Q17):
// shown in Settings -> Sign-in and, with the same paragraph, under
// Settings -> Sharing's own description. Nothing else duplicates the words.

export const EXPOSURE_WARNING =
  "Cabinet is for private networks. Single sign-on adds your provider's second factor to " +
  "its own button, not to the password, which stays a one-factor recovery credential. Do not " +
  "expose Cabinet to the internet; reach it over a VPN or an identity-aware tunnel.";

export const EXPOSURE_GUIDANCE_URL =
  "https://github.com/jsaumer/cabinet-numismatics/blob/main/docs/deployment.md#2-exposure-cabinet-is-for-private-networks";
