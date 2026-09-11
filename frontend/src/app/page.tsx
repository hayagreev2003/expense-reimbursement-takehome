import { Button } from '@/components/ui/button';

const ROLES = [
  {
    name: 'Employee',
    detail: 'Raise a travel request, review the drafted claim, submit it for approval.',
  },
  {
    name: 'Approver',
    detail: 'Act on claims routed to you by value. Approve, reject, or return with remarks.',
  },
  {
    name: 'Finance',
    detail: 'Verify approved claims, settle against the advance, release in a payment run.',
  },
];

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-10 px-6 py-16">
      <header className="space-y-3">
        <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">
          Nortex Industries Ltd
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-balance">
          Travel expense settlement
        </h1>
        <p className="text-muted-foreground max-w-prose">
          A trip inbox becomes a policy-checked claim: evidence is read, duplicates and
          non-reimbursables are caught alongside the clause that excluded them, and the claim routes
          to the approvers its final value actually requires.
        </p>
      </header>

      <ul className="grid gap-3">
        {ROLES.map(role => (
          <li key={role.name} className="rounded-lg border p-4">
            <h2 className="font-medium">{role.name}</h2>
            <p className="text-muted-foreground mt-1 text-sm">{role.detail}</p>
          </li>
        ))}
      </ul>

      <div>
        <Button disabled>Choose a role</Button>
        <p className="text-muted-foreground mt-2 text-xs">
          Role switching arrives with the workflow surface.
        </p>
      </div>
    </main>
  );
}
