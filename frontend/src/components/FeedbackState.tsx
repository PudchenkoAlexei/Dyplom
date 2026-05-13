import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

export function LoadingState({ message = "Завантаження..." }: { message?: string }) {
  return (
    <div className="feedback-state">
      <Loader2 className="spin" size={22} />
      <span>{message}</span>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="empty-state">
      <Inbox size={22} />
      <span>{message}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-box feedback-error">
      <div>
        <AlertTriangle size={20} />
        <span>{message}</span>
      </div>
      {onRetry && (
        <button className="danger-button" onClick={onRetry} type="button">
          Спробувати ще раз
        </button>
      )}
    </div>
  );
}
