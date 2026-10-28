import Image from "next/image";

export function Brand({
  className = "",
  logoSize = 32,
  stacked = false,
}: {
  className?: string;
  logoSize?: number;
  stacked?: boolean;
}) {
  return (
    <span className={`inline-flex items-center gap-2 ${stacked ? "flex-col" : ""} ${className}`}>
      <Image src="/logo.png" alt="" width={logoSize} height={logoSize} priority />
      <span className="font-display font-bold tracking-widest">
        <span className="text-cyan-ink glow-cyan">MEGOO</span>
        <span className="text-pink glow-pink">COLAB</span>
      </span>
    </span>
  );
}
