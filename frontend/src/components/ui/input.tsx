import { cn } from 'cn';
import * as React from 'react';

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'border-input bg-background placeholder:text-muted-foreground focus-visible:ring-ring/50 flex h-9 w-full min-w-0 rounded-md border px-3 py-1 text-sm shadow-xs transition-[color,box-shadow] outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50',
        'file:text-foreground file:mr-3 file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium',
        className,
      )}
      {...props}
    />
  );
}

export { Input };
