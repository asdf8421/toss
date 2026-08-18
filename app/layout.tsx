import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.includes("localhost") || host.startsWith("127.") ? "http" : "https");
  const origin = `${protocol}://${host}`;

  return {
    title: "AI Fund Manager · 예측에서 행동까지",
    description: "5·20일 퀀트 예측과 Groq 분석으로 매수·보유·축소·매도 행동을 만드는 투자 의사결정 시스템.",
    openGraph: {
      title: "AI Fund Manager · 예측에서 행동까지",
      description: "퀀트 예측, Groq 근거 분석, 리스크 한도와 주문 계획을 하나로 연결했습니다.",
      type: "website",
      images: [{ url: `${origin}/og-dashboard.png`, width: 1731, height: 909, alt: "AI Fund Manager 투자 의사결정 대시보드" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "AI Fund Manager · 예측에서 행동까지",
      description: "퀀트 예측, Groq 근거 분석, 리스크 한도와 주문 계획을 하나로 연결했습니다.",
      images: [`${origin}/og-dashboard.png`],
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
