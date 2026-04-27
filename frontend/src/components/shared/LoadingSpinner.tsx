// LoadingSpinner — despite the name this is a skeleton layout (not a
// spinner). It mimics the generic 4-KPIs-plus-table shell used on most
// SCION pages so the layout doesn't jump when real data arrives.
import { SkeletonCard } from "./Skeleton";

export default function LoadingSpinner({ className = "" }: { className?: string }) {
  return (
    <div className={`space-y-4 ${className}`}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden">
        <div className="bg-td-navy h-10" />
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex gap-4 px-4 py-3 border-t border-gray-100 dark:border-slate-700">
            <div className="skeleton h-4 w-12" />
            <div className="skeleton h-4 w-32" />
            <div className="skeleton h-4 w-24" />
            <div className="skeleton h-4 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}
