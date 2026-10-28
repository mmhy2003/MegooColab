import Image from "next/image";

export function Brand({
  className = "",
  logoSize = 32,
  stacked = false,
  nameClassName = "",
}: {
  className?: string;
  logoSize?: number;
  stacked?: boolean;
  /** Extra classes for the name beside the logo (the collapsed sidebar hides it). */
  nameClassName?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 ${stacked ? "flex-col" : ""} ${className}`}>
      <Image src="/logo.png" alt="" width={logoSize} height={logoSize} priority className="shrink-0" />
      <span className={`font-brand font-bold tracking-widest whitespace-nowrap ${nameClassName}`}>
        <span className="text-cyan-ink glow-cyan">MEGOO</span>
        <span className="text-pink glow-pink">COLAB</span>
      </span>
    </span>
  );
}
