import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, RefreshCw } from 'lucide-react';
import { GuardianWordmark } from './GuardianWelcome';
import '@/public-access.css';

const DEADLINE_MS = 5000;
const INITIAL_FIELDS = { name: '', email: '', company: '', use_case: '', consent: false };
const CONSENT = 'I agree that Sillage may store these details for up to 180 days and contact me about early access.';

function validEmail(value) {
  if (typeof value !== 'string') return false;
  const email = value.trim().toLowerCase();
  if (email.length > 254 || !/^[\x21-\x7e]+$/.test(email)) return false;
  const parts = email.split('@');
  if (parts.length !== 2) return false;
  const [local, domain] = parts;
  if (local.length > 64 || !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+$/.test(local)
    || local.startsWith('.') || local.endsWith('.') || local.includes('..')) return false;
  const labels = domain.split('.');
  return labels.length >= 2 && !labels.some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))
    && !/^\d+$/.test(labels[labels.length - 1]);
}

function stopRequest(ref) {
  const request = ref.current;
  ref.current = null;
  if (request) {
    clearTimeout(request.timer);
    request.controller.abort();
  }
}

function workspaceOrigin(value) {
  if (typeof value !== 'string' || value.length > 2048 || value.trim() !== value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) return null;
    if (value !== url.origin && value !== `${url.origin}/`) return null;
    return url.origin;
  } catch (_) {
    return null;
  }
}

function availabilityResult(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).sort().join(',') !== 'available,reason,workspace_url') return null;
  if (value.available === true && value.reason === 'ready') {
    const origin = workspaceOrigin(value.workspace_url);
    return origin ? { state: 'ready', origin } : null;
  }
  if (value.available === false && value.workspace_url === null
    && ['coming_soon', 'unavailable'].includes(value.reason)) return { state: value.reason, origin: null };
  return null;
}

function savedAcknowledgment(value) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === 'registered,schema_version,status'
    && value.registered === true && value.schema_version === 1 && value.status === 'interest_recorded';
}

function PublicFrame({ children }) {
  return <div className="sillage-public-access">
    <header className="sillage-access-header">
      <a href="/welcome" aria-label="Sillage home"><GuardianWordmark /></a>
      <nav aria-label="Public navigation"><a href="/demo">Demo</a><a href="/signin">Sign in</a><a className="sillage-access-nav-signup" href="/signup">Sign up <ArrowRight size={14} /></a></nav>
    </header>
    {children}
    <footer className="sillage-access-footer"><span>Understanding what passed through.</span><a href="/privacy">Privacy &amp; your details</a></footer>
  </div>;
}

function useWorkspaceAvailability(enabled = true) {
  const [access, setAccess] = useState({ state: enabled ? 'checking' : 'idle', origin: null });
  const availabilityRequest = useRef(null);
  const checkAccess = useCallback(async () => {
    stopRequest(availabilityRequest);
    if (!enabled) {
      setAccess({ state: 'idle', origin: null });
      return;
    }
    const request = { controller: new AbortController(), timer: null };
    availabilityRequest.current = request;
    setAccess({ state: 'checking', origin: null });
    request.timer = setTimeout(() => {
      if (availabilityRequest.current !== request) return;
      stopRequest(availabilityRequest);
      setAccess({ state: 'unavailable', origin: null });
    }, DEADLINE_MS);
    try {
      const response = await fetch('/api/availability', { method: 'GET', credentials: 'omit', mode: 'same-origin',
        cache: 'no-store', referrerPolicy: 'no-referrer', headers: { Accept: 'application/json' }, signal: request.controller.signal });
      if (response.status !== 200) throw new Error('availability_unconfirmed');
      const result = availabilityResult(await response.json());
      if (!result) throw new Error('availability_unconfirmed');
      if (availabilityRequest.current === request) setAccess(result);
    } catch (_) {
      if (availabilityRequest.current === request) setAccess({ state: 'unavailable', origin: null });
    } finally {
      if (availabilityRequest.current === request) stopRequest(availabilityRequest);
    }
  }, [enabled]);
  useEffect(() => {
    checkAccess();
    return () => stopRequest(availabilityRequest);
  }, [checkAccess]);
  return { access, checkAccess };
}

export default function PublicAccess({ intent = 'signin' }) {
  const source = ['signup', 'signin', 'onboarding'].includes(intent) ? intent : 'signin';
  const [fields, setFields] = useState({ ...INITIAL_FIELDS });
  const [submission, setSubmission] = useState({ state: 'idle', message: '' });
  const { access, checkAccess } = useWorkspaceAvailability(source !== 'signup' && submission.state !== 'saved');
  const interestRequest = useRef(null);
  const formRef = useRef(null);
  const optionalDetails = useRef(null);

  useEffect(() => {
    setFields({ ...INITIAL_FIELDS });
    setSubmission({ state: 'idle', message: '' });
    return () => stopRequest(interestRequest);
  }, [source]);

  const update = event => {
    const { name, type, value, checked } = event.target;
    setFields(previous => ({ ...previous, [name]: type === 'checkbox' ? checked : value }));
  };
  const invalid = (message, field) => {
    setSubmission({ state: 'error', message });
    if (['company', 'use_case'].includes(field) && optionalDetails.current) optionalDetails.current.open = true;
    formRef.current?.elements.namedItem(field)?.focus();
  };
  const submit = async event => {
    event.preventDefault();
    if (interestRequest.current || submission.state === 'saved') return;
    const name = fields.name.trim().normalize('NFC');
    const email = fields.email.trim();
    const company = fields.company.trim().normalize('NFC');
    const useCase = fields.use_case.trim().normalize('NFC');
    if (!name || name.length > 100 || /[\u0000-\u001f\u007f]/.test(name)) return invalid('Enter your name (up to 100 characters).', 'name');
    if (!validEmail(email)) return invalid('Enter a valid email address.', 'email');
    if (company.length > 120) return invalid('Keep your company name within 120 characters.', 'company');
    if (useCase.length > 1200) return invalid('Keep your description within 1,200 characters.', 'use_case');
    if (!fields.consent) return invalid('Please agree to how we will use your details before registering.', 'consent');
    const body = { schema_version: 1, name, email, consent: true, source,
      ...(company ? { company } : {}), ...(useCase ? { use_case: useCase } : {}) };
    const encoded = JSON.stringify(body);
    if (new TextEncoder().encode(encoded).length > 4096) return invalid('Please shorten your description or company name before registering.', 'use_case');
    const request = { controller: new AbortController(), timer: null };
    interestRequest.current = request;
    setSubmission({ state: 'saving', message: '' });
    request.timer = setTimeout(() => {
      if (interestRequest.current !== request) return;
      stopRequest(interestRequest);
      setSubmission({ state: 'error', message: 'We could not confirm that your details were saved. Please try again.' });
    }, DEADLINE_MS);
    try {
      const response = await fetch('/api/interest', { method: 'POST', credentials: 'omit', mode: 'same-origin',
        cache: 'no-store', referrerPolicy: 'no-referrer', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: encoded, signal: request.controller.signal });
      if (interestRequest.current !== request) return;
      if (response.status === 400 || response.status === 413) {
        setSubmission({ state: 'error', message: response.status === 400
          ? 'Please check your name, email and other details, then try again.'
          : 'Please shorten your description or company name before registering.' });
        return;
      }
      if (response.status === 429) {
        setSubmission({ state: 'error', message: 'Please wait a moment before trying again. Your details are still in the form.' });
        return;
      }
      if (response.status !== 202 || !savedAcknowledgment(await response.json())) throw new Error('registration_unconfirmed');
      if (interestRequest.current === request) {
        setFields({ ...INITIAL_FIELDS });
        setSubmission({ state: 'saved', message: '' });
        // The confirmation lives only in this mounted component. Reloading the
        // public route cannot reconstruct a successful registration from a URL.
        try { window.history.replaceState(null, '', '/waitlist'); } catch { /* The acknowledged registration remains true. */ }
      }
    } catch (_) {
      if (interestRequest.current === request) setSubmission({ state: 'error',
        message: 'We could not confirm that your details were saved. Please try again.' });
    } finally {
      if (interestRequest.current === request) stopRequest(interestRequest);
    }
  };

  if (submission.state === 'saved') return <WaitlistPage confirmed />;
  const title = source === 'signup' ? 'A clearer view of your AI.'
    : access.state === 'checking' ? 'Checking workspace access…'
      : access.state === 'ready' ? 'Your workspace is ready.'
        : access.state === 'coming_soon' ? 'Sign-in is coming soon' : 'Currently unavailable';
  return <PublicFrame><main className="sillage-access-main">
    <section className="sillage-access-story" aria-labelledby="public-access-title">
      <p className="sillage-access-eyebrow">THE WORK BEHIND THE ANSWER</p>
      <div aria-live="polite" aria-atomic="true"><h1 id="public-access-title">{title}</h1>
        <p>{source === 'signup' ? 'Follow the calls. Find the slow step. Understand the cost of an answer.'
          : access.state === 'checking' ? 'You can explore the demo or register while we check.'
            : access.state === 'ready' ? 'Continue to your workspace to sign in and connect your application.'
              : 'Thanks for your interest in Sillage. Register below and we’ll keep you updated about access.'}</p></div>
      <div className="sillage-access-actions">
        {access.state === 'ready' && <a className="sillage-access-primary" referrerPolicy="no-referrer"
          href={`${access.origin}/${source === 'onboarding' ? 'setup' : 'signin'}`}>
          {source === 'onboarding' ? 'Sign in and connect' : 'Sign in to your workspace'}<ArrowRight size={16} /></a>}
        {['unavailable', 'coming_soon'].includes(access.state) && <button className="sillage-access-secondary" onClick={checkAccess}>
          <RefreshCw size={15} /> Retry access</button>}
        <a className="sillage-access-demo" href="/demo">Explore the interactive demo <ArrowRight size={15} /></a>
      </div>
      <div className="sillage-access-promise"><span>Sillage / noun</span>
        <p>Understanding what passed through<br />by the wake it leaves.</p></div>
    </section>
    <section className="sillage-interest-panel" aria-labelledby="interest-title">
      <p className="sillage-access-eyebrow">SIGN UP</p><h2 id="interest-title">Register with Sillage.</h2>
        <p className="sillage-interest-intro">A name, an email, a place to start.</p>
        <form ref={formRef} onSubmit={submit} noValidate aria-label="Register with Sillage">
          <fieldset disabled={submission.state === 'saving'}><legend className="sillage-visually-hidden">Your registration details</legend>
            <div className="sillage-interest-field"><label htmlFor="interest-name">Your name <span>(required)</span></label>
              <input id="interest-name" name="name" value={fields.name} onChange={update} autoComplete="name" maxLength={100} required /></div>
            <div className="sillage-interest-field"><label htmlFor="interest-email">Email <span>(required)</span></label>
              <input id="interest-email" name="email" type="email" value={fields.email} onChange={update} autoComplete="email" maxLength={254} required /></div>
            <details ref={optionalDetails} className="sillage-interest-optional"><summary>Add company or project details <span>(optional)</span></summary>
            <div className="sillage-interest-field"><label htmlFor="interest-company">Company <span>(optional)</span></label>
              <input id="interest-company" name="company" value={fields.company} onChange={update} autoComplete="organization" maxLength={120} /></div>
            <div className="sillage-interest-field"><label htmlFor="interest-use-case">What are you building? <span>(optional)</span></label>
              <textarea id="interest-use-case" name="use_case" value={fields.use_case} onChange={update} maxLength={1200} rows={3}
                aria-describedby="interest-use-case-note" /><small id="interest-use-case-note">A short description is enough. Please leave out private customer information.</small></div></details>
            <div className="sillage-interest-consent"><input id="interest-consent" name="consent" type="checkbox" checked={fields.consent} onChange={update} required />
              <label htmlFor="interest-consent">{CONSENT} <a href="/privacy">Read the privacy notice.</a></label></div>
            <button type="submit" className="sillage-access-primary">{submission.state === 'saving' ? 'Saving…' : 'Register'}<ArrowRight size={16} /></button>
          </fieldset>
          {submission.state === 'error' && <p className="sillage-interest-error" role="alert">{submission.message}</p>}
          {submission.state === 'saving' && <p className="sillage-interest-progress" role="status">Saving your registration…</p>}
          <p className="sillage-interest-note">Registration saves your contact details. Workspace sign-in is separate.</p>
        </form>
    </section>
  </main></PublicFrame>;
}

export function WaitlistPage({ confirmed = false }) {
  const { access, checkAccess } = useWorkspaceAvailability();
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, [confirmed]);
  return <PublicFrame><main className="sillage-waitlist-main" aria-labelledby="waitlist-title">
    <section className="sillage-waitlist-confirmation">
      {confirmed && <span className="sillage-interest-check" aria-hidden="true"><Check size={22} /></span>}
      <p className="sillage-access-eyebrow">{confirmed ? 'REGISTRATION RECEIVED' : 'YOUR NEXT STEP'}</p>
      <h1 id="waitlist-title" ref={heading} tabIndex={-1}>{confirmed ? 'You’re on the list.' : 'Find your way into Sillage.'}</h1>
      <p className="sillage-waitlist-description" role="status">{confirmed
        ? 'We’ve received your registration. We’ll contact you about access using the details you provided.'
        : 'This page cannot confirm a registration. Register to join the list, or check whether you can sign in.'}</p>
      {confirmed && <p className="sillage-waitlist-note">This does not create an account or sign you in.</p>}
    </section>
    <section className="sillage-waitlist-next" aria-labelledby="waitlist-next-title" aria-live="polite">
      <p className="sillage-access-eyebrow">WHAT HAPPENS NEXT</p>
      <h2 id="waitlist-next-title">{access.state === 'checking' ? 'Checking workspace availability…'
        : access.state === 'ready' ? 'Already have workspace access?'
          : access.state === 'coming_soon' ? 'Workspace access is coming soon.' : 'Workspace sign-in is currently unavailable.'}</h2>
      <p>{access.state === 'ready' ? 'If you’ve already been given access, continue to your workspace to sign in.'
        : access.state === 'checking' ? 'You can explore the product while we check.'
          : confirmed ? 'Your registration is recorded. Explore the demo while you wait for access.'
            : 'You can register or explore the demo while workspace access is unavailable.'}</p>
      <div className="sillage-waitlist-actions">
        {!confirmed && <a href="/signup" className="sillage-access-primary">Sign up <ArrowRight size={16} /></a>}
        {access.state === 'ready' && <a className={confirmed ? 'sillage-access-primary' : 'sillage-access-secondary'}
          referrerPolicy="no-referrer" href={`${access.origin}/signin`}>Sign in <ArrowRight size={16} /></a>}
        <a href="/demo" className={confirmed && access.state !== 'ready' ? 'sillage-access-primary' : 'sillage-access-secondary'}>Explore the demo <ArrowRight size={16} /></a>
        {['coming_soon', 'unavailable'].includes(access.state) && <button className="sillage-waitlist-retry" onClick={checkAccess}><RefreshCw size={14} /> Check availability again</button>}
      </div>
    </section>
  </main></PublicFrame>;
}

export function PrivacyNotice() {
  const candidate = process.env.REACT_APP_PRIVACY_CONTACT_EMAIL || '';
  const contact = candidate.trim() === candidate && validEmail(candidate) ? candidate : null;
  return <PublicFrame><main className="sillage-privacy-main">
    <p className="sillage-access-eyebrow">YOUR DETAILS, WITH A CLEAR PURPOSE</p><h1>Registration &amp; privacy.</h1>
    <p>When you register interest in Sillage, we collect your name, email address, any company or project description you choose to share, and your permission to contact you.</p>
    <h2>Why we collect it</h2><p>We use these details to understand interest and contact you about early access. Registration is an unverified expression of interest; it does not create an account. Registering does not send an automated email.</p>
    <h2>Where it is kept</h2><p>The public site runs on Vercel. Registration details are saved in the MongoDB service configured by the Sillage operator. This form does not collect passwords, provider keys or application telemetry.</p>
    <p>Sillage keeps your form entries while this page is open and clears them after a confirmed registration. We do not write them to browser storage. Your browser may remember fields through its own autofill settings.</p>
    <h2>How long we keep it</h2><p>An interest record expires 180 days after its first registration. Repeated submissions while it is active keep that original expiry. If you register again after it expires, your new consent starts a new 180-day period.</p>
    <p>Expired records are excluded from contact exports and removed automatically. Deletion may not happen at the exact expiry time.</p>
    <h2>Change your mind</h2><p>You can ask the Sillage operator to delete your details or stop contacting you.
      {contact ? <> Email <a href={`mailto:${encodeURIComponent(contact)}`}>{contact}</a>.</>
        : <> Contact the Sillage operator through the channel where you received this invitation.</>}</p>
    <a className="sillage-access-secondary" href="/signup">Back to sign up <ArrowRight size={15} /></a>
  </main></PublicFrame>;
}
