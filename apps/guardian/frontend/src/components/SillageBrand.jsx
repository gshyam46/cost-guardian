// An original S-shaped wake, shared by the product and its application icons.
export function SillageMark({ className = '', ...props }) {
  return <svg viewBox="0 0 40 40" fill="none" className={className} aria-hidden="true" {...props}>
    <path d="M29 6C17 6 10 10.5 10 17c0 10 20 4 20 14 0 3-8 4-19 4" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    <path d="M29 12c-8 0-13 2-13 5 0 5 19 2 19 12M11 28c8 0 13-2 13-5 0-5-19-2-19-12" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
  </svg>;
}

export function GuardianWordmark({ light = false }) {
  return <span className={`cg-wordmark ${light ? 'cg-wordmark-light' : ''}`}>
    <span className="cg-mark"><SillageMark /></span>
    <span className="cg-wordmark-weight">sillage<span className="cg-wordmark-dot">.</span></span>
  </span>;
}
