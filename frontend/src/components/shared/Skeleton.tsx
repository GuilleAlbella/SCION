// Skeleton loading primitives. The `skeleton` CSS class (defined in
// globals.css) handles the shimmer animation; these components just compose
// pre-sized shapes so page-level loaders can mirror the final layout.

interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
}

export function SkeletonLine({ className = "h-4 w-full", style }: SkeletonProps) {
  return <div className={`skeleton ${className}`} style={style} />;
}

export function SkeletonCard() {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-slate-700 p-5 space-y-3">
      <SkeletonLine className="h-3 w-24" />
      <SkeletonLine className="h-8 w-16" />
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden">
      <div className="bg-td-navy h-10" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 px-4 py-3 border-t border-gray-100 dark:border-slate-700">
          <SkeletonLine className="h-4 w-12" />
          <SkeletonLine className="h-4 w-32" />
          <SkeletonLine className="h-4 w-24" />
          <SkeletonLine className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonChart() {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-slate-700 p-5">
      <SkeletonLine className="h-3 w-32 mb-4" />
      <div className="flex items-end gap-2 h-32">
        {[60, 80, 45, 90, 70, 55, 85].map((h, i) => (
          <div key={i} className="flex-1">
            <SkeletonLine className={`w-full`} style={{ height: `${h}%` }} />
          </div>
        ))}
      </div>
    </div>
  );
}
