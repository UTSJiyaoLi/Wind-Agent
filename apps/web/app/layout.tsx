import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "中交集团智慧风电智能体平台",
  description: "中交集团智慧风电智能体平台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
