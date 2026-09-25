export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    // Stacks below md (toolbars get their own full-width row and wrap);
    // side-by-side above, with the toolbar still allowed to wrap so it never
    // crushes the title column.
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="text-muted-foreground mt-1.5 max-w-2xl text-sm leading-relaxed">{description}</p>
        )}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2 md:justify-end">{children}</div>}
    </div>
  );
}
