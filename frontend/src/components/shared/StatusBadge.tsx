// StatusBadge — pill that colours itself based on a backend status string.
// Covers the combinations the /health endpoint returns (ready, stopped,
// mock_ready, real_ready, degraded, initialising, not_ready, error).
// Unknown statuses degrade to a neutral grey so new backend states don't
// break the UI.

interface StatusBadgeProps {
  status: string;
}

const STATUS_STYLES: Record<string, string> = {
  ready: "bg-green-100 text-green-800",
  stopped: "bg-red-100 text-red-800",
  error: "bg-red-100 text-red-800",
  mock_ready: "bg-yellow-100 text-yellow-800",
  real_ready: "bg-green-100 text-green-800",
  degraded: "bg-yellow-100 text-yellow-800",
  initialising: "bg-blue-100 text-blue-800",
  not_ready: "bg-gray-100 text-gray-800",
};

const STATUS_LABELS: Record<string, string> = {
  ready: "Ready",
  stopped: "Stopped",
  error: "Error",
  mock_ready: "Mock Mode",
  real_ready: "Ready (Real)",
  degraded: "Degraded",
  initialising: "Starting...",
  not_ready: "Not Ready",
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const style = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-800";
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${style}`}
    >
      {label}
    </span>
  );
}
