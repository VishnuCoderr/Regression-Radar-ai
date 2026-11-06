// src/components/ui/Card.tsx
import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  hover?: boolean;
}

export function Card({ children, className = "", onClick, hover }: CardProps) {
  const base =
    "bg-[#111118] border border-[#2a2a38] rounded-xl";
  const interactive = hover
    ? "cursor-pointer transition-colors hover:border-[#3b82f6]/40 hover:bg-[#111118]/80"
    : "";
  return (
    <div className={`${base} ${interactive} ${className}`} onClick={onClick}>
      {children}
    </div>
  );
}

export function CardHeader({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`px-5 py-4 border-b border-[#2a2a38] ${className}`}>
      {children}
    </div>
  );
}

export function CardBody({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`px-5 py-4 ${className}`}>{children}</div>;
}
