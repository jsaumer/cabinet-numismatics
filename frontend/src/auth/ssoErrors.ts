// Sentences for the ?error= and ?confirm_error= codes the sign-in flow
// (docs/api.md's GET /api/auth/oidc/callback) can land on: /login (a
// failed sign-in), /settings/signin (a failed link), and next (a failed
// confirm, App.tsx's signed-in shell). One map, since the codes overlap
// and the wording doesn't depend on which page shows it.

const MESSAGES: Record<string, string> = {
  unlinked:
    "That account isn't linked to Cabinet. Sign in with your password and link it in Settings, Sign-in.",
  provider: "The sign-in provider didn't answer. Sign in with your password.",
  denied: "You cancelled at the provider.",
  token: "The provider's answer couldn't be verified. Sign in with your password.",
  profile: "The provider's answer couldn't be checked. Sign in with your password.",
  already_linked: "That identity is already linked.",
  subject:
    "That identity looks like an email address or a username, which the provider may let " +
    "someone else claim; set the provider's subject to a stable id.",
  session: "Start the link from Settings again.",
  confirm_identity: "This session didn't sign in through that provider. Use the password instead.",
  not_qualified: "This provider can't confirm a fresh action. Use the password instead.",
};

const GENERIC = "That sign-in attempt can't be finished. Start again.";

/** state, cookie, expired, navigation, and anything unrecognised all read
 * as one generic sentence: the visitor doesn't need to know which
 * technical step failed, only that starting over is the fix. */
export function ssoErrorMessage(code: string): string {
  return MESSAGES[code] ?? GENERIC;
}
