import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Terms of Service — AI Search Growth OS" };

/** Replace the contact address before public launch and have counsel review. */
export default function TermsPage() {
  return (
    <article className="w-full max-w-2xl pb-16 text-sm leading-6">
      <h1 className="text-2xl font-semibold tracking-tight">Terms of Service</h1>
      <p className="text-muted-foreground mt-1 text-xs">Last updated: September 27, 2026</p>

      <h2 className="mt-8 text-base font-semibold">The service</h2>
      <p className="mt-2">
        AI Search Growth OS measures how AI search engines describe and cite your brand, audits
        your website&apos;s readiness for AI search, and helps you act on what it finds. It is
        provided as a hosted service, currently in an early-access phase: features may change, and
        availability is not guaranteed.
      </p>

      <h2 className="mt-6 text-base font-semibold">Your account and acceptable use</h2>
      <p className="mt-2">
        You are responsible for your credentials and for what happens under your account. You may
        only register website domains you own or are authorized to analyze. You agree not to abuse
        the service — including attempting to access other tenants&apos; data, using the crawler
        against sites you have no authorization for, reselling access, or circumventing usage
        limits. We may suspend accounts that do.
      </p>

      <h2 className="mt-6 text-base font-semibold">AI-generated content</h2>
      <p className="mt-2">
        Measurements are built from responses produced by third-party AI models. Those responses
        can be wrong, incomplete, or change over time. The product reports what was observed —
        treat scores and findings as evidence for your own judgment, not as guarantees of
        ranking, traffic, or business outcomes.
      </p>

      <h2 className="mt-6 text-base font-semibold">Your data</h2>
      <p className="mt-2">
        Your workspace data remains yours. You grant us the rights needed to operate the service on
        it (storing, processing, and sending your prompts to the AI providers you select). Handling
        of personal data is described in the{" "}
        <Link href="/privacy" className="underline underline-offset-4">
          Privacy Policy
        </Link>
        .
      </p>

      <h2 className="mt-6 text-base font-semibold">Termination</h2>
      <p className="mt-2">
        You can stop using the service and delete your account at any time in Settings. We may
        terminate accounts for breach of these terms. On deletion, your data is removed as
        described in the Privacy Policy.
      </p>

      <h2 className="mt-6 text-base font-semibold">Disclaimers and liability</h2>
      <p className="mt-2">
        The service is provided &quot;as is&quot; without warranties of any kind, to the extent
        permitted by law. To the same extent, our aggregate liability for claims relating to the
        service is limited to the amounts you paid for it in the twelve months before the claim.
      </p>

      <h2 className="mt-6 text-base font-semibold">Changes and contact</h2>
      <p className="mt-2">
        We may update these terms; material changes will be announced in the product with
        reasonable notice. Questions: support@aisearchgrowth.example
      </p>

      <p className="text-muted-foreground mt-8">
        <Link href="/privacy" className="underline underline-offset-4">
          Privacy Policy
        </Link>{" "}
        ·{" "}
        <Link href="/login" className="underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </article>
  );
}
