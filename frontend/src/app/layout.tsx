import type { Metadata } from "next";
import { Big_Shoulders, Public_Sans } from "next/font/google";
import Link from "next/link";

import { APP_NAME } from "@/lib/brand";

import "./globals.css";

const publicSans = Public_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-public-sans",
});

const bigShoulders = Big_Shoulders({
  subsets: ["latin"],
  weight: ["700", "800"],
  display: "swap",
  fallback: ["Arial Narrow", "sans-serif"],
  adjustFontFallback: false,
  variable: "--font-big-shoulders",
});

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s | ${APP_NAME}` },
  description: "Find out whether an AI support agent built on your help center is safe to deploy.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${publicSans.variable} ${bigShoulders.variable} antialiased`}>
      <body className="flex min-h-screen flex-col">
        <header className="border-b border-rule">
          <div className="mx-auto flex max-w-[46rem] items-center px-5 py-4">
            <Link href="/" className="font-display text-2xl font-extrabold text-ink no-underline">
              {APP_NAME}
            </Link>
          </div>
        </header>
        <div className="flex-1">{children}</div>
        <footer className="border-t border-rule">
          <p className="mx-auto max-w-[46rem] px-5 py-6 text-sm text-graphite">
            {APP_NAME} checks whether an AI support agent built on a public help center is
            ready for real customers.
          </p>
        </footer>
      </body>
    </html>
  );
}
