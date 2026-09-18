import Link from "next/link";
import { Icon } from "./icons";

interface SectionHeaderProps {
  title: string;
  sub?: string;
  link?: { href: string; label: string };
}

export function SectionHeader({ title, sub, link }: SectionHeaderProps) {
  return (
    <div className="card-head">
      <div>
        <h2 className="card-title">{title}</h2>
        {sub && <p className="card-sub">{sub}</p>}
      </div>
      {link && (
        <Link href={link.href} className="card-link">
          {link.label}
          <Icon name="chevron-right" size={14} />
        </Link>
      )}
    </div>
  );
}
