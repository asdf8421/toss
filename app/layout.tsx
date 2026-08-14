import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.includes("localhost") || host.startsWith("127.") ? "http" : "https");
  const origin = `${protocol}://${host}`;

  return {
    title: "Evidence First · AI Fund Manager",
    description: "숫자는 퀀트가 계산하고 AI는 반대편에서 심사하는 증거 우선 투자 시스템.",
    openGraph: {
      title: "Evidence First · AI Fund Manager",
      description: "추천하지 않는 능력까지 설계한 감사 가능한 투자위원회.",
      type: "website",
      images: [{ url: `${origin}/og.png`, width: 1200, height: 630, alt: "Evidence First AI Fund Manager" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "Evidence First · AI Fund Manager",
      description: "추천하지 않는 능력까지 설계한 감사 가능한 투자위원회.",
      images: [`${origin}/og.png`],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
