/**
 * The Sentinel mark: a shield with a watchful eye. The shield is the guarantee (an audit trail you can rely on); the eye is the
 * observation (it records what happened without claiming more). Drawn on a 32x32 grid with one stroke width so it stays legible at 16px.
 * Colours come from the theme (`currentColor` for the outline, the accent token for the eye), so it works in light and dark.
 */
export function SentinelMark({ className = "size-5", title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" role={title ? "img" : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
      <path d="M16 3 5.5 7v8.2c0 6.4 4.3 11.3 10.5 13.8 6.2-2.5 10.5-7.4 10.5-13.8V7L16 3Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M9.5 16.2C11.2 13.4 13.4 12 16 12s4.8 1.4 6.5 4.2C20.8 19 18.6 20.4 16 20.4s-4.8-1.4-6.5-4.2Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="16" cy="16.2" r="2.2" fill="var(--primary)" />
    </svg>
  );
}
