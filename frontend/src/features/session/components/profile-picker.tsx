'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useSession } from '@/store/session';
import { useRouter } from 'next/navigation';
import { useEmployees } from '../hooks/useSessionQueries';

const APPROVER_ROLES = ['Reporting Manager', 'Head of Department', 'Head of Division', 'MD'];

/**
 * The way in. Two columns, because the whole application has two profiles and showing them
 * side by side is the fastest way for a reviewer to understand that.
 *
 * This is not authentication and does not pretend to be - see docs/NOTE.md.
 */
export function ProfilePicker() {
  const { data: employees, isLoading, error } = useEmployees();
  const signIn = useSession(state => state.signIn);
  const router = useRouter();

  const choose = (code: string, isAdmin: boolean) => {
    signIn(code);
    router.push(isAdmin ? '/admin' : '/employee');
  };

  if (isLoading) return <p className="text-muted-foreground text-sm">Loading the directory…</p>;
  if (error) {
    return (
      <p className="text-sm text-rose-700">
        {(error as Error).message} — is the API running on port 8000?
      </p>
    );
  }

  const people = employees ?? [];
  const travellers = people.filter(person => person.role === 'Employee');
  const approvers = people.filter(person => person.role !== 'Employee');

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Employee</CardTitle>
          <p className="text-muted-foreground text-sm">
            Upload bills, check what policy allows, submit the claim, follow it.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {travellers.map(person => (
            <Button
              key={person.emp_code}
              variant="outline"
              className="h-auto w-full justify-between py-2.5 text-left"
              onClick={() => choose(person.emp_code, false)}
            >
              <span>
                <span className="block font-medium">{person.name}</span>
                <span className="text-muted-foreground block text-xs">{person.designation}</span>
              </span>
              <Badge variant="outline">{person.emp_code}</Badge>
            </Button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Approver &amp; Finance</CardTitle>
          <p className="text-muted-foreground text-sm">
            See what has been routed to you, and approve, return or reject it.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {approvers.map(person => (
            <Button
              key={person.emp_code}
              variant="outline"
              className="h-auto w-full justify-between py-2.5 text-left"
              onClick={() => choose(person.emp_code, true)}
            >
              <span>
                <span className="block font-medium">{person.name}</span>
                <span className="text-muted-foreground block text-xs">{person.designation}</span>
              </span>
              <Badge variant={APPROVER_ROLES.includes(person.role) ? 'secondary' : 'outline'}>
                {person.role}
              </Badge>
            </Button>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
