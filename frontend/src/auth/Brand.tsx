/** The logo and name above the setup, sign-in, and boot screens, where the
 * site header isn't shown. */
export function AuthBrand() {
  return (
    <div className="auth-brand">
      <img src="/logo.svg" alt="" width="56" height="56" />
      <div className="auth-brand-name">Cabinet</div>
      <div className="auth-brand-subtitle">Numismatics: Coin &amp; Paper Money Collection Manager</div>
    </div>
  );
}
