/** Indian grouping, right-aligned and tabular so columns of figures line up to the decimal. */
export function Money({ amount, className = '' }: { amount: string; className?: string }) {
  const value = Number(amount);
  const formatted = Number.isFinite(value)
    ? value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : amount;

  return <span className={`tabular-nums ${className}`}>{formatted}</span>;
}
