// EmptyState — default "nothing to show" placeholder. Prefer this over
// rendering nothing so users see intentional absence, not a blank section.
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  message: string;
}

export default function EmptyState({ message }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-td-gray-dark">
      <Inbox className="h-12 w-12 mb-3 opacity-40" />
      <p className="text-sm">{message}</p>
    </div>
  );
}
