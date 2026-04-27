// ErrorAlert — consistent red alert block for recoverable errors
// (failed fetches, validation messages, etc.). For fatal errors prefer an
// error boundary; this is meant to appear inline within a page.
import { AlertTriangle } from "lucide-react";

interface ErrorAlertProps {
  message: string;
}

export default function ErrorAlert({ message }: ErrorAlertProps) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
      <AlertTriangle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
      <p className="text-sm text-red-700">{message}</p>
    </div>
  );
}
