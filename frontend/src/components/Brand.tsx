export function Brand({ className = "" }: { className?: string }) {
  return (
    <span className={`font-display font-bold tracking-widest ${className}`}>
      <span className="text-cyan-ink glow-cyan">MEGOO</span>
      <span className="text-pink glow-pink">COLAB</span>
    </span>
  );
}
