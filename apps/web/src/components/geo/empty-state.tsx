import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-14 text-center">
      <Icon className="text-muted-foreground mb-3 size-8" aria-hidden="true" />
      <p className="font-medium">{title}</p>
      <p className="text-muted-foreground mt-1 max-w-md text-sm">{description}</p>
      {children && <div className="mt-4 flex gap-2">{children}</div>}
    </div>
  );
}
