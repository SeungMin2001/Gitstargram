import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Gitstargram — Discover the work behind the code",
  description: "A developer social space powered by your real GitHub activity.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ko"><body>{children}</body></html>;
}

