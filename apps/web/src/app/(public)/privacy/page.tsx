import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Privacy Policy — AI Search Growth OS" };

/**
 * Written to match what the product actually does today (see the API
 * codebase): essential auth cookie only, no ad tech, self-serve deletion.
 * Replace the contact address before public launch and have counsel review.
 */
export default function PrivacyPage() {
  return (
    <article className="w-full max-w-2xl pb-16 text-sm leading-6">
      <h1 className="text-2xl font-semibold tracking-tight">Privacy Policy</h1>
      <p className="text-muted-foreground mt-1 text-xs">Last updated: September 27, 2026</p>

      <h2 className="mt-8 text-base font-semibold">What we collect</h2>
      <p className="mt-2">
        Account information you give us: your email address, optional name, and a password (stored
        only as a modern salted hash, never in plain text). Workspace data you create: organizations,
        projects, the website domains you register, prompts, and settings. Product data we generate
        for you: crawled content from the public pages of the websites you register, audit results,
        responses returned by third-party AI providers to the prompts you run, and usage metering
        (token counts and estimated cost per AI call). Operational records: an authentication audit
        log (sign-ins, token refreshes, resets) including IP address and browser user-agent, kept for
        security investigation.
      </p>

      <h2 className="mt-6 text-base font-semibold">Cookies</h2>
      <p className="mt-2">
        We set exactly one cookie: an essential, httpOnly session-refresh cookie that keeps you
        signed in. There are no advertising, analytics, or cross-site tracking cookies.
      </p>

      <h2 className="mt-6 text-base font-semibold">How your data is used</h2>
      <p className="mt-2">
        Solely to provide the product: measuring how AI engines describe your brand, auditing the
        websites you register, and showing you the results. We do not sell your data or use it for
        advertising. Prompts you run are sent to the AI providers you select (such as OpenAI,
        Anthropic, or Google) to obtain their responses; those providers process that content under
        their own terms. Infrastructure providers (hosting, database, email delivery) process data
        on our behalf.
      </p>

      <h2 className="mt-6 text-base font-semibold">Crawled website content</h2>
      <p className="mt-2">
        Our crawler fetches only publicly accessible pages, identifies itself in its user-agent,
        and respects robots.txt. Crawled content is stored to produce your audits and is deleted
        with the project it belongs to.
      </p>

      <h2 className="mt-6 text-base font-semibold">Retention and deletion</h2>
      <p className="mt-2">
        Your data is retained while your account is active. Deleting a project removes its data.
        You can delete your account yourself in Settings — this requires your password, removes
        your organizations that have no other members, and permanently deletes your user record.
        Security audit-log entries are retained with the account reference removed.
      </p>

      <h2 className="mt-6 text-base font-semibold">Your rights</h2>
      <p className="mt-2">
        You can access and correct your account data in the product, and delete it as described
        above. For export requests or anything else, contact us and we will respond within 30
        days: support@aisearchgrowth.example
      </p>

      <p className="text-muted-foreground mt-8">
        <Link href="/terms" className="underline underline-offset-4">
          Terms of Service
        </Link>{" "}
        ·{" "}
        <Link href="/login" className="underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </article>
  );
}
