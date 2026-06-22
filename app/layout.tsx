import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Automated Trading System — Design",
  description:
    "Engineering design for a risk-first automated trading system targeting Interactive Brokers (IBKR). Not financial advice.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
