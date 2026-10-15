import { Logo } from "../components/logo";

/** The logo and name above the setup, sign-in, and boot screens, where the
 * site header isn't shown. */
export function AuthBrand() {
  return (
    <div className="auth-brand">
      <Logo size={56} />
      <div className="auth-brand-name">Cabinet</div>
      <div className="auth-brand-subtitle">Numismatics: Coin &amp; Paper Money Collection Manager</div>
    </div>
  );
}
