import { AlertCircle, LoaderCircle } from "lucide-react";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state-panel" role="status">
      <LoaderCircle className="spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="state-panel state-error" role="alert">
      <AlertCircle aria-hidden="true" />
      <div><strong>Something went wrong</strong><p>{message}</p></div>
      {retry ? <button className="button button-secondary" onClick={retry}>Try again</button> : null}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><strong>{title}</strong><p>{detail}</p></div>;
}
